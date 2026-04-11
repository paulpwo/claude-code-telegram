"""Handler for /topics command — add | list | delete subcommands.

Manages the dynamic project-thread registry. Projects registered here
are persisted in the `projects` table and served via
`load_project_registry_from_db` at startup (DB-only mode).

Usage:
  /topics add <slug> <name> <path> [git_url]
  /topics list
  /topics delete <slug>
"""

from pathlib import Path
from typing import List, Optional

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...bot.features.git_integration import GitError, GitIntegration
from ...config.settings import Settings
from ...projects import load_project_registry_from_db
from ...storage.repositories import ProjectRepository

logger = structlog.get_logger()

_USAGE = (
    "Usage: /topics &lt;add|list|delete&gt; [args]\n"
    "/topics add &lt;slug&gt; &lt;name&gt; &lt;path&gt; [git_url]\n"
    "/topics list\n"
    "/topics delete &lt;slug&gt;"
)


async def topics_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Entry point for /topics subcommands: add, list, delete."""
    args: List[str] = context.args or []

    if not args:
        await update.effective_message.reply_text(_USAGE, parse_mode="HTML")
        return

    subcommand = args[0].lower()
    rest = args[1:]

    if subcommand == "add":
        await _topics_add(update, context, rest)
    elif subcommand == "list":
        await _topics_list(update, context)
    elif subcommand == "delete":
        await _topics_delete(update, context, rest)
    else:
        await update.effective_message.reply_text(
            f"❓ Unknown subcommand: <code>{subcommand}</code>\n\n{_USAGE}",
            parse_mode="HTML",
        )


async def _topics_add(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
) -> None:
    """Handle /topics add <slug> <name> <path> [git_url]."""
    if len(args) < 3:
        await update.effective_message.reply_text(
            f"❌ <b>Missing arguments.</b>\n\n{_USAGE}", parse_mode="HTML"
        )
        return

    slug = args[0]
    name = args[1]
    path_str = args[2]
    git_url: Optional[str] = args[3] if len(args) > 3 else None

    # Must be sent from inside a forum topic
    thread_id: Optional[int] = update.effective_message.message_thread_id
    if thread_id is None:
        await update.effective_message.reply_text(
            "❌ <b>Must be sent from inside a forum topic.</b>\n"
            "Run <code>/topics add</code> from the topic you want to register.",
            parse_mode="HTML",
        )
        return

    chat_id = update.effective_chat.id
    settings: Settings = context.bot_data["settings"]
    approved_dir = settings.approved_directory.resolve()

    # Resolve absolute path — treat path_str as either absolute or relative to approved_dir
    raw_path = Path(path_str)
    abs_path = (raw_path if raw_path.is_absolute() else approved_dir / raw_path).resolve()

    try:
        abs_path.relative_to(approved_dir)
    except ValueError:
        await update.effective_message.reply_text(
            f"❌ <b>Invalid path.</b>\n"
            f"<code>{path_str}</code> is outside the approved directory.",
            parse_mode="HTML",
        )
        return

    # If no git_url, path must already exist as a directory
    if git_url is None:
        if not abs_path.exists() or not abs_path.is_dir():
            await update.effective_message.reply_text(
                f"❌ <b>Path does not exist or is not a directory.</b>\n"
                f"<code>{abs_path}</code>\n\n"
                "Provide a <code>git_url</code> to clone the repository first.",
                parse_mode="HTML",
            )
            return
    else:
        # Clone the repository into abs_path
        from ..features.registry import FeatureRegistry

        features: FeatureRegistry = context.bot_data["features"]
        git: Optional[GitIntegration] = features.get_git_integration()
        if git is None:
            await update.effective_message.reply_text(
                "❌ <b>Git integration is not available.</b>\n"
                "Enable it with <code>ENABLE_GIT_INTEGRATION=true</code>.",
                parse_mode="HTML",
            )
            return
        try:
            await git.clone_repo(git_url, abs_path)
        except GitError as exc:
            await update.effective_message.reply_text(
                f"❌ <b>Git clone failed.</b>\n<pre>{exc}</pre>\n"
                "No project was registered.",
                parse_mode="HTML",
            )
            return

    # Persist project record
    project_repo: ProjectRepository = context.bot_data["storage"].projects
    await project_repo.upsert(
        project_slug=slug,
        chat_id=chat_id,
        name=name,
        absolute_path=str(abs_path),
        git_url=git_url,
    )

    # Persist thread mapping
    thread_repo = context.bot_data["storage"].project_threads
    await thread_repo.upsert_mapping(
        project_slug=slug,
        chat_id=chat_id,
        message_thread_id=thread_id,
        topic_name=name,
    )

    # Reload in-memory registry
    manager = context.bot_data.get("project_threads_manager")
    if manager is not None:
        registry = await load_project_registry_from_db(
            repo=project_repo,
            approved_directory=settings.approved_directory,
            chat_id=chat_id,
        )
        manager.registry = registry
        logger.info("Registry reloaded after /topics add", slug=slug, chat_id=chat_id)

    await update.effective_message.reply_text(
        f"✅ <b>Project registered.</b>\n"
        f"<b>Slug:</b> <code>{slug}</code>\n"
        f"<b>Name:</b> {name}\n"
        f"<b>Path:</b> <code>{abs_path}</code>",
        parse_mode="HTML",
    )


async def _topics_list(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle /topics list — show all registered projects for this chat."""
    chat_id = update.effective_chat.id
    project_repo: ProjectRepository = context.bot_data["storage"].projects
    rows = await project_repo.list_by_chat(chat_id=chat_id, enabled_only=False)

    if not rows:
        await update.effective_message.reply_text(
            "ℹ️ No projects registered. Use /topics add to register one.",
            parse_mode="HTML",
        )
        return

    lines = []
    for row in rows:
        status = "enabled" if row.enabled else "disabled"
        lines.append(
            f"• <code>{row.project_slug}</code> — {row.name}\n"
            f"  Path: <code>{row.absolute_path}</code> [{status}]"
        )

    text = "\n\n".join(lines)
    await update.effective_message.reply_text(text, parse_mode="HTML")


async def _topics_delete(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
) -> None:
    """Handle /topics delete <slug>."""
    if not args:
        await update.effective_message.reply_text(
            f"❌ <b>Missing slug.</b>\n\n{_USAGE}", parse_mode="HTML"
        )
        return

    slug = args[0]
    chat_id = update.effective_chat.id
    settings: Settings = context.bot_data["settings"]
    project_repo: ProjectRepository = context.bot_data["storage"].projects

    rowcount = await project_repo.delete(project_slug=slug, chat_id=chat_id)
    if rowcount == 0:
        await update.effective_message.reply_text(
            f"❌ <b>Project not found:</b> <code>{slug}</code>",
            parse_mode="HTML",
        )
        return

    # Deactivate the thread mapping
    await context.bot_data["storage"].project_threads.set_active(
        chat_id=chat_id, project_slug=slug, is_active=False
    )

    # Reload in-memory registry
    manager = context.bot_data.get("project_threads_manager")
    if manager is not None:
        registry = await load_project_registry_from_db(
            repo=project_repo,
            approved_directory=settings.approved_directory,
            chat_id=chat_id,
        )
        manager.registry = registry
        logger.info(
            "Registry reloaded after /topics delete", slug=slug, chat_id=chat_id
        )

    await update.effective_message.reply_text(
        f"✅ Project <code>{slug}</code> removed.",
        parse_mode="HTML",
    )

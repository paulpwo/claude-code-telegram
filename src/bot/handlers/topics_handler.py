"""Handler for /topics command — add | list | delete subcommands.

Manages the dynamic project-thread registry. Projects registered here
are persisted in the `projects` table and served via
`load_project_registry_from_db` at startup (DB-only mode).

Usage:
  /topics add <slug> <name> <path> [git_url]
  /topics list
  /topics delete <slug>
"""

import shutil
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


_URL_PREFIXES = ("https://", "http://", "git@", "ssh://", "git://")


def _parse_add_args(
    args: List[str],
) -> Optional[tuple[str, str, str, Optional[str]]]:
    """Parse add subcommand args: slug [name...] path [git_url].

    Telegram does not preserve quoted strings — spaces in the name are handled
    by treating the last arg as git_url (if it looks like a URL), the
    second-to-last as path, and everything in between as the name.

    Returns (slug, name, path_str, git_url) or None if args are insufficient.
    """
    if len(args) < 3:
        return None

    slug = args[0]
    rest = args[1:]  # name parts + path [+ git_url]

    # Detect optional git_url at the end
    git_url: Optional[str] = None
    if rest[-1].startswith(_URL_PREFIXES):
        git_url = rest[-1]
        rest = rest[:-1]

    if len(rest) < 2:
        return None

    path_str = rest[-1]
    name = " ".join(rest[:-1])
    return slug, name, path_str, git_url


async def _topics_add(
    update: Update, context: ContextTypes.DEFAULT_TYPE, args: List[str]
) -> None:
    """Handle /topics add <slug> <name> <path> [git_url]."""
    parsed = _parse_add_args(args)
    if parsed is None:
        await update.effective_message.reply_text(
            f"❌ <b>Missing arguments.</b>\n\n{_USAGE}", parse_mode="HTML"
        )
        return

    slug, name, path_str, git_url = parsed

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

    # If no git_url: create directory if it doesn't exist
    if git_url is None:
        abs_path.mkdir(parents=True, exist_ok=True)
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

    # Fetch before delete to get the workspace path
    project = await project_repo.get_by_slug(project_slug=slug, chat_id=chat_id)

    rowcount = await project_repo.delete(project_slug=slug, chat_id=chat_id)
    if rowcount == 0:
        await update.effective_message.reply_text(
            f"❌ <b>Project not found:</b> <code>{slug}</code>",
            parse_mode="HTML",
        )
        return

    # Remove cloned workspace directory
    if project is not None:
        workspace_path = Path(project.absolute_path)
        if workspace_path.exists() and workspace_path.is_dir():
            shutil.rmtree(workspace_path, ignore_errors=True)
            logger.info("Workspace directory removed", path=str(workspace_path), slug=slug)

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

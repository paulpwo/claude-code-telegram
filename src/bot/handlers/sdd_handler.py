"""Handler for the /sdd command — SDD pre-analysis workflow.

Accepts a GitHub issue URL or a free-text description, builds a structured
prompt, delegates to Claude Code via ClaudeIntegration, and relays the result
back to the user as an HTML-formatted Telegram message.

Claude performs all git operations and file writes inside the working directory
(.agent/planning/sdd.md, .agent/context/files.md, .agent/context/approach.md).
The handler is intentionally thin — it only constructs the prompt and routes
the response.
"""

import re
from pathlib import Path
from typing import Optional, Tuple

import structlog
from telegram import Update
from telegram.ext import ContextTypes

from ...config.settings import Settings
from ...security.audit import AuditLogger

logger = structlog.get_logger()


# Regex patterns for parsing Claude's SDD response summary
_BRANCH_RE = re.compile(
    r"(?:branch[:\s]+|checkout[:\s]+-b\s+|created branch[:\s]+)"
    r"([A-Za-z][A-Za-z0-9/_-]+)",
    re.IGNORECASE,
)
_GITHUB_REPO_RE = re.compile(
    r"https?://github\.com/([^/]+)/([^/]+?)(?:\.git|/|$)",
    re.IGNORECASE,
)


def _parse_sdd_summary(
    response_text: str,
    issue_url: str,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """Extract (branch_name, owner, repo) from Claude's SDD summary response.

    Returns (None, None, None) if not found.
    """
    branch_match = _BRANCH_RE.search(response_text)
    branch_name = branch_match.group(1) if branch_match else None

    repo_match = _GITHUB_REPO_RE.search(issue_url) or _GITHUB_REPO_RE.search(response_text)
    if repo_match:
        owner = repo_match.group(1)
        repo = repo_match.group(2).rstrip("/")
    else:
        owner = repo = None

    return branch_name, owner, repo

# Regex for detecting GitHub issue URLs
_GITHUB_ISSUE_RE = re.compile(
    r"https?://github\.com/[^/]+/[^/]+/issues/(\d+)", re.IGNORECASE
)


def _is_github_issue_url(text: str) -> bool:
    """Return True when *text* looks like a GitHub issue URL."""
    return bool(_GITHUB_ISSUE_RE.search(text.strip()))


def _extract_issue_number(url: str) -> Optional[int]:
    """Return the issue number embedded in a GitHub issue URL, or None."""
    match = _GITHUB_ISSUE_RE.search(url.strip())
    if match:
        return int(match.group(1))
    return None


def _build_sdd_prompt(
    arg: str,
    working_dir: Path,
    protected_branches: list[str],
    is_url: bool,
) -> str:
    """Assemble the Claude prompt for an SDD pre-analysis run.

    Args:
        arg: The raw argument — either a GitHub issue URL or free-text.
        working_dir: The repo directory Claude should work in.
        protected_branches: List of branch names Claude must never push to.
        is_url: Whether *arg* is a GitHub issue URL (True) or free text (False).

    Returns:
        A fully formed prompt string ready to pass to ClaudeIntegration.run_command().
    """
    protected_str = ", ".join(protected_branches) if protected_branches else "main, master, develop"

    if is_url:
        issue_block = (
            f"GitHub issue URL: {arg}\n"
            "Fetch the issue content by running: gh issue view <url>"
        )
    else:
        issue_block = f"Issue / task description:\n{arg}"

    prompt = f"""You are running a SDD pre-analysis on the repo at {working_dir}.

Protected branches (NEVER push to these): {protected_str}

{issue_block}

Instructions:
1. If a GitHub URL was provided, run: gh issue view {arg if is_url else '<url>'} to fetch the issue title and body.
2. Infer branch type from the issue content:
   - Bug report → Fix
   - New feature → Feat
   - Refactoring → Refactor
   - Documentation → Docs
   - Everything else → Chore
3. Create a new branch following the naming convention:
   - For numbered issues: {{Tipo}}/Issue{{N}}{{DescripcionEnPascalCase}}  (e.g. Feat/Issue5AddDarkMode)
   - For free-text input: {{Tipo}}/{{DescripcionEnPascalCase}}            (e.g. Feat/AddDarkModeToSettingsPage)
   Run: git checkout -b <branch-name>
4. Explore the repo structure — focus on directories relevant to the issue.
5. Write .agent/planning/sdd.md — what to implement, acceptance criteria.
6. Write .agent/context/files.md — relevant files and their role.
7. Write .agent/context/approach.md — suggested approach, alternatives, tradeoffs.
8. Run: git add .agent/ && git commit -m "📝 docs(analysis): agregar pre-análisis {arg[:60] if not is_url else 'issue #' + str(_extract_issue_number(arg) or '?')}"
9. Run: git push origin <branch-name>
10. RESTRICTIONS:
    - DO NOT modify any existing source file outside .agent/
    - DO NOT open a Pull Request
    - DO NOT run tests or builds
    - DO NOT push to any protected branch ({protected_str})

End with a brief summary containing:
- Branch name created
- Files written under .agent/
- One-line problem statement
"""
    return prompt


async def sdd_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle the /sdd command — trigger an SDD pre-analysis workflow.

    Usage: /sdd <github-issue-url | description>

    The handler delegates the full analysis (branch creation, file writing,
    git commit/push) to Claude Code via ClaudeIntegration. It only constructs
    the prompt and relays the summary back to the user.
    """
    settings: Settings = context.bot_data["settings"]
    audit_logger: AuditLogger = context.bot_data.get("audit_logger")
    user_id = update.effective_user.id

    logger.info("SDD command received", user_id=user_id)

    # --- Feature flag check ---
    if not settings.enable_sdd:
        await update.message.reply_text("SDD command is disabled.")
        if audit_logger:
            await audit_logger.log_command(user_id, "sdd", [], False)
        return

    # --- Parse argument ---
    text = update.message.text or ""
    parts = text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip():
        await update.message.reply_text(
            "Usage: <code>/sdd &lt;github-issue-url | description&gt;</code>\n\n"
            "Examples:\n"
            "  <code>/sdd https://github.com/owner/repo/issues/5</code>\n"
            "  <code>/sdd Add dark mode to settings page</code>",
            parse_mode="HTML",
        )
        if audit_logger:
            await audit_logger.log_command(user_id, "sdd", [], False)
        return

    arg = parts[1].strip()
    is_url = _is_github_issue_url(arg)

    # --- Progress message ---
    progress_msg = await update.message.reply_text("🔍 Analyzing...")

    # --- Resolve working directory ---
    current_dir = context.user_data.get(
        "current_directory", settings.approved_directory
    )

    # --- Build prompt ---
    prompt = _build_sdd_prompt(
        arg=arg,
        working_dir=Path(current_dir),
        protected_branches=settings.sdd_protected_branches,
        is_url=is_url,
    )

    # --- Delegate to Claude ---
    claude_integration = context.bot_data.get("claude_integration")
    if not claude_integration:
        await progress_msg.edit_text(
            "❌ Claude integration not available. Check configuration."
        )
        logger.error("SDD command: claude_integration not in bot_data", user_id=user_id)
        return

    session_id = context.user_data.get("claude_session_id")

    try:
        claude_response = await claude_integration.run_command(
            prompt=prompt,
            working_directory=current_dir,
            user_id=user_id,
            session_id=session_id,
        )

        # Update session ID if a new session was created
        if claude_response and claude_response.session_id:
            context.user_data["claude_session_id"] = claude_response.session_id

        response_text = (
            claude_response.content
            if claude_response and claude_response.content
            else ""
        )

        if not response_text:
            await progress_msg.edit_text(
                "⚠️ SDD analysis completed but Claude returned an empty response."
            )
            logger.warning("SDD command: empty Claude response", user_id=user_id)
            if audit_logger:
                await audit_logger.log_command(user_id, "sdd", [arg], False)
            return

        # Telegram message limit is 4096 chars — truncate gracefully
        MAX_LEN = 4000
        if len(response_text) > MAX_LEN:
            response_text = response_text[:MAX_LEN] + "\n\n… <i>(truncated)</i>"

        await progress_msg.edit_text(
            f"✅ <b>SDD Analysis Complete</b>\n\n{response_text}",
            parse_mode="HTML",
        )

        if audit_logger:
            await audit_logger.log_command(user_id, "sdd", [arg], True)

        logger.info("SDD command completed successfully", user_id=user_id)

        # --- Auto-PR: attempt to open a PR if the user has a GitHub PAT stored ---
        await _try_auto_pr(
            update=update,
            context=context,
            user_id=user_id,
            response_text=response_text,
            issue_url=arg if is_url else "",
            issue_number=_extract_issue_number(arg) if is_url else None,
            arg=arg,
            settings=settings,
        )

    except Exception as exc:
        error_msg = str(exc)
        logger.error(
            "SDD command failed",
            user_id=user_id,
            error=error_msg,
        )
        await progress_msg.edit_text(
            f"❌ <b>SDD analysis failed</b>\n\n<code>{error_msg[:500]}</code>",
            parse_mode="HTML",
        )
        if audit_logger:
            await audit_logger.log_command(user_id, "sdd", [arg], False)


# ---------------------------------------------------------------------------
# Auto-PR helper (T-17)
# ---------------------------------------------------------------------------


async def _try_auto_pr(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    response_text: str,
    issue_url: str,
    issue_number: Optional[int],
    arg: str,
    settings: Settings,
) -> None:
    """Try to create a GitHub PR after SDD branch push.

    Silently skips if no PAT is configured or if branch/repo info cannot be
    parsed from Claude's response. Sends a tip message prompting the user to
    configure a PAT when one is not set.
    """
    from cryptography.fernet import Fernet, InvalidToken

    from ...bot.features.git_integration import GitIntegration
    from ...storage.repositories import GitTokenRepository

    storage = context.bot_data.get("storage")
    db_manager = storage.db_manager if storage else None
    encryption_key = settings.git_token_encryption_key

    if not db_manager:
        return

    git_token_repo = GitTokenRepository(db_manager)
    encrypted = await git_token_repo.get(user_id)

    if not encrypted:
        # Nudge user to set a PAT for future auto-PR
        await update.effective_message.reply_text(
            "💡 Configurá un token de GitHub con <code>/git set &lt;token&gt;</code> "
            "para habilitar la creación automática de PRs.",
            parse_mode="HTML",
        )
        return

    if not encryption_key:
        logger.warning("SDD auto-PR: GIT_TOKEN_ENCRYPTION_KEY not set", user_id=user_id)
        return

    try:
        fernet = Fernet(encryption_key.get_secret_value().encode())
        pat = fernet.decrypt(encrypted).decode()
    except (InvalidToken, Exception) as e:
        logger.error("SDD auto-PR: could not decrypt PAT", error=str(e), user_id=user_id)
        return

    # Parse branch and repo from Claude's response
    branch_name, owner, repo = _parse_sdd_summary(response_text, issue_url)

    if not branch_name or not owner or not repo:
        logger.info(
            "SDD auto-PR: could not extract branch/repo from response, skipping PR",
            user_id=user_id,
        )
        return

    # Determine default branch (fall back to "main")
    base_branch = "main"
    for protected in settings.sdd_protected_branches:
        if protected in ("main", "master", "develop"):
            base_branch = protected
            break

    issue_title = arg if not _is_github_issue_url(arg) else f"Issue #{issue_number}"

    try:
        git_integration = GitIntegration(settings)
        pr_url = await git_integration.create_pr(
            owner=owner,
            repo=repo,
            head_branch=branch_name,
            base_branch=base_branch,
            issue_number=issue_number or 0,
            issue_title=issue_title,
            pat=pat,
        )
        await update.effective_message.reply_text(
            f"✅ <b>PR creado:</b> {pr_url}",
            parse_mode="HTML",
        )
        logger.info(
            "SDD auto-PR created",
            pr_url=pr_url,
            branch=branch_name,
            user_id=user_id,
        )
    except Exception as e:
        await update.effective_message.reply_text(
            f"⚠️ Rama pusheada pero la creación del PR falló: <code>{str(e)[:200]}</code>",
            parse_mode="HTML",
        )
        logger.error("SDD auto-PR failed", error=str(e), user_id=user_id)

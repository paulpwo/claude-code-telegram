"""GitHub issues webhook handler — automatic SDD trigger.

When GitHub sends an ``issues`` webhook event with ``action: opened`` or
``action: labeled``, this module filters the payload against the configured
allow-list and label requirements, then publishes a :class:`ScheduledEvent`
that carries an SDD prompt into the event bus.

The existing AgentHandler + NotificationService pipeline picks the event up
and delivers the Claude response to the configured Telegram chat IDs — no new
infrastructure needed.

Design decisions
----------------
- Filtering logic lives here (not in ``server.py``) so it can be unit-tested
  without starting an HTTP server.
- This module is *intentionally* not async — all filtering is pure logic.
  The async helper at the bottom is what the server calls.
- We reuse :func:`src.bot.handlers.sdd_handler._build_sdd_prompt` for the
  prompt text so the behaviour is identical to ``/sdd <url>``.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

import structlog

if TYPE_CHECKING:
    from ..storage.database import DatabaseManager

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Payload helpers
# ---------------------------------------------------------------------------


def _get_issue_labels(payload: Dict[str, Any]) -> List[str]:
    """Return the list of label names on the issue in the payload.

    GitHub sends labels as a list of objects under ``payload["issue"]["labels"]``.
    Each object has at least a ``"name"`` key.
    """
    issue = payload.get("issue") or {}
    raw_labels = issue.get("labels") or []
    return [lbl.get("name", "") for lbl in raw_labels if isinstance(lbl, dict)]


def _get_labeled_label(payload: Dict[str, Any]) -> Optional[str]:
    """Return the name of the label that was just added in a ``labeled`` event.

    For ``action: labeled`` GitHub puts the single newly-added label object
    under ``payload["label"]``.  Returns None if the key is missing.
    """
    label_obj = payload.get("label")
    if isinstance(label_obj, dict):
        return label_obj.get("name")
    return None


def _get_repo_full_name(payload: Dict[str, Any]) -> Optional[str]:
    """Return ``owner/repo`` from the payload, or None if not present."""
    repo = payload.get("repository") or {}
    return repo.get("full_name")


def _get_issue_url(payload: Dict[str, Any]) -> Optional[str]:
    """Return the HTML URL of the issue, or None."""
    issue = payload.get("issue") or {}
    return issue.get("html_url")


def _get_issue_number(payload: Dict[str, Any]) -> Optional[int]:
    """Return the issue number as an int, or None."""
    issue = payload.get("issue") or {}
    num = issue.get("number")
    return int(num) if num is not None else None


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------


class IssueWebhookFilter:
    """Encapsulates all filtering rules for GitHub issue events.

    Instantiate once at startup (or per-request) with the settings values.

    Parameters
    ----------
    enabled:
        Master switch.  When False, :meth:`should_trigger` always returns
        ``(False, reason)``.
    require_label:
        When True, the issue must carry ``target_label``.
    target_label:
        The GitHub label name that activates analysis.
    repo_allowlist:
        ``owner/repo`` strings that are allowed.  An empty list means *all*
        repos are allowed.
    """

    def __init__(
        self,
        enabled: bool,
        require_label: bool,
        target_label: str,
        repo_allowlist: List[str],
    ) -> None:
        self.enabled = enabled
        self.require_label = require_label
        self.target_label = target_label
        # Normalise to lower-case for case-insensitive comparison
        self.repo_allowlist = [r.lower() for r in repo_allowlist]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def should_trigger(
        self,
        event_type: str,
        payload: Dict[str, Any],
    ) -> tuple[bool, str]:
        """Decide whether to trigger SDD analysis for this webhook event.

        Returns a ``(should_trigger: bool, reason: str)`` tuple.  The reason
        is useful for structured logging.
        """
        if not self.enabled:
            return False, "issue_webhook disabled"

        if event_type != "issues":
            return False, f"event_type={event_type!r} is not 'issues'"

        action = payload.get("action", "")
        if action not in ("opened", "labeled"):
            return False, f"action={action!r} not in ('opened', 'labeled')"

        # Repo allowlist check
        repo = _get_repo_full_name(payload)
        if self.repo_allowlist:
            if not repo or repo.lower() not in self.repo_allowlist:
                return False, f"repo={repo!r} not in allowlist"

        # Label check
        if self.require_label:
            ok, reason = self._check_label(action, payload)
            if not ok:
                return False, reason

        return True, "ok"

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _check_label(
        self, action: str, payload: Dict[str, Any]
    ) -> tuple[bool, str]:
        """Verify that the required label is present.

        - For ``opened``: the label must already be on the issue.
        - For ``labeled``: the label that was just added must be the target.
        """
        if action == "labeled":
            added_label = _get_labeled_label(payload)
            if added_label != self.target_label:
                return (
                    False,
                    f"labeled action but added label={added_label!r} != {self.target_label!r}",
                )
            return True, "label match (labeled action)"

        # action == "opened"
        labels = _get_issue_labels(payload)
        if self.target_label not in labels:
            return (
                False,
                f"opened action but label {self.target_label!r} not on issue",
            )
        return True, "label match (opened action)"


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------


def build_issue_sdd_prompt(
    payload: Dict[str, Any],
    working_directory: Path,
    protected_branches: List[str],
) -> str:
    """Build the SDD prompt for an auto-triggered issue analysis.

    Delegates to :func:`src.bot.handlers.sdd_handler._build_sdd_prompt` so the
    prompt is identical to what ``/sdd <url>`` would produce.

    Falls back to a minimal inline prompt if the issue URL cannot be extracted
    (e.g. malformed payload).
    """
    from ..bot.handlers.sdd_handler import _build_sdd_prompt

    issue_url = _get_issue_url(payload)
    if issue_url:
        return _build_sdd_prompt(
            arg=issue_url,
            working_dir=working_directory,
            protected_branches=protected_branches,
            is_url=True,
        )

    # Fallback — describe the event inline
    issue_number = _get_issue_number(payload)
    repo = _get_repo_full_name(payload) or "unknown/repo"
    issue = payload.get("issue") or {}
    title = issue.get("title", "(no title)")
    body = issue.get("body", "(no body)") or "(no body)"

    fallback_description = (
        f"GitHub issue #{issue_number} in {repo}\nTitle: {title}\n\n{body[:500]}"
    )
    return _build_sdd_prompt(
        arg=fallback_description,
        working_dir=working_directory,
        protected_branches=protected_branches,
        is_url=False,
    )


# ---------------------------------------------------------------------------
# Notification text
# ---------------------------------------------------------------------------


def build_trigger_notification(payload: Dict[str, Any]) -> str:
    """Return a short Telegram HTML notification sent *before* Claude runs.

    This tells the user that an automatic analysis has started so they know
    it didn't come out of nowhere.
    """
    issue = payload.get("issue") or {}
    repo = _get_repo_full_name(payload) or "unknown/repo"
    number = issue.get("number", "?")
    title = issue.get("title", "(no title)")
    url = issue.get("html_url", "")

    url_part = f'\n<a href="{url}">View issue</a>' if url else ""

    return (
        f"🔍 <b>SDD auto-analysis started</b>\n\n"
        f"GitHub issue <b>#{number}</b> in <code>{repo}</code> triggered an "
        f"automatic pre-analysis.\n\n"
        f"<b>{title}</b>{url_part}\n\n"
        f"Claude is analyzing the issue and will create a branch with the "
        f"pre-analysis documents. This may take a minute…"
    )


# ---------------------------------------------------------------------------
# Per-issue deduplication helper
# ---------------------------------------------------------------------------


async def try_record_issue_seen(
    db_manager: "DatabaseManager",
    repo_full_name: str,
    issue_number: int,
) -> bool:
    """Atomically insert a (repo, issue_number) row.

    Returns True if this is the first time we see this issue (inserted),
    False if it was already seen (duplicate — silent drop).
    """
    async with db_manager.get_connection() as conn:
        await conn.execute(
            """
            INSERT OR IGNORE INTO webhook_issue_seen (repo_full_name, issue_number)
            VALUES (?, ?)
            """,
            (repo_full_name, issue_number),
        )
        cursor = await conn.execute("SELECT changes()")
        row = await cursor.fetchone()
        inserted = (row[0] > 0) if row else False
        await conn.commit()
    return inserted

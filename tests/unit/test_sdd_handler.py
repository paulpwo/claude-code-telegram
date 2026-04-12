"""Unit tests for the /sdd command handler."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.handlers.sdd_handler import (
    _build_sdd_prompt,
    _extract_issue_number,
    _is_github_issue_url,
    sdd_command,
)
from src.config import create_test_config
from src.config.features import FeatureFlags

# ---------------------------------------------------------------------------
# Tests for _is_github_issue_url()
# ---------------------------------------------------------------------------


def test_is_github_issue_url_valid():
    """A standard GitHub issue URL is recognised correctly."""
    assert _is_github_issue_url("https://github.com/owner/repo/issues/5") is True


def test_is_github_issue_url_valid_with_trailing_text():
    """URL embedded in surrounding whitespace is still recognised."""
    assert _is_github_issue_url("  https://github.com/owner/repo/issues/42  ") is True


def test_is_github_issue_url_free_text():
    """Plain free-text descriptions are NOT treated as URLs."""
    assert _is_github_issue_url("Add dark mode to settings page") is False


def test_is_github_issue_url_malformed():
    """A URL that looks like GitHub but lacks the /issues/ path returns False."""
    assert _is_github_issue_url("https://github.com/owner/repo/pull/5") is False


def test_is_github_issue_url_http():
    """http:// scheme is also accepted."""
    assert _is_github_issue_url("http://github.com/owner/repo/issues/1") is True


def test_is_github_issue_url_non_github():
    """Non-GitHub URLs return False."""
    assert _is_github_issue_url("https://gitlab.com/owner/repo/issues/5") is False


# ---------------------------------------------------------------------------
# Tests for _extract_issue_number()
# ---------------------------------------------------------------------------


def test_extract_issue_number_returns_int():
    """Issue number is extracted as an integer from a valid URL."""
    result = _extract_issue_number("https://github.com/owner/repo/issues/42")
    assert result == 42


def test_extract_issue_number_returns_none_for_free_text():
    """Returns None when the input is not a GitHub issue URL."""
    result = _extract_issue_number("Add dark mode")
    assert result is None


# ---------------------------------------------------------------------------
# Tests for _build_sdd_prompt()
# ---------------------------------------------------------------------------


def test_build_sdd_prompt_url_contains_gh_fetch_instruction():
    """When is_url=True the prompt includes the gh issue view instruction."""
    url = "https://github.com/owner/repo/issues/5"
    prompt = _build_sdd_prompt(
        arg=url,
        working_dir=Path("/some/repo"),
        protected_branches=["main", "master"],
        is_url=True,
    )
    assert "gh issue view" in prompt
    assert url in prompt


def test_build_sdd_prompt_url_contains_protected_branches():
    """Protected branches are injected into the URL-mode prompt."""
    prompt = _build_sdd_prompt(
        arg="https://github.com/owner/repo/issues/1",
        working_dir=Path("/repo"),
        protected_branches=["main", "master", "develop"],
        is_url=True,
    )
    assert "main" in prompt
    assert "master" in prompt
    assert "develop" in prompt


def test_build_sdd_prompt_free_text_no_gh_fetch():
    """When is_url=False the prompt does NOT contain a gh issue view fetch call."""
    prompt = _build_sdd_prompt(
        arg="Add dark mode to settings page",
        working_dir=Path("/repo"),
        protected_branches=["main"],
        is_url=False,
    )
    # The fetch instruction references the URL directly — should be absent for free text
    assert "gh issue view https://" not in prompt
    assert "Add dark mode to settings page" in prompt


def test_build_sdd_prompt_free_text_description_in_prompt():
    """Free-text description is passed verbatim into the prompt."""
    description = "Improve pagination in the users list"
    prompt = _build_sdd_prompt(
        arg=description,
        working_dir=Path("/repo"),
        protected_branches=[],
        is_url=False,
    )
    assert description in prompt


def test_build_sdd_prompt_working_dir_in_prompt():
    """Working directory path appears in the prompt."""
    prompt = _build_sdd_prompt(
        arg="Fix login bug",
        working_dir=Path("/home/user/myproject"),
        protected_branches=["main"],
        is_url=False,
    )
    assert "/home/user/myproject" in prompt


def test_build_sdd_prompt_contains_agent_file_instructions():
    """Prompt instructs Claude to write all three .agent/<Type>/<BranchSlug>/ files."""
    prompt = _build_sdd_prompt(
        arg="Some task",
        working_dir=Path("/repo"),
        protected_branches=["main"],
        is_url=False,
    )
    assert ".agent/<Type>/<BranchSlug>/planning.md" in prompt
    assert ".agent/<Type>/<BranchSlug>/files.md" in prompt
    assert ".agent/<Type>/<BranchSlug>/approach.md" in prompt


def test_build_sdd_prompt_restrictions_present():
    """Prompt must explicitly forbid modifying source files, opening PRs, running tests."""
    prompt = _build_sdd_prompt(
        arg="Some task",
        working_dir=Path("/repo"),
        protected_branches=["main"],
        is_url=False,
    )
    assert "DO NOT modify any existing source file" in prompt
    assert "DO NOT open a Pull Request" in prompt
    assert "DO NOT run tests" in prompt


# ---------------------------------------------------------------------------
# Tests for sdd_command() handler — feature flag disabled
# ---------------------------------------------------------------------------


def _make_update(text: str) -> MagicMock:
    """Build a minimal Telegram Update mock."""
    update = MagicMock()
    update.effective_user.id = 99
    update.message.text = text
    update.message.reply_text = AsyncMock(return_value=MagicMock(edit_text=AsyncMock()))
    return update


def _make_context(settings, claude_integration=None, user_data=None) -> MagicMock:
    """Build a minimal PTB context mock."""
    context = MagicMock()
    context.bot_data = {
        "settings": settings,
        "claude_integration": claude_integration,
        "audit_logger": None,
    }
    context.user_data = user_data or {}
    return context


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def settings_sdd_enabled(tmp_dir):
    return create_test_config(
        approved_directory=str(tmp_dir),
        agentic_mode=True,
        enable_sdd=True,
    )


@pytest.fixture
def settings_sdd_disabled(tmp_dir):
    return create_test_config(
        approved_directory=str(tmp_dir),
        agentic_mode=True,
        enable_sdd=False,
    )


async def test_sdd_command_disabled_replies_and_does_not_call_claude(
    settings_sdd_disabled,
):
    """When enable_sdd=False the handler replies disabled message without calling Claude."""
    claude_integration = AsyncMock()
    update = _make_update("/sdd https://github.com/owner/repo/issues/1")
    context = _make_context(settings_sdd_disabled, claude_integration)

    await sdd_command(update, context)

    update.message.reply_text.assert_called_once_with("SDD command is disabled.")
    claude_integration.run_command.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for sdd_command() — no argument
# ---------------------------------------------------------------------------


async def test_sdd_command_no_arg_replies_usage_and_does_not_call_claude(
    settings_sdd_enabled,
):
    """When /sdd is sent with no argument the handler replies with usage help."""
    claude_integration = AsyncMock()
    update = _make_update("/sdd")
    context = _make_context(settings_sdd_enabled, claude_integration)

    await sdd_command(update, context)

    call_args = update.message.reply_text.call_args
    reply_text = call_args[0][0]
    assert (
        "Usage" in reply_text or "usage" in reply_text.lower() or "/sdd" in reply_text
    )
    claude_integration.run_command.assert_not_called()


# ---------------------------------------------------------------------------
# Tests for sdd_command() — happy path
# ---------------------------------------------------------------------------


async def test_sdd_command_happy_path_calls_run_command_and_edits_message(
    settings_sdd_enabled,
):
    """Happy path: run_command is called and the progress message is edited with the result."""
    fake_response = MagicMock()
    fake_response.content = "Branch Feat/Issue5AddDarkMode created. Files written."
    fake_response.session_id = "sess-abc"

    claude_integration = MagicMock()
    claude_integration.run_command = AsyncMock(return_value=fake_response)

    progress_msg = MagicMock()
    progress_msg.edit_text = AsyncMock()

    update = _make_update("/sdd https://github.com/owner/repo/issues/5")
    update.message.reply_text = AsyncMock(return_value=progress_msg)

    context = _make_context(settings_sdd_enabled, claude_integration)

    await sdd_command(update, context)

    claude_integration.run_command.assert_called_once()
    # The prompt passed must contain the issue URL
    call_kwargs = claude_integration.run_command.call_args
    prompt_used = call_kwargs[1].get("prompt") or call_kwargs[0][0]
    assert "github.com" in prompt_used

    # Progress message must be edited with the response content
    progress_msg.edit_text.assert_called_once()
    edit_text_arg = progress_msg.edit_text.call_args[0][0]
    assert "Feat/Issue5AddDarkMode" in edit_text_arg or "Branch" in edit_text_arg


async def test_sdd_command_session_id_stored_after_success(settings_sdd_enabled):
    """A new session_id returned by Claude is stored in user_data."""
    fake_response = MagicMock()
    fake_response.content = "Done."
    fake_response.session_id = "new-session-xyz"

    claude_integration = MagicMock()
    claude_integration.run_command = AsyncMock(return_value=fake_response)

    progress_msg = MagicMock()
    progress_msg.edit_text = AsyncMock()

    update = _make_update("/sdd Add some feature")
    update.message.reply_text = AsyncMock(return_value=progress_msg)

    context = _make_context(settings_sdd_enabled, claude_integration)

    await sdd_command(update, context)

    assert context.user_data.get("claude_session_id") == "new-session-xyz"


# ---------------------------------------------------------------------------
# Tests for FeatureFlags.sdd_enabled
# ---------------------------------------------------------------------------


def test_feature_flags_sdd_enabled_true(tmp_dir):
    """sdd_enabled returns True when enable_sdd=True in settings."""
    settings = create_test_config(
        approved_directory=str(tmp_dir),
        enable_sdd=True,
    )
    flags = FeatureFlags(settings)
    assert flags.sdd_enabled is True


def test_feature_flags_sdd_enabled_false(tmp_dir):
    """sdd_enabled returns False when enable_sdd=False in settings."""
    settings = create_test_config(
        approved_directory=str(tmp_dir),
        enable_sdd=False,
    )
    flags = FeatureFlags(settings)
    assert flags.sdd_enabled is False


def test_feature_flags_is_feature_enabled_sdd(tmp_dir):
    """is_feature_enabled('sdd') reflects the sdd_enabled property."""
    settings_on = create_test_config(approved_directory=str(tmp_dir), enable_sdd=True)
    settings_off = create_test_config(approved_directory=str(tmp_dir), enable_sdd=False)

    assert FeatureFlags(settings_on).is_feature_enabled("sdd") is True
    assert FeatureFlags(settings_off).is_feature_enabled("sdd") is False

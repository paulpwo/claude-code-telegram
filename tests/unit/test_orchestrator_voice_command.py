"""Tests for /voice command handling (tool-based voice design)."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.bot.orchestrator import MessageOrchestrator
from src.config.settings import Settings

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_settings(tmp_dir: Path, **overrides) -> Settings:
    """Build Settings directly, bypassing .env file to avoid test-env issues."""
    defaults = dict(
        telegram_bot_token="test_token_123",
        telegram_bot_username="test_bot",
        approved_directory=str(tmp_dir),
        agentic_mode=True,
        enable_voice_replies=True,
        edge_tts_voice="es-AR-TomasNeural",
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def voice_settings(tmp_dir):
    """Settings with voice replies enabled."""
    return _make_settings(tmp_dir)


@pytest.fixture
def no_voice_settings(tmp_dir):
    """Settings with voice replies disabled."""
    return _make_settings(tmp_dir, enable_voice_replies=False)


@pytest.fixture
def deps():
    return {
        "claude_integration": MagicMock(),
        "storage": MagicMock(),
        "security_validator": MagicMock(),
        "rate_limiter": MagicMock(),
        "audit_logger": MagicMock(),
        "features": MagicMock(),
    }


def _make_context(user_data: dict | None = None, bot_data: dict | None = None):
    """Build a minimal mock context."""
    ctx = MagicMock()
    ctx.user_data = user_data if user_data is not None else {}
    ctx.bot_data = bot_data if bot_data is not None else {}
    return ctx


def _make_update(text: str) -> MagicMock:
    """Build a minimal mock Update with message.text."""
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.reply_text = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = 12345
    return update


# ---------------------------------------------------------------------------
# /voice on — sets user_data (4.7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_on_sets_state(voice_settings, deps):
    """/voice on sets user_data['voice_reply'] = 'on' and sends confirmation."""
    orchestrator = MessageOrchestrator(settings=voice_settings, deps=deps)
    context = _make_context()
    update = _make_update("/voice on")

    await orchestrator.agentic_voice_command(update, context)

    assert context.user_data.get("voice_reply") == "on"
    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "enabled" in reply_text.lower() or "voice" in reply_text.lower()


# ---------------------------------------------------------------------------
# /voice off — state transition (4.8)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_off_sets_state(voice_settings, deps):
    """/voice off sets user_data['voice_reply'] = 'off'."""
    orchestrator = MessageOrchestrator(settings=voice_settings, deps=deps)
    context = _make_context(user_data={"voice_reply": "on"})
    update = _make_update("/voice off")

    await orchestrator.agentic_voice_command(update, context)

    assert context.user_data.get("voice_reply") == "off"


@pytest.mark.asyncio
async def test_voice_auto_is_alias_for_on(voice_settings, deps):
    """/voice auto is accepted as an alias for 'on'."""
    orchestrator = MessageOrchestrator(settings=voice_settings, deps=deps)
    context = _make_context()
    update = _make_update("/voice auto")

    await orchestrator.agentic_voice_command(update, context)

    # auto is normalized to "on" in the new design
    assert context.user_data.get("voice_reply") == "on"


# ---------------------------------------------------------------------------
# /voice (no args) — returns current status (4.9)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_no_args_shows_status(voice_settings, deps):
    """/voice with no args replies with current status without changing state."""
    orchestrator = MessageOrchestrator(settings=voice_settings, deps=deps)
    context = _make_context(user_data={"voice_reply": "on"})
    update = _make_update("/voice")

    await orchestrator.agentic_voice_command(update, context)

    # State unchanged
    assert context.user_data.get("voice_reply") == "on"
    update.message.reply_text.assert_awaited_once()


# ---------------------------------------------------------------------------
# /voice xyz — invalid arg, state unchanged (4.9 edge)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_invalid_arg_does_not_change_state(voice_settings, deps):
    """/voice xyz replies with usage info and does not change state."""
    orchestrator = MessageOrchestrator(settings=voice_settings, deps=deps)
    context = _make_context(user_data={"voice_reply": "off"})
    update = _make_update("/voice xyz")

    await orchestrator.agentic_voice_command(update, context)

    assert context.user_data.get("voice_reply") == "off"


# ---------------------------------------------------------------------------
# /voice disabled — feature flag check (4.7 edge)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_feature_disabled_informs_user(no_voice_settings, deps):
    """/voice when feature is disabled informs the user."""
    orchestrator = MessageOrchestrator(settings=no_voice_settings, deps=deps)
    context = _make_context()
    update = _make_update("/voice on")

    await orchestrator.agentic_voice_command(update, context)

    # State must NOT be set
    assert "voice_reply" not in context.user_data
    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args[0][0]
    assert "disabled" in reply_text.lower()


# ---------------------------------------------------------------------------
# agentic_new — resets voice_reply (4.11)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agentic_new_clears_voice_reply(voice_settings, deps):
    """/new clears voice_reply from user_data."""
    orchestrator = MessageOrchestrator(settings=voice_settings, deps=deps)
    context = _make_context(user_data={"voice_reply": "on"})
    update = _make_update("/new")

    await orchestrator.agentic_new(update, context)

    assert "voice_reply" not in context.user_data

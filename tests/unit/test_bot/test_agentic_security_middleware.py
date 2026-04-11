"""Tests for agentic mode behavior in security_middleware.

Verifies that:
- In agentic mode, dangerous patterns are logged but NOT blocked.
- In classic mode, dangerous patterns ARE blocked (existing behavior).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.middleware.security import security_middleware


def _make_event(text: str) -> MagicMock:
    """Build a minimal mock Telegram Update with a text message."""
    message = MagicMock()
    message.text = text
    message.document = None
    message.reply_text = AsyncMock()

    event = MagicMock()
    event.effective_user = MagicMock()
    event.effective_user.id = 1
    event.effective_user.username = "testuser"
    event.effective_message = message
    return event


def _make_data(agentic_mode: bool) -> dict:
    """Build the data dict passed into middleware."""
    settings = MagicMock()
    settings.agentic_mode = agentic_mode

    security_validator = MagicMock()
    # sanitize_command_input returns input unchanged (no excessive sanitization)
    security_validator.sanitize_command_input.side_effect = lambda text: text

    audit_logger = MagicMock()
    audit_logger.log_security_violation = AsyncMock()

    return {
        "settings": settings,
        "security_validator": security_validator,
        "audit_logger": audit_logger,
    }


@pytest.mark.asyncio
async def test_agentic_mode_dangerous_pattern_not_blocked() -> None:
    """eval( pattern must NOT block the handler in agentic mode."""
    event = _make_event("can you explain why eval( is dangerous?")
    data = _make_data(agentic_mode=True)
    handler = AsyncMock(return_value="ok")

    result = await security_middleware(handler, event, data)

    # Handler must be called (not blocked)
    handler.assert_awaited_once()
    assert result == "ok"
    # reply_text must NOT be called
    event.effective_message.reply_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_agentic_mode_audit_logger_called_for_pattern() -> None:
    """audit_logger.log_security_violation must be called in agentic mode."""
    event = _make_event("eval( this code")
    data = _make_data(agentic_mode=True)
    handler = AsyncMock(return_value="ok")

    await security_middleware(handler, event, data)

    data["audit_logger"].log_security_violation.assert_awaited()


@pytest.mark.asyncio
async def test_classic_mode_dangerous_pattern_blocked() -> None:
    """eval( pattern MUST block the handler in classic mode."""
    event = _make_event("eval( this code")
    data = _make_data(agentic_mode=False)
    handler = AsyncMock(return_value="ok")

    result = await security_middleware(handler, event, data)

    # Handler must NOT be called (blocked)
    handler.assert_not_awaited()
    # reply_text must be called with a security alert
    event.effective_message.reply_text.assert_awaited_once()
    # result is None because middleware returned early
    assert result is None


@pytest.mark.asyncio
async def test_agentic_mode_clean_message_passes_silently() -> None:
    """A clean message in agentic mode must reach the handler without audit logging."""
    event = _make_event("Hello, world! What is the capital of France?")
    data = _make_data(agentic_mode=True)
    handler = AsyncMock(return_value="reply")

    result = await security_middleware(handler, event, data)

    handler.assert_awaited_once()
    assert result == "reply"
    data["audit_logger"].log_security_violation.assert_not_awaited()


@pytest.mark.asyncio
async def test_classic_mode_clean_message_passes() -> None:
    """A clean message in classic mode must also reach the handler."""
    event = _make_event("What time is it?")
    data = _make_data(agentic_mode=False)
    handler = AsyncMock(return_value="reply")

    result = await security_middleware(handler, event, data)

    handler.assert_awaited_once()
    assert result == "reply"
    event.effective_message.reply_text.assert_not_awaited()

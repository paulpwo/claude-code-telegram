"""Unit tests for ``src.bot.session_scope``.

These tests cover the scope-key helper in isolation — no real Telegram
objects. ``MagicMock`` stands in for ``telegram.Update`` and its nested
attributes.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.bot.session_scope import (
    is_dm,
    scope_key,
    user_data_session_key,
)


def _make_update(
    *,
    user_id: int,
    chat_id: int,
    message_thread_id: int | None = None,
    has_message: bool = True,
) -> MagicMock:
    """Build a fake ``telegram.Update`` with just the fields the helper reads."""
    update = MagicMock()
    update.effective_user.id = user_id
    update.effective_chat.id = chat_id
    if has_message:
        update.effective_message.message_thread_id = message_thread_id
    else:
        update.effective_message = None
    return update


class TestScopeKeyDM:
    """DM updates must produce ``(user_id, user_id, 0)``."""

    def test_dm_triple_shape(self) -> None:
        update = _make_update(user_id=42, chat_id=42, message_thread_id=None)

        assert scope_key(update) == (42, 42, 0)

    def test_dm_is_detected(self) -> None:
        update = _make_update(user_id=42, chat_id=42, message_thread_id=None)

        assert is_dm(update) is True

    def test_dm_user_data_key(self) -> None:
        update = _make_update(user_id=42, chat_id=42, message_thread_id=None)

        assert user_data_session_key(update) == "claude_session_id:42:0"


class TestScopeKeyForumTopic:
    """Forum topics populate ``message_thread_id`` and MUST flow through."""

    def test_forum_topic_triple_includes_thread(self) -> None:
        update = _make_update(
            user_id=42, chat_id=-1001234, message_thread_id=7
        )

        assert scope_key(update) == (42, -1001234, 7)

    def test_forum_topic_is_not_dm(self) -> None:
        update = _make_update(
            user_id=42, chat_id=-1001234, message_thread_id=7
        )

        assert is_dm(update) is False

    def test_forum_topic_user_data_key(self) -> None:
        update = _make_update(
            user_id=42, chat_id=-1001234, message_thread_id=7
        )

        assert (
            user_data_session_key(update)
            == "claude_session_id:-1001234:7"
        )


class TestScopeKeyPlainGroup:
    """Non-forum groups have no ``message_thread_id`` → default ``thread_id=0``."""

    def test_group_without_topic_thread_is_zero(self) -> None:
        update = _make_update(
            user_id=42, chat_id=-1009999, message_thread_id=None
        )

        assert scope_key(update) == (42, -1009999, 0)

    def test_group_is_not_dm(self) -> None:
        # chat_id differs from user_id — not a DM even with thread_id=0.
        update = _make_update(
            user_id=42, chat_id=-1009999, message_thread_id=None
        )

        assert is_dm(update) is False

    def test_group_user_data_key(self) -> None:
        update = _make_update(
            user_id=42, chat_id=-1009999, message_thread_id=None
        )

        assert (
            user_data_session_key(update)
            == "claude_session_id:-1009999:0"
        )


class TestScopeKeyMissingMessage:
    """If ``effective_message`` is ``None`` the helper still yields ``thread_id=0``."""

    def test_missing_message_falls_back_to_zero(self) -> None:
        update = _make_update(user_id=42, chat_id=42, has_message=False)

        assert scope_key(update) == (42, 42, 0)
        assert user_data_session_key(update) == "claude_session_id:42:0"


class TestScopeKeyStability:
    """Repeated calls on the same ``Update`` must return the same triple/key."""

    def test_scope_key_is_stable(self) -> None:
        update = _make_update(
            user_id=42, chat_id=-1001234, message_thread_id=7
        )

        first = scope_key(update)
        second = scope_key(update)
        third = scope_key(update)

        assert first == second == third == (42, -1001234, 7)

    def test_user_data_session_key_is_stable(self) -> None:
        update = _make_update(
            user_id=42, chat_id=-1001234, message_thread_id=7
        )

        first = user_data_session_key(update)
        second = user_data_session_key(update)

        assert first == second == "claude_session_id:-1001234:7"

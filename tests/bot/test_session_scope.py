"""Unit tests for ``src.bot.session_scope``.

These tests cover the scope-key helper in isolation — no real Telegram
objects. ``MagicMock`` stands in for ``telegram.Update`` and its nested
attributes.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.bot.session_scope import (
    DmWorkdirError,
    dm_workdir_for,
    ensure_dm_workdir,
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
        update = _make_update(user_id=42, chat_id=-1001234, message_thread_id=7)

        assert scope_key(update) == (42, -1001234, 7)

    def test_forum_topic_is_not_dm(self) -> None:
        update = _make_update(user_id=42, chat_id=-1001234, message_thread_id=7)

        assert is_dm(update) is False

    def test_forum_topic_user_data_key(self) -> None:
        update = _make_update(user_id=42, chat_id=-1001234, message_thread_id=7)

        assert user_data_session_key(update) == "claude_session_id:-1001234:7"


class TestScopeKeyPlainGroup:
    """Non-forum groups have no ``message_thread_id`` → default ``thread_id=0``."""

    def test_group_without_topic_thread_is_zero(self) -> None:
        update = _make_update(user_id=42, chat_id=-1009999, message_thread_id=None)

        assert scope_key(update) == (42, -1009999, 0)

    def test_group_is_not_dm(self) -> None:
        # chat_id differs from user_id — not a DM even with thread_id=0.
        update = _make_update(user_id=42, chat_id=-1009999, message_thread_id=None)

        assert is_dm(update) is False

    def test_group_user_data_key(self) -> None:
        update = _make_update(user_id=42, chat_id=-1009999, message_thread_id=None)

        assert user_data_session_key(update) == "claude_session_id:-1009999:0"


class TestScopeKeyMissingMessage:
    """If ``effective_message`` is ``None`` the helper still yields ``thread_id=0``."""

    def test_missing_message_falls_back_to_zero(self) -> None:
        update = _make_update(user_id=42, chat_id=42, has_message=False)

        assert scope_key(update) == (42, 42, 0)
        assert user_data_session_key(update) == "claude_session_id:42:0"


class TestScopeKeyStability:
    """Repeated calls on the same ``Update`` must return the same triple/key."""

    def test_scope_key_is_stable(self) -> None:
        update = _make_update(user_id=42, chat_id=-1001234, message_thread_id=7)

        first = scope_key(update)
        second = scope_key(update)
        third = scope_key(update)

        assert first == second == third == (42, -1001234, 7)

    def test_user_data_session_key_is_stable(self) -> None:
        update = _make_update(user_id=42, chat_id=-1001234, message_thread_id=7)

        first = user_data_session_key(update)
        second = user_data_session_key(update)

        assert first == second == "claude_session_id:-1001234:7"


class TestCrossScopeIsolation:
    """Same user across DM + forum topic MUST yield distinct session keys.

    This is the core of the bug this change fixes: user_data is keyed by
    user-only in python-telegram-bot, so a single user's DM and forum
    topic share the same dict. Without scope-keyed entries, starting a
    session in one scope leaks into the other.
    """

    def test_dm_and_forum_topic_produce_distinct_keys(self) -> None:
        user_id = 42
        dm = _make_update(user_id=user_id, chat_id=user_id, message_thread_id=None)
        topic = _make_update(user_id=user_id, chat_id=-1001234, message_thread_id=7)

        dm_key = user_data_session_key(dm)
        topic_key = user_data_session_key(topic)

        assert dm_key != topic_key
        assert dm_key == "claude_session_id:42:0"
        assert topic_key == "claude_session_id:-1001234:7"

    def test_two_topics_same_group_produce_distinct_keys(self) -> None:
        user_id = 42
        group_id = -1001234
        topic_a = _make_update(user_id=user_id, chat_id=group_id, message_thread_id=3)
        topic_b = _make_update(user_id=user_id, chat_id=group_id, message_thread_id=4)

        assert user_data_session_key(topic_a) != user_data_session_key(topic_b)

    def test_new_in_one_scope_does_not_affect_other(self) -> None:
        """Simulate `/new` in DM while a topic session exists for the same user.

        user_data is a single dict per user. Resetting only the DM's
        scoped key MUST leave the topic's key intact.
        """
        user_id = 42
        dm = _make_update(user_id=user_id, chat_id=user_id, message_thread_id=None)
        topic = _make_update(user_id=user_id, chat_id=-1001234, message_thread_id=7)

        user_data: dict[str, str | None] = {
            user_data_session_key(dm): "dm-session-abc",
            user_data_session_key(topic): "topic-session-xyz",
        }

        # Simulate /new running in the DM scope: wipe only the DM-scoped key.
        user_data[user_data_session_key(dm)] = None

        assert user_data[user_data_session_key(dm)] is None
        assert user_data[user_data_session_key(topic)] == "topic-session-xyz"


class TestRestartRecovery:
    """After a restart (fresh `user_data`), storage lookup by scope MUST win.

    Simulated with an in-memory dict standing in for the sessions table —
    no real sqlite, no real Telegram. The assertion is behavioural:
    ``load_by_scope(user_id, chat_id, thread_id)`` returns the row that
    matches the triple, NOT whatever was last written by any scope.
    """

    @staticmethod
    def _load_by_scope(
        rows: list[dict],
        *,
        user_id: int,
        chat_id: int | None,
        thread_id: int,
    ) -> str | None:
        """Tiny in-memory analogue of ``load_session_by_scope``.

        Matches the real storage query: triple match AND is_active.
        Legacy rows (``chat_id IS NULL``) are naturally excluded by the
        triple match on ``chat_id``.
        """
        for row in rows:
            if (
                row["user_id"] == user_id
                and row["chat_id"] == chat_id
                and row["thread_id"] == thread_id
                and row["is_active"]
            ):
                return row["session_id"]
        return None

    def test_restart_recovers_distinct_sessions_per_scope(self) -> None:
        user_id = 42
        group_id = -1001234
        topic_id = 7

        # Seed the "storage layer" with a DM row and a topic row.
        rows = [
            {
                "session_id": "dm-session-abc",
                "user_id": user_id,
                "chat_id": user_id,
                "thread_id": 0,
                "is_active": True,
            },
            {
                "session_id": "topic-session-xyz",
                "user_id": user_id,
                "chat_id": group_id,
                "thread_id": topic_id,
                "is_active": True,
            },
        ]

        # Restart: user_data is a fresh empty dict, no cached session ids.
        user_data: dict[str, str | None] = {}

        # Incoming DM update resumes the DM session from storage.
        dm = _make_update(user_id=user_id, chat_id=user_id, message_thread_id=None)
        u, c, t = scope_key(dm)
        user_data[user_data_session_key(dm)] = self._load_by_scope(
            rows, user_id=u, chat_id=c, thread_id=t
        )

        # Incoming topic update resumes the topic session from storage.
        topic = _make_update(
            user_id=user_id, chat_id=group_id, message_thread_id=topic_id
        )
        u, c, t = scope_key(topic)
        user_data[user_data_session_key(topic)] = self._load_by_scope(
            rows, user_id=u, chat_id=c, thread_id=t
        )

        assert user_data[user_data_session_key(dm)] == "dm-session-abc"
        assert user_data[user_data_session_key(topic)] == "topic-session-xyz"

    def test_legacy_rows_excluded_from_scope_lookup(self) -> None:
        """Pre-v8 rows have ``chat_id IS NULL`` → never returned by triple match."""
        user_id = 42

        # Legacy row: no chat_id. Migration v8 also flips is_active=False,
        # but the triple query is already self-protecting via the chat_id
        # equality constraint. Include both defences here.
        rows = [
            {
                "session_id": "legacy-pre-v8",
                "user_id": user_id,
                "chat_id": None,
                "thread_id": 0,
                "is_active": False,
            },
        ]

        dm = _make_update(user_id=user_id, chat_id=user_id, message_thread_id=None)
        u, c, t = scope_key(dm)

        assert self._load_by_scope(rows, user_id=u, chat_id=c, thread_id=t) is None


class TestEnsureDmWorkdir:
    """Lazy DM workdir provisioning."""

    def test_creates_workdir_for_dm(self) -> None:
        update = _make_update(user_id=42, chat_id=42, message_thread_id=None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = ensure_dm_workdir(update, root=root)

            assert path == dm_workdir_for(42, root=root)
            assert path.is_dir()

    def test_is_idempotent(self) -> None:
        update = _make_update(user_id=42, chat_id=42, message_thread_id=None)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = ensure_dm_workdir(update, root=root)
            second = ensure_dm_workdir(update, root=root)

            assert first == second

    def test_raises_on_non_dm_update(self) -> None:
        update = _make_update(user_id=42, chat_id=-1001234, message_thread_id=7)

        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(ValueError):
                ensure_dm_workdir(update, root=Path(tmp))

    def test_raises_dm_workdir_error_when_root_is_a_file(self) -> None:
        """If the parent ``root`` is unusable, surface a loud error."""
        update = _make_update(user_id=42, chat_id=42, message_thread_id=None)

        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / "not-a-dir"
            blocker.write_text("I am a file, not a directory")
            # Using the file as the root makes mkdir(parents=True) fail —
            # Path.mkdir raises FileExistsError (a subclass of OSError).
            with pytest.raises(DmWorkdirError):
                ensure_dm_workdir(update, root=blocker)

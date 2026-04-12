"""Tests for DatabaseAuthProvider (approved_users table + auto-approve)."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import aiosqlite
import pytest

from src.security.auth import DatabaseAuthProvider


class _StubDBManager:
    """Minimal db_manager stub that yields a shared aiosqlite connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @asynccontextmanager  # type: ignore[misc]
    async def get_connection(self):  # type: ignore[override]
        yield self._conn


@pytest.fixture
async def in_memory_db():
    """Create an in-memory SQLite DB with the approved_users table."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute(
        """
        CREATE TABLE approved_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            username TEXT,
            first_name TEXT,
            approved_by TEXT NOT NULL DEFAULT 'manual',
            approved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    await conn.commit()
    yield _StubDBManager(conn)
    await conn.close()


# ---------------------------------------------------------------------------
# is_approved / approve_user
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_is_approved_empty_db(in_memory_db: _StubDBManager) -> None:
    """Unknown user is not approved."""
    provider = DatabaseAuthProvider(db=in_memory_db)
    assert await provider.is_approved(999) is False


@pytest.mark.asyncio
async def test_approve_and_check(in_memory_db: _StubDBManager) -> None:
    """After approve_user, is_approved returns True."""
    provider = DatabaseAuthProvider(db=in_memory_db)
    await provider.approve_user(42, username="pablo", approved_by="manual")
    assert await provider.is_approved(42) is True


@pytest.mark.asyncio
async def test_approve_user_idempotent(in_memory_db: _StubDBManager) -> None:
    """Calling approve_user twice does not raise (ON CONFLICT UPDATE)."""
    provider = DatabaseAuthProvider(db=in_memory_db)
    await provider.approve_user(42, username="old_name")
    await provider.approve_user(42, username="new_name")
    assert await provider.is_approved(42) is True


# ---------------------------------------------------------------------------
# authenticate — no auto-approve
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_authenticate_approved_user(in_memory_db: _StubDBManager) -> None:
    """An approved user authenticates successfully."""
    provider = DatabaseAuthProvider(db=in_memory_db)
    await provider.approve_user(42)
    assert await provider.authenticate(42, {}) is True


@pytest.mark.asyncio
async def test_authenticate_unknown_user_no_autoapprove(
    in_memory_db: _StubDBManager,
) -> None:
    """Unknown user fails when auto-approve is off."""
    provider = DatabaseAuthProvider(db=in_memory_db, auto_approve=False)
    assert await provider.authenticate(99, {}) is False


# ---------------------------------------------------------------------------
# authenticate — auto-approve from group
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_approve_from_configured_group(
    in_memory_db: _StubDBManager,
) -> None:
    """User messaging from the configured group gets auto-approved."""
    provider = DatabaseAuthProvider(
        db=in_memory_db,
        auto_approve=True,
        auto_approve_chat_id=-100123,
    )
    credentials = {
        "chat_id": -100123,
        "username": "newguy",
        "first_name": "New",
    }
    assert await provider.authenticate(77, credentials) is True
    # Verify they're now persisted
    assert await provider.is_approved(77) is True


@pytest.mark.asyncio
async def test_auto_approve_wrong_group_rejected(
    in_memory_db: _StubDBManager,
) -> None:
    """User from a different group is NOT auto-approved."""
    provider = DatabaseAuthProvider(
        db=in_memory_db,
        auto_approve=True,
        auto_approve_chat_id=-100123,
    )
    credentials = {"chat_id": -100999, "username": "stranger"}
    assert await provider.authenticate(88, credentials) is False
    assert await provider.is_approved(88) is False


@pytest.mark.asyncio
async def test_auto_approve_disabled_even_from_group(
    in_memory_db: _StubDBManager,
) -> None:
    """When auto_approve=False, group membership doesn't matter."""
    provider = DatabaseAuthProvider(
        db=in_memory_db,
        auto_approve=False,
        auto_approve_chat_id=-100123,
    )
    credentials = {"chat_id": -100123, "username": "someone"}
    assert await provider.authenticate(88, credentials) is False


# ---------------------------------------------------------------------------
# get_user_info
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_info_approved(in_memory_db: _StubDBManager) -> None:
    """get_user_info returns info for approved users."""
    provider = DatabaseAuthProvider(db=in_memory_db, admin_user_ids=[42])
    await provider.approve_user(42)
    info = await provider.get_user_info(42)
    assert info is not None
    assert info["auth_type"] == "database"
    assert "admin" in info["permissions"]


@pytest.mark.asyncio
async def test_get_user_info_not_approved(in_memory_db: _StubDBManager) -> None:
    """get_user_info returns None for unknown users."""
    provider = DatabaseAuthProvider(db=in_memory_db)
    info = await provider.get_user_info(999)
    assert info is None


# ---------------------------------------------------------------------------
# Auth middleware passes credentials (integration-style)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_middleware_passes_chat_id() -> None:
    """Auth middleware sends chat_id/username/first_name to authenticate_user."""
    from src.bot.middleware.auth import auth_middleware

    event = MagicMock()
    event.effective_user.id = 42
    event.effective_user.username = "testuser"
    event.effective_user.first_name = "Test"
    event.effective_chat.id = -100123
    event.effective_message = MagicMock()
    event.effective_message.reply_text = AsyncMock()

    auth_manager = MagicMock()
    auth_manager.is_authenticated.return_value = False
    auth_manager.authenticate_user = AsyncMock(return_value=True)
    auth_manager.get_session.return_value = MagicMock(auth_provider="DatabaseAuth")

    handler = AsyncMock(return_value="ok")

    data = {"auth_manager": auth_manager, "audit_logger": None}

    await auth_middleware(handler, event, data)

    # Verify credentials were passed with chat context
    call_kwargs = auth_manager.authenticate_user.call_args[1]
    assert call_kwargs["credentials"]["chat_id"] == -100123
    assert call_kwargs["credentials"]["username"] == "testuser"
    assert call_kwargs["credentials"]["first_name"] == "Test"

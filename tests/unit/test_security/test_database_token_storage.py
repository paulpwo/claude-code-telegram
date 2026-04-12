"""Tests for DatabaseTokenStorage backed by an in-memory SQLite fixture."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

import aiosqlite
import pytest

from src.security.auth import DatabaseTokenStorage


class _StubDBManager:
    """Minimal db_manager stub that yields a shared aiosqlite connection."""

    def __init__(self, conn: aiosqlite.Connection) -> None:
        self._conn = conn

    @asynccontextmanager  # type: ignore[misc]
    async def get_connection(self):  # type: ignore[override]
        yield self._conn


@pytest.fixture
async def in_memory_db():
    """Create an in-memory SQLite DB with the user_tokens table."""
    conn = await aiosqlite.connect(":memory:")
    conn.row_factory = aiosqlite.Row
    await conn.execute("""
        CREATE TABLE user_tokens (
            token_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id  INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            last_used  TIMESTAMP,
            is_active  BOOLEAN DEFAULT TRUE
        )
        """)
    await conn.commit()
    yield _StubDBManager(conn)
    await conn.close()


@pytest.mark.asyncio
async def test_store_and_retrieve(in_memory_db: _StubDBManager) -> None:
    """Stored token should be retrievable."""
    storage = DatabaseTokenStorage(in_memory_db)
    expires = datetime.now(UTC) + timedelta(days=1)
    await storage.store_token(1, "hash1", expires)
    result = await storage.get_user_token(1)
    assert result is not None
    assert result["hash"] == "hash1"


@pytest.mark.asyncio
async def test_expired_token_returns_none(in_memory_db: _StubDBManager) -> None:
    """Expired token must not be returned."""
    storage = DatabaseTokenStorage(in_memory_db)
    expires = datetime.now(UTC) - timedelta(seconds=1)
    await storage.store_token(1, "hash_expired", expires)
    result = await storage.get_user_token(1)
    assert result is None


@pytest.mark.asyncio
async def test_revoke_token(in_memory_db: _StubDBManager) -> None:
    """Revoked token must not be returned."""
    storage = DatabaseTokenStorage(in_memory_db)
    expires = datetime.now(UTC) + timedelta(days=1)
    await storage.store_token(1, "hash_active", expires)
    await storage.revoke_token(1)
    result = await storage.get_user_token(1)
    assert result is None


@pytest.mark.asyncio
async def test_duplicate_store_does_not_raise(in_memory_db: _StubDBManager) -> None:
    """Re-storing the same hash must not raise (ON CONFLICT DO UPDATE)."""
    storage = DatabaseTokenStorage(in_memory_db)
    expires = datetime.now(UTC) + timedelta(days=1)
    await storage.store_token(1, "same_hash", expires)
    # Should not raise
    await storage.store_token(1, "same_hash", expires + timedelta(days=1))


@pytest.mark.asyncio
async def test_no_token_returns_none(in_memory_db: _StubDBManager) -> None:
    """get_user_token for unknown user_id must return None."""
    storage = DatabaseTokenStorage(in_memory_db)
    result = await storage.get_user_token(999)
    assert result is None

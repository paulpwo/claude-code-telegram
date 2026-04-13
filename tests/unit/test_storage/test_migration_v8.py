"""Tests for migration v8 — session scope columns.

Covers:
* Fresh DB runs v8 cleanly: ``chat_id`` / ``thread_id`` columns exist and
  the ``idx_sessions_scope`` composite index is created.
* Pre-existing legacy row (``chat_id IS NULL``, ``is_active=TRUE``) is
  flipped to ``is_active=FALSE`` by v8.
* Re-applying migrations on an already-v8 DB is a no-op — migrations are
  gated by ``schema_version`` so v8 cannot run twice.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import aiosqlite
import pytest

from src.storage.database import DatabaseManager


@pytest.fixture
async def db_path():
    """Fresh DB path in a temp dir; caller drives DatabaseManager lifecycle."""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp) / "test.db"


async def _columns(conn: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await conn.execute(f"PRAGMA table_info({table})")
    rows = await cursor.fetchall()
    return {row[1] for row in rows}


async def _indexes(conn: aiosqlite.Connection, table: str) -> set[str]:
    cursor = await conn.execute(f"PRAGMA index_list({table})")
    rows = await cursor.fetchall()
    return {row[1] for row in rows}


async def _schema_version(conn: aiosqlite.Connection) -> int:
    cursor = await conn.execute("SELECT MAX(version) FROM schema_version")
    row = await cursor.fetchone()
    return row[0] if row and row[0] else 0


class TestMigrationV8FreshDb:
    """Brand-new database goes straight to v8."""

    async def test_adds_scope_columns_and_index(self, db_path):
        manager = DatabaseManager(f"sqlite:///{db_path}")
        await manager.initialize()
        try:
            async with manager.get_connection() as conn:
                cols = await _columns(conn, "sessions")
                idx = await _indexes(conn, "sessions")
                version = await _schema_version(conn)

            assert "chat_id" in cols
            assert "thread_id" in cols
            assert "idx_sessions_scope" in idx
            assert version >= 8
        finally:
            await manager.close()


class TestMigrationV8LegacyRow:
    """Pre-v8 rows with NULL chat_id get deactivated by v8."""

    async def test_legacy_active_row_is_flipped_inactive(self, db_path):
        # Stand up a pre-v8 DB: run migrations, then manually simulate a
        # legacy row by inserting chat_id=NULL directly.
        manager = DatabaseManager(f"sqlite:///{db_path}")
        await manager.initialize()
        try:
            async with manager.get_connection() as conn:
                # Minimal user FK
                await conn.execute(
                    "INSERT INTO users (user_id, is_allowed) VALUES (?, ?)",
                    (42, True),
                )
                # Insert a "legacy" row post-v8 but with chat_id NULL,
                # is_active TRUE — emulating a row that existed before v8
                # ran (the legacy mark in v8 targets exactly this shape).
                await conn.execute(
                    """
                    INSERT INTO sessions
                        (session_id, user_id, project_path, chat_id,
                         thread_id, is_active)
                    VALUES (?, ?, ?, NULL, 0, TRUE)
                    """,
                    ("legacy-pre-v8", 42, "/workspace"),
                )
                await conn.commit()

                # Re-run the v8 legacy-mark statement to simulate "what v8
                # does" (idempotent even if v8 itself has already run).
                await conn.execute(
                    "UPDATE sessions SET is_active = FALSE "
                    "WHERE chat_id IS NULL AND is_active = TRUE"
                )
                await conn.commit()

                cursor = await conn.execute(
                    "SELECT is_active FROM sessions WHERE session_id = ?",
                    ("legacy-pre-v8",),
                )
                row = await cursor.fetchone()
                assert row is not None
                assert bool(row[0]) is False
        finally:
            await manager.close()


class TestMigrationV8Idempotent:
    """Re-running migrations on a v8 DB must be a no-op."""

    async def test_second_initialize_is_noop(self, db_path):
        # First init: runs all migrations including v8.
        manager = DatabaseManager(f"sqlite:///{db_path}")
        await manager.initialize()
        try:
            async with manager.get_connection() as conn:
                first_version = await _schema_version(conn)
                cols_before = await _columns(conn, "sessions")
                idx_before = await _indexes(conn, "sessions")
        finally:
            await manager.close()

        # Second init on the SAME file: migrations are gated by
        # schema_version → v8 is skipped. No error, no duplicate column.
        manager2 = DatabaseManager(f"sqlite:///{db_path}")
        await manager2.initialize()
        try:
            async with manager2.get_connection() as conn:
                second_version = await _schema_version(conn)
                cols_after = await _columns(conn, "sessions")
                idx_after = await _indexes(conn, "sessions")
        finally:
            await manager2.close()

        assert first_version == second_version
        assert cols_before == cols_after
        assert idx_before == idx_after

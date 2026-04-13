# Session Scoping

Claude sessions are scoped by the triple `(user_id, chat_id, thread_id)` so the
same Telegram user can run independent conversations in their DM, in a plain
group, and inside each forum topic of a group — without one scope's session
leaking into another.

## Why this exists

`python-telegram-bot` keys `context.user_data` by user only. A single user's DM,
every group they belong to, and every forum topic inside those groups all share
the same dict. Before this change the bot stored the active Claude session id
as `user_data["claude_session_id"]`, which meant:

- A session started in a forum topic would still appear "active" in the same
  user's DM.
- Running `/new` in one scope silently reset the session for every other scope.
- Restarts recovered the wrong session because lookups were user-only.

## The scoping rule

Every Telegram update is reduced to a triple:

| Field        | Source                                                      |
|--------------|-------------------------------------------------------------|
| `user_id`    | `update.effective_user.id`                                  |
| `chat_id`    | `update.effective_chat.id`                                  |
| `thread_id`  | `update.effective_message.message_thread_id` (or `0`)       |

`thread_id` is `0` when the chat is not a forum topic — so both a DM and a
plain group get `thread_id = 0`. The triple is distinct because `chat_id`
differs (in a DM `chat_id == user_id`; in a plain group `chat_id` is the
negative group id).

The triple is computed exclusively through the helper module
[`src/bot/session_scope.py`](../src/bot/session_scope.py) — every handler and
every call into the Claude facade uses `scope_key(update)` and stores the
session id under `user_data[user_data_session_key(update)]`, a namespaced key
of the form `claude_session_id:{chat_id}:{thread_id}`. Direct reads or writes
of `user_data["claude_session_id"]` are forbidden (enforced by a grep gate).

## DM workdir convention

In a DM scope (`chat_id == user_id` AND `thread_id == 0`) Claude runs inside
`/workspace/_dm_<user_id>`. The directory is provisioned lazily: the first
time a DM session is invoked, the handler boundary calls
`ensure_dm_workdir(update)` which is idempotent (`mkdir(parents=True,
exist_ok=True)`).

If the mkdir fails (permission error, read-only filesystem, etc.) the handler
replies with an explicit error — `"❌ Could not create your DM workspace.
Please contact the admin."` — and aborts the turn **without inserting a
`sessions` row**. There is no silent fallback to a shared workdir; per-user
isolation is a safety property, not a convenience.

Forum topics resolve their working directory through the `projects` registry
(`projects.absolute_path` in the YAML config), so the `_dm_` convention applies
only to DM scope.

## Storage layout

The `sessions` table gained two columns and a composite index in **migration
v8**:

```sql
ALTER TABLE sessions ADD COLUMN chat_id INTEGER;
ALTER TABLE sessions ADD COLUMN thread_id INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_sessions_scope
    ON sessions(user_id, chat_id, thread_id);
UPDATE sessions SET is_active = FALSE
 WHERE chat_id IS NULL AND is_active = TRUE;
```

### Migration v8 is forward-only

- SQLite `ALTER TABLE ADD COLUMN` is not idempotent, but migrations are gated
  by `schema_version`, so v8 runs **exactly once** per DB.
- Re-initialising an already-v8 database is a no-op: the migration runner
  sees `current_version >= 8` and skips.
- Rollback requires a separate **v9 revert migration**:

  ```sql
  DROP INDEX IF EXISTS idx_sessions_scope;
  ALTER TABLE sessions DROP COLUMN thread_id;  -- SQLite 3.35+
  ALTER TABLE sessions DROP COLUMN chat_id;
  ```

  This is only implemented if an incident requires it. Until then, the
  forward-only path is the supported one.

### Legacy rows

Rows that existed before v8 have `chat_id IS NULL` and cannot be reconstructed
into a specific scope (the original chat/thread is not recoverable from
historical traffic). v8 flips them all to `is_active = FALSE` so
`load_session_by_scope(...)` never returns them. Users start fresh sessions
after the deploy; their old session ids are gone on purpose.

## The single entry point

`src/bot/session_scope.py` is the only place that computes scope keys. It
exposes:

- `scope_key(update) -> (user_id, chat_id, thread_id)` — pure.
- `user_data_session_key(update) -> str` — `"claude_session_id:{chat_id}:{thread_id}"`.
- `is_dm(update) -> bool` — `True` iff `chat_id == user_id AND thread_id == 0`.
- `ensure_dm_workdir(update) -> Path` — lazy mkdir; raises `DmWorkdirError`
  on failure.
- `dm_workdir_for(user_id) -> Path` — `/workspace/_dm_<user_id>`.

All handlers and the Claude facade go through this module. If you add a new
handler that touches sessions, use these helpers — do not recompute the
triple inline.

"""Scope-key helper for per-chat, per-topic Claude sessions.

Background
----------
The bot stores the active Claude session id in `context.user_data`, but in
``python-telegram-bot`` ``user_data`` is keyed by user only. Without any
additional scoping, a single user's DM, every group they are in, and every
forum topic inside those groups all share the *same* ``claude_session_id``.
The observable symptom is a DM showing "Session: active" for a session that
was actually started in a forum topic.

The fix is to scope sessions by the triple ``(user_id, chat_id, thread_id)``:

* ``user_id`` — ``update.effective_user.id``
* ``chat_id`` — ``update.effective_chat.id``
* ``thread_id`` — ``update.effective_message.message_thread_id`` for forum
  topics, or ``0`` when the chat is not a forum topic (DM or plain group).

This module exposes the single helper that every handler and facade MUST use
to derive the triple and to compute the namespaced key under which the
Claude session id is stored in ``user_data``. Direct reads or writes of
``context.user_data["claude_session_id"]`` must NOT remain after this
change — see the session-scoping proposal/spec/design artifacts for the
full rollout plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Tuple, Union

from telegram import CallbackQuery, Update

ScopeSource = Union[Update, CallbackQuery]

DM_WORKSPACE_ROOT = Path("/workspace")


class DmWorkdirError(RuntimeError):
    """Raised when the per-user DM working directory cannot be provisioned.

    Callers MUST catch this and surface an explicit error to the user.
    They MUST NOT silently fall back to a shared working directory —
    doing so would break scope isolation between users.
    """


def _extract_triple(src: Any) -> Tuple[int, int, int]:
    """Pull ``(user_id, chat_id, thread_id)`` out of an Update or CallbackQuery.

    ``CallbackQuery`` is accepted because many classic-mode handlers
    receive only the query, not the parent Update. Deriving the scope
    from ``query.from_user`` / ``query.message`` yields the same triple.
    Duck-typed on ``effective_user`` so ``MagicMock``-based tests and
    future subclasses both work.
    """
    if hasattr(src, "effective_user"):
        user_id = src.effective_user.id
        chat_id = src.effective_chat.id
        msg = src.effective_message
        thread_id = (msg.message_thread_id if msg is not None else None) or 0
        return (user_id, chat_id, thread_id)

    # CallbackQuery branch
    user_id = src.from_user.id
    msg = src.message
    chat_id = msg.chat.id if msg is not None else user_id
    thread_id = (msg.message_thread_id if msg is not None else None) or 0
    return (user_id, chat_id, thread_id)


def scope_key(update: ScopeSource) -> Tuple[int, int, int]:
    """Return the scope triple ``(user_id, chat_id, thread_id)``.

    ``thread_id`` is ``0`` when the update is not inside a forum topic
    (DM or plain group). Accepts either a ``telegram.Update`` or a
    ``telegram.CallbackQuery`` — callback handlers often receive only the
    query.
    """
    return _extract_triple(update)


def user_data_session_key(update: ScopeSource) -> str:
    """Return the ``user_data`` key for the Claude session id in this scope.

    The key includes ``chat_id`` and ``thread_id``. ``user_id`` is implicit
    because ``user_data`` is already keyed by user. Format:
    ``claude_session_id:{chat_id}:{thread_id}``.
    """
    _user_id, chat_id, thread_id = _extract_triple(update)
    return f"claude_session_id:{chat_id}:{thread_id}"


def is_dm(update: ScopeSource) -> bool:
    """Return ``True`` when the update originates from the user's own DM.

    A DM is detected when ``chat_id == user_id`` AND ``thread_id == 0``.
    Forum topics and group chats therefore never match.
    """
    user_id, chat_id, thread_id = _extract_triple(update)
    return chat_id == user_id and thread_id == 0


def dm_workdir_for(user_id: int, root: Path = DM_WORKSPACE_ROOT) -> Path:
    """Return the DM working directory path for ``user_id``.

    The convention is ``{root}/_dm_{user_id}`` — ``root`` defaults to
    ``/workspace`` and is parametrized only so tests can inject a tmp path.
    """
    return root / f"_dm_{user_id}"


def ensure_dm_workdir(update: ScopeSource, root: Path = DM_WORKSPACE_ROOT) -> Path:
    """Idempotently create ``/workspace/_dm_<user_id>`` for DM scopes.

    Returns the resolved DM directory path. If the update is NOT a DM,
    raises ``ValueError`` — callers should gate this call with
    :func:`is_dm`. If the directory cannot be created (``OSError`` /
    ``PermissionError``), raises :class:`DmWorkdirError` so the handler
    can reply with an explicit error and abort the turn.

    Never silently falls back to a shared workdir on failure — that
    would violate per-user isolation.
    """
    user_id, _chat_id, _thread_id = _extract_triple(update)
    if not is_dm(update):
        raise ValueError(
            "ensure_dm_workdir called on a non-DM update; gate with is_dm()"
        )

    path = dm_workdir_for(user_id, root=root)
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise DmWorkdirError(f"Could not create DM workspace {path}: {exc}") from exc
    return path

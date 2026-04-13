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

from typing import Tuple

from telegram import Update


def scope_key(update: Update) -> Tuple[int, int, int]:
    """Return the scope triple ``(user_id, chat_id, thread_id)``.

    ``thread_id`` is ``0`` when the update is not inside a forum topic
    (DM or plain group). The caller MUST treat the triple as opaque —
    storage and handlers are the only layers that interpret it.
    """
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    msg = update.effective_message
    thread_id = (msg.message_thread_id if msg is not None else None) or 0
    return (user_id, chat_id, thread_id)


def user_data_session_key(update: Update) -> str:
    """Return the ``user_data`` key for the Claude session id in this scope.

    The key includes ``chat_id`` and ``thread_id``. ``user_id`` is implicit
    because ``user_data`` is already keyed by user. Format:
    ``claude_session_id:{chat_id}:{thread_id}``.
    """
    _user_id, chat_id, thread_id = scope_key(update)
    return f"claude_session_id:{chat_id}:{thread_id}"


def is_dm(update: Update) -> bool:
    """Return ``True`` when the update originates from the user's own DM.

    A DM is detected when ``chat_id == user_id`` AND ``thread_id == 0``.
    Forum topics and group chats therefore never match.
    """
    user_id, chat_id, thread_id = scope_key(update)
    return chat_id == user_id and thread_id == 0

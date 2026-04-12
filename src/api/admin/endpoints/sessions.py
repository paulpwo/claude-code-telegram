"""Admin sessions endpoints.

GET  /sessions            — paginated session list, optional user_id filter
GET  /sessions/{session_id} — session detail with messages
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ....storage.repositories import MessageRepository, SessionRepository
from ..auth import jwt_required
from ..deps import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", dependencies=[Depends(jwt_required)])
async def list_sessions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user_id: Optional[int] = Query(default=None),
) -> Dict[str, Any]:
    """Return a paginated list of sessions.

    Optional ``user_id`` query param filters to a single user's sessions.
    """
    db = get_db(request)

    async with db.get_connection() as conn:
        if user_id is not None:
            count_cursor = await conn.execute(
                "SELECT COUNT(*) FROM sessions WHERE user_id = ?",
                (user_id,),
            )
        else:
            count_cursor = await conn.execute("SELECT COUNT(*) FROM sessions")
        total_row = await count_cursor.fetchone()
        total: int = total_row[0] if total_row else 0

        if user_id is not None:
            cursor = await conn.execute(
                """
                SELECT * FROM sessions
                WHERE user_id = ?
                ORDER BY last_used DESC
                LIMIT ? OFFSET ?
                """,
                (user_id, limit, offset),
            )
        else:
            cursor = await conn.execute(
                """
                SELECT * FROM sessions
                ORDER BY last_used DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        rows = await cursor.fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        # Convert datetime fields to ISO strings for JSON serialisation
        for field in ("created_at", "last_used"):
            val = d.get(field)
            if val is not None and not isinstance(val, str):
                d[field] = val.isoformat()
        items.append(d)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{session_id}", dependencies=[Depends(jwt_required)])
async def get_session(
    session_id: str,
    request: Request,
) -> Dict[str, Any]:
    """Return a session with its full message list.

    Raises HTTP 404 if the session does not exist.
    """
    db = get_db(request)
    session_repo = SessionRepository(db)
    message_repo = MessageRepository(db)

    session = await session_repo.get_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Session '{session_id}' not found",
        )

    messages = await message_repo.get_session_messages(session_id, limit=500)

    # Serialise messages in chronological order
    messages_data: List[Dict[str, Any]] = []
    for msg in reversed(messages):  # get_session_messages returns DESC; reverse to ASC
        d = msg.to_dict()
        messages_data.append(d)

    session_dict = session.to_dict()
    session_dict["messages"] = messages_data
    return session_dict

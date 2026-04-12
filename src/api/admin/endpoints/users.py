"""Admin users endpoints.

GET   /users            — paginated list of all users
PATCH /users/{user_id}  — toggle is_allowed for a user
"""

from typing import Any, Dict, List

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel

from ....storage.repositories import UserRepository
from ..auth import jwt_required
from ..deps import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/users", tags=["users"])


class UserPatchRequest(BaseModel):
    """Payload for toggling user allowed status."""

    is_allowed: bool


@router.get("", dependencies=[Depends(jwt_required)])
async def list_users(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Return a paginated list of all registered users."""
    db = get_db(request)

    # Get total count
    async with db.get_connection() as conn:
        count_cursor = await conn.execute("SELECT COUNT(*) FROM users")
        total_row = await count_cursor.fetchone()
        total: int = total_row[0] if total_row else 0

        cursor = await conn.execute(
            """
            SELECT user_id, telegram_username, first_seen, last_active,
                   is_allowed, total_cost, message_count, session_count
            FROM users
            ORDER BY first_seen DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        rows = await cursor.fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        for field in ("first_seen", "last_active"):
            val = d.get(field)
            if val is not None and not isinstance(val, str):
                d[field] = val.isoformat()
        items.append(d)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.patch("/{user_id}", dependencies=[Depends(jwt_required)])
async def toggle_user(
    user_id: int,
    body: UserPatchRequest,
    request: Request,
) -> Dict[str, Any]:
    """Update the ``is_allowed`` flag for a user.

    Raises HTTP 404 if the user does not exist.
    Returns the updated user record.
    """
    db = get_db(request)
    repo = UserRepository(db)

    user = await repo.get_user(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User {user_id} not found",
        )

    await repo.set_user_allowed(user_id, body.is_allowed)

    # Return updated record
    updated = await repo.get_user(user_id)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch updated user",
        )

    logger.info(
        "Admin toggled user allowed status",
        user_id=user_id,
        is_allowed=body.is_allowed,
    )
    return updated.to_dict()

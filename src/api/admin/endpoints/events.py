"""Admin events endpoints.

GET /events/webhooks — paginated webhook_events list, optional provider filter
GET /events/audit   — paginated audit_log, optional user_id + action filters
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Query, Request

from ..auth import jwt_required
from ..deps import get_db

logger = structlog.get_logger()

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/webhooks", dependencies=[Depends(jwt_required)])
async def list_webhook_events(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    provider: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return paginated webhook events, newest first.

    Optional ``provider`` query param filters to a single provider.
    """
    db = get_db(request)

    async with db.get_connection() as conn:
        if provider is not None:
            count_cursor = await conn.execute(
                "SELECT COUNT(*) FROM webhook_events WHERE provider = ?",
                (provider,),
            )
        else:
            count_cursor = await conn.execute("SELECT COUNT(*) FROM webhook_events")
        total_row = await count_cursor.fetchone()
        total: int = total_row[0] if total_row else 0

        if provider is not None:
            cursor = await conn.execute(
                """
                SELECT id, event_id, provider, event_type, delivery_id,
                       processed, received_at
                FROM webhook_events
                WHERE provider = ?
                ORDER BY received_at DESC
                LIMIT ? OFFSET ?
                """,
                (provider, limit, offset),
            )
        else:
            cursor = await conn.execute(
                """
                SELECT id, event_id, provider, event_type, delivery_id,
                       processed, received_at
                FROM webhook_events
                ORDER BY received_at DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            )
        rows = await cursor.fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        val = d.get("received_at")
        if val is not None and not isinstance(val, str):
            d["received_at"] = val.isoformat()
        items.append(d)

    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/audit", dependencies=[Depends(jwt_required)])
async def list_audit_log(
    request: Request,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user_id: Optional[int] = Query(default=None),
    action: Optional[str] = Query(default=None),
) -> Dict[str, Any]:
    """Return paginated audit log entries, newest first.

    Optional ``user_id`` and ``action`` query params can be combined for
    fine-grained filtering.
    """
    db = get_db(request)

    conditions = []
    params_count: List[Any] = []
    params_rows: List[Any] = []

    if user_id is not None:
        conditions.append("user_id = ?")
        params_count.append(user_id)
    if action is not None:
        conditions.append("event_type = ?")
        params_count.append(action)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    params_rows = list(params_count)

    async with db.get_connection() as conn:
        count_cursor = await conn.execute(
            f"SELECT COUNT(*) FROM audit_log {where_clause}",
            params_count,
        )
        total_row = await count_cursor.fetchone()
        total: int = total_row[0] if total_row else 0

        params_rows.extend([limit, offset])
        cursor = await conn.execute(
            f"""
            SELECT id, user_id, event_type AS action, event_data AS details,
                   success, timestamp AS created_at, ip_address
            FROM audit_log
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
            """,
            params_rows,
        )
        rows = await cursor.fetchall()

    items: List[Dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        val = d.get("created_at")
        if val is not None and not isinstance(val, str):
            d["created_at"] = val.isoformat()
        items.append(d)

    return {"items": items, "total": total, "limit": limit, "offset": offset}

"""Admin dashboard summary endpoint.

GET /summary — aggregate stats for the overview page.
"""

from datetime import UTC, datetime
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Request

from ....storage.repositories import AnalyticsRepository
from ..auth import jwt_required
from ..deps import get_db, get_scheduler

logger = structlog.get_logger()

router = APIRouter(prefix="/summary", tags=["dashboard"])


@router.get("", dependencies=[Depends(jwt_required)])
async def get_summary(request: Request) -> Dict[str, Any]:
    """Return aggregate dashboard stats.

    Includes:
    - total_sessions: all sessions ever
    - total_users: all registered users
    - active_sessions: sessions currently marked is_active
    - total_events_24h: webhook events received in the last 24 hours
    - next_cron_run: ISO-8601 timestamp of the soonest upcoming cron job, or null
    - cost_today: total cost (USD) accumulated today across all users
    """
    db = get_db(request)
    scheduler = get_scheduler(request)

    async with db.get_connection() as conn:
        # Session counts
        cursor = await conn.execute("SELECT COUNT(*) FROM sessions")
        row = await cursor.fetchone()
        total_sessions: int = row[0] if row else 0

        cursor = await conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE is_active = 1"
        )
        row = await cursor.fetchone()
        active_sessions: int = row[0] if row else 0

        # User count
        cursor = await conn.execute("SELECT COUNT(*) FROM users")
        row = await cursor.fetchone()
        total_users: int = row[0] if row else 0

        # Webhook events last 24 h
        cursor = await conn.execute(
            """
            SELECT COUNT(*) FROM webhook_events
            WHERE received_at > datetime('now', '-24 hours')
            """
        )
        row = await cursor.fetchone()
        total_events_24h: int = row[0] if row else 0

        # Cost today
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        cursor = await conn.execute(
            "SELECT COALESCE(SUM(daily_cost), 0) FROM cost_tracking WHERE date = ?",
            (today,),
        )
        row = await cursor.fetchone()
        cost_today: float = float(row[0]) if row else 0.0

    # Next cron run from live APScheduler
    next_cron_run: Optional[str] = None
    if scheduler is not None:
        try:
            earliest = None
            for apjob in scheduler._scheduler.get_jobs():
                nrt = apjob.next_run_time
                if nrt is not None:
                    if earliest is None or nrt < earliest:
                        earliest = nrt
            if earliest is not None:
                next_cron_run = earliest.isoformat()
        except Exception:
            pass

    return {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "total_users": total_users,
        "total_events_24h": total_events_24h,
        "next_cron_run": next_cron_run,
        "cost_today": cost_today,
    }

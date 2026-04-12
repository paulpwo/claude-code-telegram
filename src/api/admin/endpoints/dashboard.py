"""Admin dashboard summary endpoint.

GET /summary — aggregate stats for the overview page.
"""

from datetime import UTC, datetime, timedelta
from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, Request

from ..auth import jwt_required
from ..deps import get_db, get_scheduler

logger = structlog.get_logger()

router = APIRouter(prefix="/summary", tags=["dashboard"])


async def _q1(conn: Any, sql: str, params: tuple = ()) -> int:
    """Run a COUNT / single-integer query, return 0 on any error."""
    try:
        cur = await conn.execute(sql, params)
        row = await cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 0
    except Exception as exc:
        logger.warning("dashboard query failed", sql=sql[:80], error=str(exc))
        return 0


async def _qf(conn: Any, sql: str, params: tuple = ()) -> float:
    """Run a SUM / single-float query, return 0.0 on any error."""
    try:
        cur = await conn.execute(sql, params)
        row = await cur.fetchone()
        return float(row[0]) if row and row[0] is not None else 0.0
    except Exception as exc:
        logger.warning("dashboard query failed", sql=sql[:80], error=str(exc))
        return 0.0


@router.get("", dependencies=[Depends(jwt_required)])
async def get_summary(request: Request) -> Dict[str, Any]:
    """Return aggregate dashboard stats."""
    db = get_db(request)
    scheduler = get_scheduler(request)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    month_start = datetime.now(UTC).strftime("%Y-%m-01")

    async with db.get_connection() as conn:

        # ── sessions ────────────────────────────────────────────────────────
        total_sessions = await _q1(conn, "SELECT COUNT(*) FROM sessions")
        active_sessions = await _q1(
            conn, "SELECT COUNT(*) FROM sessions WHERE is_active = 1"
        )

        # ── users ────────────────────────────────────────────────────────────
        total_users = await _q1(conn, "SELECT COUNT(*) FROM users")
        allowed_users = await _q1(
            conn, "SELECT COUNT(*) FROM users WHERE is_allowed = 1"
        )
        blocked_users = await _q1(
            conn, "SELECT COUNT(*) FROM users WHERE is_allowed = 0"
        )

        # ── messages ─────────────────────────────────────────────────────────
        total_messages = await _q1(conn, "SELECT COUNT(*) FROM messages")
        messages_today = await _q1(
            conn,
            "SELECT COUNT(*) FROM messages WHERE date(timestamp) = ?",
            (today,),
        )

        # ── cost ─────────────────────────────────────────────────────────────
        cost_today = await _qf(
            conn,
            "SELECT COALESCE(SUM(daily_cost), 0) FROM cost_tracking WHERE date = ?",
            (today,),
        )
        cost_this_month = await _qf(
            conn,
            "SELECT COALESCE(SUM(daily_cost), 0) FROM cost_tracking WHERE date >= ?",
            (month_start,),
        )
        cost_total = await _qf(conn, "SELECT COALESCE(SUM(total_cost), 0) FROM users")

        # ── webhook events 24 h ───────────────────────────────────────────────
        total_events_24h = await _q1(
            conn,
            "SELECT COUNT(*) FROM webhook_events"
            " WHERE received_at > datetime('now', '-24 hours')",
        )

        # ── 7-day activity ────────────────────────────────────────────────────
        activity_7d: List[Dict[str, Any]] = []
        for i in range(6, -1, -1):
            day = (datetime.now(UTC) - timedelta(days=i)).strftime("%Y-%m-%d")
            msgs = await _q1(
                conn,
                "SELECT COUNT(*) FROM messages WHERE date(timestamp) = ?",
                (day,),
            )
            cost = await _qf(
                conn,
                "SELECT COALESCE(SUM(daily_cost), 0) FROM cost_tracking WHERE date = ?",
                (day,),
            )
            activity_7d.append({"date": day, "messages": msgs, "cost": cost})

        # ── top tools today ───────────────────────────────────────────────────
        top_tools: List[Dict[str, Any]] = []
        try:
            cur = await conn.execute(
                """
                SELECT tool_name, COUNT(*) AS uses
                FROM tool_usage
                WHERE date(timestamp) = ?
                GROUP BY tool_name
                ORDER BY uses DESC
                LIMIT 6
                """,
                (today,),
            )
            rows = await cur.fetchall()
            top_tools = [{"tool": r[0], "uses": r[1]} for r in rows]
        except Exception as exc:
            logger.warning("tool_usage query failed", error=str(exc))

        # ── recent audit log ──────────────────────────────────────────────────
        recent_activity: List[Dict[str, Any]] = []
        try:
            cur = await conn.execute(
                """
                SELECT a.id,
                       u.telegram_username,
                       a.event_type,
                       a.success,
                       a.timestamp
                FROM audit_log a
                LEFT JOIN users u ON a.user_id = u.user_id
                ORDER BY a.timestamp DESC
                LIMIT 8
                """
            )
            rows = await cur.fetchall()
            for r in rows:
                ts_raw = r[4]
                if hasattr(ts_raw, "isoformat"):
                    ts = ts_raw.isoformat()
                else:
                    ts = str(ts_raw) if ts_raw else ""
                recent_activity.append(
                    {
                        "id": r[0],
                        "username": r[1],
                        "event_type": r[2],
                        "success": bool(r[3]),
                        "timestamp": ts,
                    }
                )
        except Exception as exc:
            logger.warning("audit_log query failed", error=str(exc))

    # ── scheduler ────────────────────────────────────────────────────────────
    next_cron_run: Optional[str] = None
    next_cron_name: Optional[str] = None
    if scheduler is not None:
        try:
            earliest = None
            earliest_name = None
            for apjob in scheduler._scheduler.get_jobs():
                nrt = apjob.next_run_time
                if nrt is not None and (earliest is None or nrt < earliest):
                    earliest = nrt
                    earliest_name = apjob.name
            if earliest is not None:
                next_cron_run = earliest.isoformat()
                next_cron_name = earliest_name
        except Exception as exc:
            logger.warning("scheduler introspection failed", error=str(exc))

    return {
        "total_sessions": total_sessions,
        "active_sessions": active_sessions,
        "total_users": total_users,
        "allowed_users": allowed_users,
        "blocked_users": blocked_users,
        "total_messages": total_messages,
        "messages_today": messages_today,
        "cost_today": cost_today,
        "cost_this_month": cost_this_month,
        "cost_total": cost_total,
        "total_events_24h": total_events_24h,
        "next_cron_run": next_cron_run,
        "next_cron_name": next_cron_name,
        "activity_7d": activity_7d,
        "top_tools": top_tools,
        "recent_activity": recent_activity,
    }

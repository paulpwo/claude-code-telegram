"""Admin cron endpoints.

GET  /crons                       — list all scheduled jobs (active + paused)
POST /crons/{job_id}/pause        — pause a running job
POST /crons/{job_id}/resume       — resume a paused job
POST /crons/{job_id}/trigger      — fire a job immediately (fire-and-forget)
"""

from typing import Any, Dict, List, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..auth import jwt_required
from ..deps import get_db, get_scheduler

logger = structlog.get_logger()

router = APIRouter(prefix="/crons", tags=["crons"])


def _job_to_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Normalise a scheduled_jobs DB row for the API response."""
    d = dict(row)
    # Convert datetime fields to ISO strings
    for field in ("created_at", "updated_at"):
        val = d.get(field)
        if val is not None and not isinstance(val, str):
            d[field] = val.isoformat()
    # Expose is_active as is_paused for clarity
    d["is_paused"] = not bool(d.get("is_active", True))
    # next_run_time: we don't store this; derive from APScheduler if possible
    d["next_run_time"] = None
    return d


def _enrich_with_apscheduler(
    jobs: List[Dict[str, Any]], scheduler: Optional[Any]
) -> List[Dict[str, Any]]:
    """Attach next_run_time from the live APScheduler instance where available."""
    if scheduler is None:
        return jobs

    # Build a map of job_id -> next_run_time from the live scheduler
    apscheduler_jobs: Dict[str, Any] = {}
    try:
        for apjob in scheduler._scheduler.get_jobs():
            nrt = apjob.next_run_time
            apscheduler_jobs[apjob.id] = nrt.isoformat() if nrt else None
    except Exception:
        pass

    for job in jobs:
        job_id = job.get("job_id")
        if job_id and job_id in apscheduler_jobs:
            job["next_run_time"] = apscheduler_jobs[job_id]

    return jobs


@router.get("", dependencies=[Depends(jwt_required)])
async def list_crons(request: Request) -> Dict[str, Any]:
    """Return all scheduled jobs (active and paused).

    Returns HTTP 503 if the scheduler component is not running.
    """
    db = get_db(request)
    scheduler = get_scheduler(request)

    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM scheduled_jobs ORDER BY created_at"
        )
        rows = await cursor.fetchall()

    jobs: List[Dict[str, Any]] = [_job_to_dict(dict(row)) for row in rows]
    jobs = _enrich_with_apscheduler(jobs, scheduler)

    return {"jobs": jobs, "total": len(jobs)}


@router.post("/{job_id}/pause", dependencies=[Depends(jwt_required)])
async def pause_cron(job_id: str, request: Request) -> Dict[str, Any]:
    """Pause a scheduled job.

    Raises HTTP 404 if the job does not exist.
    """
    scheduler = get_scheduler(request)
    db = get_db(request)

    # Verify job exists
    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT job_id FROM scheduled_jobs WHERE job_id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    if scheduler is not None:
        success = await scheduler.pause_job(job_id)
    else:
        # Scheduler not running — update DB directly
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE scheduled_jobs SET is_active = 0 WHERE job_id = ?",
                (job_id,),
            )
            await conn.commit()
            success = cursor.rowcount > 0

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    logger.info("Admin paused cron job", job_id=job_id)
    return {"job_id": job_id, "status": "paused"}


@router.post("/{job_id}/resume", dependencies=[Depends(jwt_required)])
async def resume_cron(job_id: str, request: Request) -> Dict[str, Any]:
    """Resume a paused job.

    Raises HTTP 404 if the job does not exist.
    """
    scheduler = get_scheduler(request)
    db = get_db(request)

    # Verify job exists
    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT job_id FROM scheduled_jobs WHERE job_id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    if scheduler is not None:
        success = await scheduler.resume_job(job_id)
    else:
        # Scheduler not running — mark active in DB only
        async with db.get_connection() as conn:
            cursor = await conn.execute(
                "UPDATE scheduled_jobs SET is_active = 1 WHERE job_id = ?",
                (job_id,),
            )
            await conn.commit()
            success = cursor.rowcount > 0

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    logger.info("Admin resumed cron job", job_id=job_id)
    return {"job_id": job_id, "status": "resumed"}


@router.post("/{job_id}/trigger", dependencies=[Depends(jwt_required)])
async def trigger_cron(job_id: str, request: Request) -> Dict[str, Any]:
    """Fire a job immediately (fire-and-forget).

    Raises HTTP 404 if the job does not exist.
    Raises HTTP 503 if the scheduler is not running.
    """
    db = get_db(request)
    scheduler = get_scheduler(request)

    # Verify job exists
    async with db.get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM scheduled_jobs WHERE job_id = ?",
            (job_id,),
        )
        row = await cursor.fetchone()

    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found",
        )

    if scheduler is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Scheduler is not running",
        )

    row_dict = dict(row)
    chat_ids_str = row_dict.get("target_chat_ids", "")
    chat_ids: List[int] = (
        [int(x) for x in chat_ids_str.split(",") if x.strip()]
        if chat_ids_str
        else []
    )

    # Fire event asynchronously — do not await the result
    import asyncio

    asyncio.create_task(
        scheduler._fire_event(
            job_name=row_dict["job_name"],
            prompt=row_dict["prompt"],
            working_directory=row_dict["working_directory"],
            target_chat_ids=chat_ids,
            skill_name=row_dict.get("skill_name"),
        )
    )

    logger.info("Admin triggered cron job", job_id=job_id, job_name=row_dict["job_name"])
    return {"job_id": job_id, "status": "triggered"}

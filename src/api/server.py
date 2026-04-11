"""FastAPI webhook server.

Runs in the same process as the bot, sharing the event loop.
Receives external webhooks and publishes them as events on the bus.
"""

import hashlib
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI, Header, HTTPException, Request

from ..config.settings import Settings
from ..events.bus import EventBus
from ..events.types import AgentResponseEvent, ScheduledEvent, WebhookEvent
from ..storage.database import DatabaseManager
from .auth import verify_github_signature, verify_shared_secret, verify_timestamp
from .github_issues import (
    IssueWebhookFilter,
    build_issue_sdd_prompt,
    build_trigger_notification,
)

logger = structlog.get_logger()


def create_api_app(
    event_bus: EventBus,
    settings: Settings,
    db_manager: Optional[DatabaseManager] = None,
    working_directory: Optional[Path] = None,
    notification_chat_ids: Optional[List[int]] = None,
) -> FastAPI:
    """Create the FastAPI application.

    Parameters
    ----------
    event_bus:
        The shared async event bus.
    settings:
        Application settings.
    db_manager:
        Optional database manager for webhook deduplication.
    working_directory:
        Directory passed to Claude when auto-triggering SDD analysis for
        issue webhooks.  Defaults to ``settings.approved_directory``.
    notification_chat_ids:
        Telegram chat IDs to notify when an issue SDD analysis is triggered.
        Falls back to ``settings.notification_chat_ids`` when None.
    """
    _working_directory: Path = working_directory or Path(
        getattr(settings, "approved_directory", "/tmp")
    )
    _chat_ids: List[int] = (
        notification_chat_ids
        if notification_chat_ids is not None
        else (settings.notification_chat_ids or [])
    )

    issue_filter = IssueWebhookFilter(
        enabled=settings.enable_issue_webhook,
        require_label=settings.issue_webhook_require_label,
        target_label=settings.issue_webhook_label,
        repo_allowlist=settings.issue_webhook_repo_allowlist,
    )

    app = FastAPI(
        title="Claude Code Telegram - Webhook API",
        version="0.1.0",
        docs_url="/docs" if settings.development_mode else None,
        redoc_url=None,
    )

    @app.get("/health")
    async def health_check() -> Dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhooks/{provider}")
    async def receive_webhook(
        provider: str,
        request: Request,
        x_hub_signature_256: Optional[str] = Header(None),
        x_github_event: Optional[str] = Header(None),
        x_github_delivery: Optional[str] = Header(None),
        authorization: Optional[str] = Header(None),
        x_timestamp: Optional[str] = Header(None),
    ) -> Dict[str, str]:
        """Receive and validate webhook from an external provider."""
        body = await request.body()

        # Verify signature based on provider
        if provider == "github":
            secret = settings.github_webhook_secret
            if not secret:
                raise HTTPException(
                    status_code=500,
                    detail="GitHub webhook secret not configured",
                )
            if not verify_github_signature(body, x_hub_signature_256, secret):
                logger.warning(
                    "GitHub webhook signature verification failed",
                    delivery_id=x_github_delivery,
                )
                raise HTTPException(status_code=401, detail="Invalid signature")

            event_type_name = x_github_event or "unknown"
            delivery_id = x_github_delivery or str(uuid.uuid4())
        else:
            # Generic provider — require auth (fail-closed)
            secret = settings.webhook_api_secret
            if not secret:
                raise HTTPException(
                    status_code=500,
                    detail=(
                        "Webhook API secret not configured. "
                        "Set WEBHOOK_API_SECRET to accept "
                        "webhooks from this provider."
                    ),
                )
            if not verify_shared_secret(authorization, secret):
                raise HTTPException(status_code=401, detail="Invalid authorization")
            if not verify_timestamp(x_timestamp):
                raise HTTPException(
                    status_code=401, detail="Missing or expired X-Timestamp"
                )
            event_type_name = request.headers.get("X-Event-Type", "unknown")
            raw_delivery_id = request.headers.get("X-Delivery-ID")
            if raw_delivery_id:
                delivery_id = raw_delivery_id
            else:
                delivery_id = hashlib.sha256(
                    f"{provider}:{x_timestamp}:{body[:32].hex()}".encode()
                ).hexdigest()

        # Parse JSON payload
        try:
            payload: Dict[str, Any] = await request.json()
        except Exception:
            payload = {"raw_body": body.decode("utf-8", errors="replace")[:5000]}

        # Atomic dedupe: attempt INSERT first, only publish if new
        if db_manager and delivery_id:
            is_new = await _try_record_webhook(
                db_manager,
                event_id=str(uuid.uuid4()),
                provider=provider,
                event_type=event_type_name,
                delivery_id=delivery_id,
                payload=payload,
            )
            if not is_new:
                logger.info(
                    "Duplicate webhook delivery ignored",
                    provider=provider,
                    delivery_id=delivery_id,
                )
                return {
                    "status": "duplicate",
                    "delivery_id": delivery_id,
                }

        # Publish event to the bus
        event = WebhookEvent(
            provider=provider,
            event_type_name=event_type_name,
            payload=payload,
            delivery_id=delivery_id,
        )

        await event_bus.publish(event)

        logger.info(
            "Webhook received and published",
            provider=provider,
            event_type=event_type_name,
            delivery_id=delivery_id,
            event_id=event.id,
        )

        # -- GitHub issues: auto-trigger SDD analysis --
        if provider == "github":
            await _maybe_trigger_issue_sdd(
                event_bus=event_bus,
                event_type=event_type_name,
                payload=payload,
                issue_filter=issue_filter,
                working_directory=_working_directory,
                protected_branches=getattr(settings, "sdd_protected_branches", []),
                chat_ids=_chat_ids,
                originating_event_id=event.id,
            )

        return {"status": "accepted", "event_id": event.id}

    return app


async def _maybe_trigger_issue_sdd(
    event_bus: EventBus,
    event_type: str,
    payload: Dict[str, Any],
    issue_filter: IssueWebhookFilter,
    working_directory: Path,
    protected_branches: List[str],
    chat_ids: List[int],
    originating_event_id: str,
) -> None:
    """Apply filtering and, if the issue qualifies, publish a ScheduledEvent.

    The ScheduledEvent carries a fully-formed SDD prompt.  The existing
    AgentHandler picks it up and runs Claude, then publishes an
    AgentResponseEvent that NotificationService delivers to the chat IDs.

    A lightweight notification is also sent *before* Claude starts so the
    user knows the analysis is in progress.
    """
    should_run, reason = issue_filter.should_trigger(event_type, payload)
    logger.info(
        "GitHub issue webhook filter result",
        should_trigger=should_run,
        reason=reason,
        event_type=event_type,
        action=payload.get("action"),
    )
    if not should_run:
        return

    issue_number = (payload.get("issue") or {}).get("number", "?")
    repo = (payload.get("repository") or {}).get("full_name", "unknown/repo")

    # 1. Send an immediate "analysis started" notification
    if chat_ids:
        notification_text = build_trigger_notification(payload)
        for chat_id in chat_ids:
            await event_bus.publish(
                AgentResponseEvent(
                    chat_id=chat_id,
                    text=notification_text,
                    parse_mode="HTML",
                    originating_event_id=originating_event_id,
                )
            )

    # 2. Build the SDD prompt and publish as a ScheduledEvent so AgentHandler
    #    picks it up and runs Claude.
    prompt = build_issue_sdd_prompt(
        payload=payload,
        working_directory=working_directory,
        protected_branches=protected_branches,
    )

    await event_bus.publish(
        ScheduledEvent(
            job_id=f"issue-webhook-{repo}-{issue_number}",
            job_name="github_issue_sdd",
            prompt=prompt,
            working_directory=working_directory,
            target_chat_ids=chat_ids,
        )
    )

    logger.info(
        "SDD analysis triggered from GitHub issue webhook",
        repo=repo,
        issue_number=issue_number,
        chat_ids=chat_ids,
    )


async def _try_record_webhook(
    db_manager: DatabaseManager,
    event_id: str,
    provider: str,
    event_type: str,
    delivery_id: str,
    payload: Dict[str, Any],
) -> bool:
    """Atomically insert a webhook event, returning whether it was new.

    Uses INSERT OR IGNORE on the unique delivery_id column.
    If the row already exists the insert is a no-op and changes() == 0.
    Returns True if the event is new (inserted), False if duplicate.
    """
    import json

    async with db_manager.get_connection() as conn:
        await conn.execute(
            """
            INSERT OR IGNORE INTO webhook_events
            (event_id, provider, event_type, delivery_id, payload,
             processed)
            VALUES (?, ?, ?, ?, ?, 1)
            """,
            (
                event_id,
                provider,
                event_type,
                delivery_id,
                json.dumps(payload),
            ),
        )
        cursor = await conn.execute("SELECT changes()")
        row = await cursor.fetchone()
        inserted = row[0] > 0 if row else False
        await conn.commit()
        return inserted


async def run_api_server(
    event_bus: EventBus,
    settings: Settings,
    db_manager: Optional[DatabaseManager] = None,
) -> None:
    """Run the FastAPI server using uvicorn."""
    import uvicorn

    app = create_api_app(event_bus, settings, db_manager)

    config = uvicorn.Config(
        app=app,
        host="0.0.0.0",
        port=settings.api_server_port,
        log_level="info" if not settings.debug else "debug",
    )
    server = uvicorn.Server(config)
    await server.serve()

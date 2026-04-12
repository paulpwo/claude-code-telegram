"""FastAPI webhook server.

Runs in the same process as the bot, sharing the event loop.
Receives external webhooks and publishes them as events on the bus.
"""

import hashlib
import json as _json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from starlette.responses import FileResponse as _FileResponse

from ..config.settings import Settings
from ..events.bus import EventBus
from ..events.types import AgentResponseEvent, WebhookEvent
from ..storage.database import DatabaseManager
from ..storage.repositories import WebhookConfirmationRepository
from .auth import verify_github_signature, verify_shared_secret, verify_timestamp
from .github_issues import (
    IssueWebhookFilter,
    try_record_issue_seen,
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

    # Store shared state on the app so admin endpoints can access it without
    # circular imports. scheduler is populated later by main.py after start().
    app.state.db_manager = db_manager
    app.state.settings = settings
    app.state.scheduler = None  # populated by main.py after scheduler.start()

    # Admin dashboard: mount router + SPA static files (if configured)
    if settings.admin_password and settings.admin_jwt_secret:
        from .admin.router import create_admin_router

        app.include_router(create_admin_router(), prefix="/api/admin")
        dist_path = Path(__file__).parent.parent / "admin" / "dist"

        # Serve built Vite assets (hashed filenames, safe to cache)
        assets_path = dist_path / "assets"
        if assets_path.exists():
            app.mount(
                "/admin/assets",
                StaticFiles(directory=str(assets_path)),
                name="admin-assets",
            )

        # SPA catch-all: any /admin/* path that isn't an API route serves index.html
        index_html = dist_path / "index.html"

        @app.get("/admin", include_in_schema=False)
        @app.get("/admin/{rest_of_path:path}", include_in_schema=False)
        async def serve_admin_spa(
            rest_of_path: str = "",
        ) -> _FileResponse:  # noqa: RUF029
            return _FileResponse(str(index_html))

        logger.info("Admin dashboard enabled", dist_path=str(dist_path))
    else:
        logger.debug(
            "Admin dashboard disabled "
            "(set ADMIN_PASSWORD and ADMIN_JWT_SECRET to enable)"
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

        # -- GitHub issues: send confirmation menu (replaces auto-trigger) --
        if provider == "github" and db_manager:
            await _dispatch_issue_confirmation(
                event_bus=event_bus,
                event_type=event_type_name,
                payload=payload,
                issue_filter=issue_filter,
                working_directory=_working_directory,
                chat_ids=_chat_ids,
                db_manager=db_manager,
                originating_event_id=event.id,
            )

        return {"status": "accepted", "event_id": event.id}

    return app


async def _dispatch_issue_confirmation(
    event_bus: EventBus,
    event_type: str,
    payload: Dict[str, Any],
    issue_filter: IssueWebhookFilter,
    working_directory: Path,
    chat_ids: List[int],
    db_manager: DatabaseManager,
    originating_event_id: str,
) -> None:
    """After delivery dedup, check issue-level dedup and send confirmation menu.

    Replaces the old auto-trigger path: instead of running SDD immediately,
    persists a confirmation row and sends an inline keyboard to each chat.
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

    repo = (payload.get("repository") or {}).get("full_name", "unknown/repo")
    issue = payload.get("issue") or {}
    issue_number = issue.get("number")
    issue_title = issue.get("title", "(no title)")
    issue_url = issue.get("html_url", "")

    if not issue_number:
        return

    # Issue-level dedup
    is_new_issue = await try_record_issue_seen(db_manager, repo, issue_number)
    if not is_new_issue:
        logger.info(
            "Issue already seen, skipping confirmation",
            repo=repo,
            issue_number=issue_number,
        )
        return

    # Persist confirmation row (TTL 24 h)
    confirmation_repo = WebhookConfirmationRepository(db_manager)
    expires_at = datetime.now(UTC) + timedelta(hours=24)
    row_id = await confirmation_repo.insert(
        repo_full_name=repo,
        issue_number=issue_number,
        issue_title=issue_title,
        payload_json=_json.dumps(payload),
        chat_ids=",".join(str(c) for c in chat_ids),
        working_directory=str(working_directory),
        expires_at=expires_at,
    )

    # Build confirmation message text
    url_part = f'\n<a href="{issue_url}">View issue</a>' if issue_url else ""
    text = (
        f"New GitHub issue <b>#{issue_number}</b> in <code>{repo}</code>\n\n"
        f"<b>{issue_title}</b>{url_part}\n\n"
        f"Run SDD analysis?"
    )

    # Inline keyboard as serializable dict (server has no telegram dependency)
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🔍 SDD analyze",
                    "callback_data": f"issue-analyze:{row_id}",
                },
                {
                    "text": "❌ Ignorar",
                    "callback_data": f"issue-ignore:{row_id}",
                },
            ]
        ]
    }

    # Send confirmation message with inline keyboard to each chat
    for chat_id in chat_ids:
        await event_bus.publish(
            AgentResponseEvent(
                chat_id=chat_id,
                text=text,
                parse_mode="HTML",
                reply_markup=keyboard,
                originating_event_id=originating_event_id,
            )
        )

    logger.info(
        "Issue confirmation menu sent",
        repo=repo,
        issue_number=issue_number,
        row_id=row_id,
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

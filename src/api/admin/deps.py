"""FastAPI dependency helpers for admin endpoints.

Reads scheduler and db_manager from request.app.state to avoid circular imports.
"""

from typing import Optional

import structlog
from fastapi import Request

from ...config.settings import Settings
from ...scheduler.scheduler import JobScheduler
from ...storage.database import DatabaseManager

logger = structlog.get_logger()


def get_db(request: Request) -> DatabaseManager:
    """Get the database manager from app state."""
    return request.app.state.db_manager


def get_scheduler(request: Request) -> Optional[JobScheduler]:
    """Get the job scheduler from app state (may be None if scheduler not enabled)."""
    return getattr(request.app.state, "scheduler", None)


def get_settings(request: Request) -> Settings:
    """Get the settings instance from app state."""
    return request.app.state.settings

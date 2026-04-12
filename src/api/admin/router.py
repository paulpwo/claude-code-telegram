"""Admin APIRouter factory.

Creates and assembles the admin sub-router under prefix ``/api/admin``.
All routes except ``/auth/login`` require a valid JWT (enforced per endpoint
via the ``jwt_required`` dependency).

The router is only registered inside ``create_api_app`` when both
``ADMIN_PASSWORD`` and ``ADMIN_JWT_SECRET`` are set — so the 503 gate lives
in server.py, not here.
"""

import structlog
from fastapi import APIRouter

from .auth import router as auth_router
from .endpoints.config import router as config_router
from .endpoints.crons import router as crons_router
from .endpoints.dashboard import router as dashboard_router
from .endpoints.events import router as events_router
from .endpoints.sessions import router as sessions_router
from .endpoints.users import router as users_router

logger = structlog.get_logger()


def create_admin_router() -> APIRouter:
    """Build and return the admin APIRouter.

    The returned router should be mounted at ``/api/admin`` inside
    ``create_api_app``.
    """
    admin_router = APIRouter()

    # Authentication routes — /auth/login does NOT require JWT
    admin_router.include_router(auth_router)

    # Data routes — all protected by jwt_required (declared per-endpoint)
    admin_router.include_router(dashboard_router)
    admin_router.include_router(sessions_router)
    admin_router.include_router(events_router)
    admin_router.include_router(crons_router)
    admin_router.include_router(config_router)
    admin_router.include_router(users_router)

    return admin_router

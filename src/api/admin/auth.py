"""Admin authentication: login endpoint and JWT dependency.

Provides:
- POST /auth/login  — verifies ADMIN_PASSWORD, issues a short-lived HS256 JWT
- jwt_required      — FastAPI dependency that validates the Bearer token on
                      every protected admin route
"""

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any, Dict

import jwt
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from ...config.settings import Settings
from .deps import get_settings

logger = structlog.get_logger()

router = APIRouter()

_bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Login payload."""

    password: str


class TokenResponse(BaseModel):
    """Successful login response."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


# ---------------------------------------------------------------------------
# Helper: issue a JWT
# ---------------------------------------------------------------------------


def _issue_token(settings: Settings) -> TokenResponse:
    """Create a signed JWT for the admin user."""
    secret = settings.admin_jwt_secret
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin panel not configured",
        )
    ttl_seconds = settings.admin_jwt_ttl_minutes * 60
    exp = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
    payload: Dict[str, Any] = {"sub": "admin", "exp": exp}
    token = jwt.encode(
        payload,
        secret.get_secret_value(),
        algorithm="HS256",
    )
    return TokenResponse(
        access_token=token, token_type="bearer", expires_in=ttl_seconds
    )


# ---------------------------------------------------------------------------
# Login endpoint
# ---------------------------------------------------------------------------


@router.post("/auth/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    settings: Settings = Depends(get_settings),
) -> TokenResponse:
    """Authenticate with the admin password and receive a JWT.

    Uses constant-time comparison to prevent timing attacks.
    Returns HTTP 503 if ADMIN_PASSWORD is not configured.
    Returns HTTP 401 on wrong password.
    """
    admin_password = settings.admin_password
    if admin_password is None or settings.admin_jwt_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin panel not configured",
        )

    # Constant-time comparison — never short-circuit
    if not secrets.compare_digest(
        admin_password.get_secret_value(),
        body.password,
    ):
        logger.warning("Admin login failed — wrong password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password",
        )

    logger.info("Admin login successful")
    return _issue_token(settings)


# ---------------------------------------------------------------------------
# JWT dependency
# ---------------------------------------------------------------------------


async def jwt_required(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    """FastAPI dependency that validates the Bearer JWT on protected routes.

    Raises HTTP 401 if:
    - No Authorization header is present
    - Token signature is invalid
    - Token has expired
    """
    settings: Settings = request.app.state.settings

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    secret = settings.admin_jwt_secret
    if secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin panel not configured",
        )

    try:
        payload: Dict[str, Any] = jwt.decode(
            credentials.credentials,
            secret.get_secret_value(),
            algorithms=["HS256"],
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload

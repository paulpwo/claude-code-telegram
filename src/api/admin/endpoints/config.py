"""Admin config endpoint.

GET /config — read-only dump of current Settings with all SecretStr values masked.
"""

from typing import Any, Dict

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import SecretStr

from ..auth import jwt_required
from ..deps import get_settings

logger = structlog.get_logger()

router = APIRouter(prefix="/config", tags=["config"])


def _mask_secrets(data: Dict[str, Any]) -> Dict[str, Any]:
    """Replace SecretStr values with '***' in a settings dict."""
    masked: Dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, SecretStr):
            masked[key] = "***"
        else:
            masked[key] = value
    return masked


@router.get("", dependencies=[Depends(jwt_required)])
async def get_config(request: Request) -> Dict[str, Any]:
    """Return a read-only dump of the current application settings.

    All ``SecretStr`` fields are replaced with ``"***"`` — raw secret values
    are never exposed.
    """
    settings = get_settings(request)

    # model_dump() from pydantic-settings returns SecretStr objects as-is;
    # we serialise carefully to avoid leaking secrets.
    raw: Dict[str, Any] = settings.model_dump()
    masked = _mask_secrets(raw)

    # Convert Path objects to strings for JSON serialisation
    for key, value in masked.items():
        from pathlib import Path

        if isinstance(value, Path):
            masked[key] = str(value)

    return {"settings": masked}

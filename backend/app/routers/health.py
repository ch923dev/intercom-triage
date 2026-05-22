"""`GET /health` — startup smoke + cred summary.

Reference: plan.md §4, tasks.md T005.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app import __version__
from app.clients.intercom import IntercomClient
from app.config import AppConfig, get_config
from app.deps import get_intercom
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(
    request: Request,
    config: AppConfig = Depends(get_config),
) -> HealthResponse:
    missing = config.missing_secrets
    intercom: IntercomClient | None = get_intercom(request)
    return HealthResponse(
        status="ok" if not missing else "degraded",
        version=__version__,
        model=config.openrouter_model,
        intercom_configured=config.intercom_configured,
        openrouter_configured=config.openrouter_configured,
        workspace_id=intercom.workspace_id if intercom else None,
        missing_secrets=missing,
    )

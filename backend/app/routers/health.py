"""`GET /health` — startup smoke + cred summary.

Reference: plan.md §4, tasks.md T005.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.config import AppConfig, get_config
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(config: AppConfig = Depends(get_config)) -> HealthResponse:
    missing = config.missing_secrets
    return HealthResponse(
        status="ok" if not missing else "degraded",
        version=__version__,
        model=config.openrouter_model,
        intercom_configured=config.intercom_configured,
        openrouter_configured=config.openrouter_configured,
        missing_secrets=missing,
    )

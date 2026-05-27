"""`GET /stats` — dashboard rollups (roadmap 1.3).

Thin router over `services/stats.py`. Read-only aggregations over the existing
`tickets` table; no migration. The four success metrics (spec §8) are computed
server-side over a trailing window selected by `window_days`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import StatsResponse
from app.services import stats as svc

router = APIRouter(prefix="/stats", tags=["stats"])


@router.get("", response_model=StatsResponse)
async def read_stats(
    window_days: int = Query(default=svc.DEFAULT_WINDOW_DAYS, ge=1, le=365),
    session: AsyncSession = Depends(get_session),
) -> StatsResponse:
    """Category breakdown, volume trend, resolution mix, and time-to-resolve
    distribution over the trailing `window_days` (by ticket `created_at`)."""
    return await svc.get_stats(session, window_days=window_days)

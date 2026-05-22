"""Settings endpoints. Reference: plan.md §4, tasks.md T027."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import FilterSettings
from app.services import settings as svc

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=FilterSettings)
async def read_settings(session: AsyncSession = Depends(get_session)) -> FilterSettings:
    """T027 — the stored singleton filter settings."""
    return await svc.get_settings(session)


@router.put("", response_model=FilterSettings)
async def write_settings(
    body: FilterSettings,
    session: AsyncSession = Depends(get_session),
) -> FilterSettings:
    """T027 — overwrite the singleton settings row."""
    return await svc.update_settings(session, body)

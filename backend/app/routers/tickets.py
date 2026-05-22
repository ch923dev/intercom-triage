"""Ticket endpoints. Reference: plan.md §4, tasks.md T025, T026."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.intercom import IntercomClient
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.db import get_session
from app.deps import get_app_config, get_intercom, get_openrouter
from app.schemas import CategoryUpdate, FilterSettings, OverrideResponse, TicketSchema
from app.services import tickets as svc

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.post("/fetch", response_model=list[TicketSchema])
async def fetch_tickets(
    body: FilterSettings,
    session: AsyncSession = Depends(get_session),
    intercom: IntercomClient | None = Depends(get_intercom),
    openrouter: OpenRouterClient | None = Depends(get_openrouter),
    config: AppConfig = Depends(get_app_config),
) -> list[TicketSchema]:
    """T025 — search Intercom, hydrate, categorize (cache-aware), sort."""
    return await svc.fetch_tickets(
        session=session,
        intercom=intercom,
        openrouter=openrouter,
        config=config,
        filter_settings=body,
    )


@router.patch("/{ticket_id}/category", response_model=OverrideResponse)
async def override_category(
    ticket_id: str,
    body: CategoryUpdate,
    session: AsyncSession = Depends(get_session),
) -> OverrideResponse:
    """T026 — persist a manual category override for a ticket."""
    category_id = await svc.set_override(session, ticket_id, body.category_id)
    return OverrideResponse(category_id=category_id)

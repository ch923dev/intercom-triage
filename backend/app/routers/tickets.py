"""Ticket endpoints. Reference: plan.md §4, tasks.md T025, T026."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.intercom import IntercomClient
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.db import get_session
from app.deps import get_app_config, get_intercom, get_openrouter
from app.schemas import (
    CategoryUpdate,
    FilterSettings,
    HydratedTicket,
    IngestResponse,
    OkResponse,
    OverrideResponse,
    TicketEdit,
    TicketSchema,
)
from app.services import tickets as svc

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("", response_model=list[TicketSchema])
async def list_tickets(session: AsyncSession = Depends(get_session)) -> list[TicketSchema]:
    """Serve the stored board — extension-ingested tickets, no live Intercom
    call. Honors the saved filter settings."""
    return await svc.get_tickets(session)


@router.get("/sync-state", response_model=dict[str, datetime])
async def sync_state(session: AsyncSession = Depends(get_session)) -> dict[str, datetime]:
    """`{ticket_id: updated_at}` for every stored ticket — lets the extension
    skip Intercom detail fetches for conversations it already has unchanged."""
    return await svc.get_sync_state(session)


@router.post("/ingest", response_model=IngestResponse)
async def ingest_tickets(
    body: list[HydratedTicket],
    session: AsyncSession = Depends(get_session),
    openrouter: OpenRouterClient | None = Depends(get_openrouter),
    config: AppConfig = Depends(get_app_config),
) -> IngestResponse:
    """Receive conversations the Chrome extension fetched from the operator's
    Intercom session; categorize (cache-aware) and store them."""
    return await svc.ingest_tickets(
        session=session,
        openrouter=openrouter,
        config=config,
        hydrated=body,
    )


@router.post("/fetch", response_model=list[TicketSchema])
async def fetch_tickets(
    body: FilterSettings,
    session: AsyncSession = Depends(get_session),
    intercom: IntercomClient | None = Depends(get_intercom),
    openrouter: OpenRouterClient | None = Depends(get_openrouter),
    config: AppConfig = Depends(get_app_config),
) -> list[TicketSchema]:
    """Legacy — search Intercom directly via an Access Token (T025). Dormant
    unless a token is configured; the extension-ingest path is primary."""
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


@router.patch("/{ticket_id}", response_model=OkResponse)
async def edit_ticket(
    ticket_id: str,
    body: TicketEdit,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """Operator edits the AI/Intercom title + summary. Edited values are sticky
    across re-syncs; an empty string on either clears the override."""
    await svc.edit_ticket(
        session,
        ticket_id,
        title=body.title,
        summary=body.summary,
    )
    return OkResponse()

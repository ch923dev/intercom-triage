"""Ticket endpoints. Reference: plan.md §4, tasks.md T025, T026."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.db import get_session
from app.deps import get_app_config, get_openrouter
from app.schemas import (
    AIResolveSet,
    BulkCategoryUpdate,
    BulkResult,
    BulkTicketIds,
    CategoryUpdate,
    HydratedTicket,
    IngestResponse,
    OkResponse,
    OverrideResponse,
    ReopenResponse,
    ResolveResponse,
    TicketEdit,
    TicketSchema,
)
from app.services import bulk as bulk_svc
from app.services import resolution as resolution_svc
from app.services import tickets as svc

router = APIRouter(prefix="/tickets", tags=["tickets"])


@router.get("", response_model=list[TicketSchema])
async def list_tickets(
    resolved: bool | None = None,
    session: AsyncSession = Depends(get_session),
) -> list[TicketSchema]:
    """Serve the stored board — extension-ingested tickets, no live Intercom
    call. Honors the saved filter settings.

    Pass ``?resolved=true`` for the Resolved column (shows only resolved
    tickets, ordered by resolved_at desc, ignores include_category_ids).
    Default (omitted or ``?resolved=false``) returns open-only tickets.
    """
    effective = bool(resolved)
    return await svc.get_tickets(session, resolved=effective)


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


# ── Bulk actions (plan §8d, T075-T078) ────────────────────────────────────────
#
# Registered ahead of the `/{ticket_id}/...` routes so that "bulk" wins the
# match against the path parameter — FastAPI dispatches on registration order.


@router.post("/bulk/resolve", response_model=BulkResult)
async def bulk_resolve(
    body: BulkTicketIds,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Mark N tickets manually resolved. Returns per-id ok/failed."""
    return await bulk_svc.bulk_resolve(session, body.ticket_ids)


@router.post("/bulk/reopen", response_model=BulkResult)
async def bulk_reopen(
    body: BulkTicketIds,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Reopen N resolved tickets. Returns per-id ok/failed."""
    return await bulk_svc.bulk_reopen(session, body.ticket_ids)


@router.patch("/bulk/category", response_model=BulkResult)
async def bulk_recategorize(
    body: BulkCategoryUpdate,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Assign one category to N tickets via override rows. 422 if the category
    is unknown or archived; per-id 404s land in `failed[]`."""
    return await bulk_svc.bulk_recategorize(session, body.ticket_ids, body.category_id)


@router.post("/bulk/dismiss-chip", response_model=BulkResult)
async def bulk_dismiss_chip(
    body: BulkTicketIds,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Suppress the resolution chip on N tickets."""
    return await bulk_svc.bulk_dismiss_chip(session, body.ticket_ids)


@router.post("/bulk/non-actionable", response_model=BulkResult)
async def bulk_non_actionable(
    body: BulkTicketIds,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Mark N tickets non-actionable. Already-resolved rows fail with 409."""
    return await bulk_svc.bulk_mark_non_actionable(session, body.ticket_ids)


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


@router.post("/{ticket_id}/resolve", response_model=ResolveResponse)
async def resolve_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> ResolveResponse:
    """Manual resolve. 409 if already resolved, 404 if unknown."""
    out = await resolution_svc.resolve(session, ticket_id)
    return ResolveResponse(resolved_at=out.resolved_at, resolved_source=out.resolved_source)


@router.post("/{ticket_id}/non-actionable", response_model=ResolveResponse)
async def mark_ticket_non_actionable(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> ResolveResponse:
    """Mark a ticket non-actionable. 409 if already resolved, 404 if unknown."""
    out = await resolution_svc.mark_non_actionable(session, ticket_id)
    return ResolveResponse(resolved_at=out.resolved_at, resolved_source=out.resolved_source)


@router.post("/{ticket_id}/reopen", response_model=ReopenResponse)
async def reopen_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> ReopenResponse:
    """Reopen a resolved ticket. 409 if already open, 404 if unknown."""
    await resolution_svc.reopen(session, ticket_id)
    return ReopenResponse()


@router.patch("/{ticket_id}/ai-resolve", response_model=OkResponse)
async def set_ai_resolve(
    ticket_id: str,
    body: AIResolveSet,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """Per-ticket AI-resolve override. `null` inherits settings.ai_resolve_default."""
    await resolution_svc.set_ai_resolve(session, ticket_id, body.enabled)
    return OkResponse()


@router.post("/{ticket_id}/dismiss-chip", response_model=OkResponse)
async def dismiss_chip(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """Suppress the resolution chip until `tickets.updated_at` advances."""
    await resolution_svc.dismiss_chip(session, ticket_id)
    return OkResponse()

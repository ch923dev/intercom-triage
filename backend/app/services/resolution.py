"""Manual ticket-resolution mutations.

Reference: docs/superpowers/specs/2026-05-23-ticket-resolution-design.md §6, §7.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import Ticket
from app.schemas import ResolvedSource
from app.util import naive_utcnow


@dataclass
class ResolveOutcome:
    resolved_at: datetime
    resolved_source: ResolvedSource


async def _get_or_404(session: AsyncSession, ticket_id: str) -> Ticket:
    row = await session.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    return row


async def resolve(session: AsyncSession, ticket_id: str) -> ResolveOutcome:
    """Mark a ticket as manually resolved. 409 if already resolved."""
    row = await _get_or_404(session, ticket_id)
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already resolved")
    now = naive_utcnow()
    row.resolved_at = now
    row.resolved_source = "manual"
    await session.commit()
    metrics.incr("tickets_resolved_total.manual")
    return ResolveOutcome(resolved_at=now, resolved_source="manual")


async def reopen(session: AsyncSession, ticket_id: str) -> None:
    """Clear resolution. 409 if not currently resolved."""
    row = await _get_or_404(session, ticket_id)
    if row.resolved_at is None:
        raise HTTPException(status_code=409, detail="ticket is not resolved")
    row.resolved_at = None
    row.resolved_source = None
    await session.commit()
    metrics.incr("tickets_reopened_total")


async def set_ai_resolve(
    session: AsyncSession,
    ticket_id: str,
    enabled: bool | None,
) -> None:
    """Tri-state per-ticket override. `None` clears the override."""
    row = await _get_or_404(session, ticket_id)
    row.ai_resolve_enabled = enabled
    await session.commit()


async def dismiss_chip(session: AsyncSession, ticket_id: str) -> None:
    """Suppress the resolution chip until `tickets.updated_at` advances."""
    row = await _get_or_404(session, ticket_id)
    row.resolution_chip_dismissed_at = row.updated_at
    await session.commit()

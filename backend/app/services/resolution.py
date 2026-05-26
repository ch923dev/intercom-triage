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


async def get_or_404(session: AsyncSession, ticket_id: str) -> Ticket:
    row = await session.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    return row


# Backwards-compat alias for callers that imported the underscore name.
_get_or_404 = get_or_404


def apply_resolve(row: Ticket) -> ResolveOutcome:
    """Mutate a Ticket row to mark it manually resolved. Does NOT commit.

    Shared by the single-id endpoint and the bulk endpoint — the bulk caller
    issues one commit at the end of the loop instead of N. 409 if the row is
    already resolved.
    """
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already resolved")
    now = naive_utcnow()
    row.resolved_at = now
    row.resolved_source = "manual"
    return ResolveOutcome(resolved_at=now, resolved_source="manual")


def apply_reopen(row: Ticket) -> None:
    """Mutate a Ticket row to clear its resolution. Does NOT commit. 409 if
    the row is not currently resolved."""
    if row.resolved_at is None:
        raise HTTPException(status_code=409, detail="ticket is not resolved")
    row.resolved_at = None
    row.resolved_source = None


def apply_mark_non_actionable(row: Ticket) -> ResolveOutcome:
    """Mutate a Ticket row to mark it non-actionable. Does NOT commit.

    Sub-state of resolved — sets resolved_at + resolved_source='non_actionable'.
    409 if the row is already resolved by any source.
    """
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already resolved")
    now = naive_utcnow()
    row.resolved_at = now
    row.resolved_source = "non_actionable"
    return ResolveOutcome(resolved_at=now, resolved_source="non_actionable")


async def resolve(session: AsyncSession, ticket_id: str) -> ResolveOutcome:
    """Mark a ticket as manually resolved. 409 if already resolved."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_resolve(row)
    await session.commit()
    metrics.incr("tickets_resolved_total.manual")
    return outcome


async def reopen(session: AsyncSession, ticket_id: str) -> None:
    """Clear resolution. 409 if not currently resolved."""
    row = await get_or_404(session, ticket_id)
    apply_reopen(row)
    await session.commit()
    metrics.incr("tickets_reopened_total")


async def mark_non_actionable(session: AsyncSession, ticket_id: str) -> ResolveOutcome:
    """Mark a ticket non-actionable. 409 if already resolved, 404 if unknown."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_mark_non_actionable(row)
    await session.commit()
    metrics.incr("tickets_resolved_total.non_actionable")
    return outcome


async def set_ai_resolve(
    session: AsyncSession,
    ticket_id: str,
    enabled: bool | None,
) -> None:
    """Tri-state per-ticket override. `None` clears the override."""
    row = await get_or_404(session, ticket_id)
    row.ai_resolve_enabled = enabled
    await session.commit()


def apply_dismiss_chip(row: Ticket) -> None:
    """Mutate a Ticket row to suppress its resolution chip until
    `tickets.updated_at` advances. Does NOT commit."""
    row.resolution_chip_dismissed_at = row.updated_at


async def dismiss_chip(session: AsyncSession, ticket_id: str) -> None:
    """Suppress the resolution chip until `tickets.updated_at` advances."""
    row = await get_or_404(session, ticket_id)
    apply_dismiss_chip(row)
    await session.commit()

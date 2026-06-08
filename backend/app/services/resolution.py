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
from app.schemas import ParkedReason, ResolvedSource
from app.util import naive_utcnow


@dataclass
class ResolveOutcome:
    resolved_at: datetime
    resolved_source: ResolvedSource


@dataclass
class ParkOutcome:
    parked_at: datetime
    parked_until: datetime
    parked_reason: ParkedReason
    parked_note: str | None


async def get_or_404(session: AsyncSession, ticket_id: str) -> Ticket:
    row = await session.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    return row


# Backwards-compat alias for callers that imported the underscore name.
_get_or_404 = get_or_404


def apply_resolve(row: Ticket, *, resolved_by: int | None) -> ResolveOutcome:
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
    row.non_actionable_kind = None
    row.resolved_by = resolved_by
    clear_parked(row)
    return ResolveOutcome(resolved_at=now, resolved_source="manual")


def clear_resolution(row: Ticket) -> None:
    """Clear the resolution quartet atomically: the XOR pair
    (resolved_at / resolved_source), the AI-derived non_actionable_kind, and the
    reopen marker (resolution_cleared_at). Does NOT commit. Safe on an
    unresolved row.

    The single owner of the reopen mutation — every reopen path (the button,
    the drag-out override, bulk recategorize) routes through here so a field
    coupled to resolution can never be cleared at some sites and forgotten at
    others. Note tickets_non_actionable_kind_check does NOT catch a reopen that
    nulls resolved_source but leaves a stale kind (its `IS NULL` branch passes),
    so this helper is the structural guarantee, not the DB."""
    row.resolved_at = None
    row.resolved_source = None
    row.non_actionable_kind = None
    row.resolved_by = None
    row.resolution_cleared_at = naive_utcnow()


def apply_reopen(row: Ticket) -> None:
    """Mutate a Ticket row to clear its resolution. Does NOT commit. 409 if
    the row is not currently resolved."""
    if row.resolved_at is None:
        raise HTTPException(status_code=409, detail="ticket is not resolved")
    clear_resolution(row)


def clear_parked(row: Ticket) -> None:
    """Clear the parked trio. Does NOT commit. Safe on an unparked row.
    Called by every resolve path so a parked ticket can never become resolved
    while still parked (tickets_not_parked_and_resolved_check)."""
    row.parked_at = None
    row.parked_until = None
    row.parked_reason = None
    row.parked_note = None


def apply_park(
    row: Ticket, until_at: datetime, reason: ParkedReason, note: str | None = None
) -> ParkOutcome:
    """Mutate a Ticket row into the parked state. Does NOT commit.
    409 if the row is resolved (reopen first) or already parked."""
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is resolved; reopen before parking")
    if row.parked_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already parked")
    now = naive_utcnow()
    row.parked_at = now
    row.parked_until = until_at
    row.parked_reason = reason
    row.parked_note = note
    return ParkOutcome(parked_at=now, parked_until=until_at, parked_reason=reason, parked_note=note)


def apply_unpark(row: Ticket) -> None:
    """Clear the parked state. Does NOT commit. 409 if not parked."""
    if row.parked_at is None:
        raise HTTPException(status_code=409, detail="ticket is not parked")
    clear_parked(row)


def apply_mark_non_actionable(row: Ticket, *, resolved_by: int | None) -> ResolveOutcome:
    """Mutate a Ticket row to mark it non-actionable. Does NOT commit.

    Sub-state of resolved — sets resolved_at + resolved_source='non_actionable'.
    409 if the row is already resolved by any source.
    """
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already resolved")
    now = naive_utcnow()
    row.resolved_at = now
    row.resolved_source = "non_actionable"
    # Manual marks carry no AI kind (D3). Explicit for the CHECK-coupling pattern.
    row.non_actionable_kind = None
    row.resolved_by = resolved_by
    clear_parked(row)
    return ResolveOutcome(resolved_at=now, resolved_source="non_actionable")


async def resolve(
    session: AsyncSession, ticket_id: str, *, resolved_by: int | None
) -> ResolveOutcome:
    """Mark a ticket as manually resolved. 409 if already resolved."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_resolve(row, resolved_by=resolved_by)
    await session.commit()
    metrics.incr("tickets_resolved_total.manual")
    return outcome


async def reopen(session: AsyncSession, ticket_id: str) -> None:
    """Clear resolution. 409 if not currently resolved."""
    row = await get_or_404(session, ticket_id)
    apply_reopen(row)
    await session.commit()
    metrics.incr("tickets_reopened_total")


async def mark_non_actionable(
    session: AsyncSession, ticket_id: str, *, resolved_by: int | None
) -> ResolveOutcome:
    """Mark a ticket non-actionable. 409 if already resolved, 404 if unknown."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_mark_non_actionable(row, resolved_by=resolved_by)
    await session.commit()
    metrics.incr("tickets_resolved_total.non_actionable")
    return outcome


async def park(
    session: AsyncSession,
    ticket_id: str,
    until_at: datetime,
    reason: ParkedReason,
    note: str | None = None,
) -> ParkOutcome:
    """Park a ticket until `until_at`. 409 if resolved or already parked."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_park(row, until_at, reason, note)
    await session.commit()
    metrics.incr("tickets_parked_total")
    return outcome


async def unpark(session: AsyncSession, ticket_id: str) -> None:
    """Unpark a ticket. 409 if not parked."""
    row = await get_or_404(session, ticket_id)
    apply_unpark(row)
    await session.commit()
    metrics.incr("tickets_unparked_total")


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

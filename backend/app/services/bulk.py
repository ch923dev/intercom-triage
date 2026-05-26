"""Bulk-action service. Plan §8d.

Each entry point loops the per-id mutation helper from the matching
single-id service, catches `HTTPException` per id, and returns a
`BulkResult` with the per-id outcome. One commit at the end of the loop
when at least one mutation succeeded.

Why a single commit per batch (not per id):
- Cuts the number of SQLite write transactions from N to 1.
- Per-id failures are still partial — the failed id simply doesn't mutate.
- The session's identity map is unaffected: `session.get(Ticket, id)`
  re-uses already-loaded rows in the same loop.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import Category, Override, Ticket
from app.schemas import BulkFailure, BulkResult
from app.services import followups as followups_svc
from app.services import resolution as resolution_svc
from app.util import naive_utcnow

T = TypeVar("T")


def _dedupe_preserving_order(ids: list[str]) -> list[str]:
    """Deduplicate ticket ids while preserving first-seen order.
    The bulk endpoints accept duplicates in the request and process each
    distinct id exactly once (FR-033)."""
    return list(dict.fromkeys(ids))


async def _run_per_id(
    session: AsyncSession,
    ticket_ids: list[str],
    per_id: Callable[[str], Awaitable[None]],
) -> BulkResult:
    """Loop ids, capture per-id HTTPExceptions, commit once at the end.

    `per_id` is responsible for the row lookup + mutation. It receives the
    ticket id and either returns (success) or raises `HTTPException`
    (recorded in `failed[]`). Unexpected exceptions propagate.
    """
    ok_ids: list[str] = []
    failed: list[BulkFailure] = []
    for tid in _dedupe_preserving_order(ticket_ids):
        try:
            await per_id(tid)
            ok_ids.append(tid)
        except HTTPException as exc:
            failed.append(BulkFailure(id=tid, reason=str(exc.detail)))
    if ok_ids:
        await session.commit()
    return BulkResult(ok_ids=ok_ids, failed=failed)


def _record_outcome(op: str, result: BulkResult) -> None:
    """Tag the batch outcome onto `bulk_actions_total{op, result}` for /metrics.
    `ok` = no failures, `fail` = no successes, `partial` = both."""
    if result.failed and not result.ok_ids:
        outcome = "fail"
    elif result.failed:
        outcome = "partial"
    else:
        outcome = "ok"
    metrics.incr(f"bulk_actions_total.{op}.{outcome}")
    if result.ok_ids:
        metrics.incr(f"bulk_action_ids_total.{op}", len(result.ok_ids))


# ── Resolution ────────────────────────────────────────────────────────────────


async def bulk_resolve(session: AsyncSession, ticket_ids: list[str]) -> BulkResult:
    """Resolve N tickets as `manual`. Already-resolved rows fail with 409."""

    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_resolve(row)
        metrics.incr("tickets_resolved_total.manual")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("resolve", result)
    return result


async def bulk_reopen(session: AsyncSession, ticket_ids: list[str]) -> BulkResult:
    """Reopen N resolved tickets. Open rows fail with 409."""

    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_reopen(row)
        metrics.incr("tickets_reopened_total")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("reopen", result)
    return result


async def bulk_mark_non_actionable(session: AsyncSession, ticket_ids: list[str]) -> BulkResult:
    """Mark N tickets non-actionable. Already-resolved rows fail with 409."""

    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_mark_non_actionable(row)
        metrics.incr("tickets_resolved_total.non_actionable")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("non_actionable", result)
    return result


# ── Recategorize ──────────────────────────────────────────────────────────────


async def bulk_recategorize(
    session: AsyncSession,
    ticket_ids: list[str],
    category_id: int,
) -> BulkResult:
    """Assign one category to N tickets via overrides. Unknown category → 422
    raised up to the endpoint; unknown ticket id → per-id 404 in `failed[]`.

    A resolved ticket in the batch is reopened in the same transaction (the
    "drag out of Resolved" behavior of the single-id path).
    """
    category = await session.get(Category, category_id)
    if category is None or not category.is_active:
        raise HTTPException(status_code=422, detail=f"category {category_id} not found")

    async def per_id(tid: str) -> None:
        ticket = await session.get(Ticket, tid)
        if ticket is None:
            raise HTTPException(status_code=404, detail=f"ticket {tid!r} not found")
        if ticket.resolved_at is not None:
            ticket.resolved_at = None
            ticket.resolved_source = None
            ticket.resolution_cleared_at = naive_utcnow()
        override = await session.get(Override, tid)
        now = naive_utcnow()
        if override is None:
            session.add(Override(ticket_id=tid, category_id=category_id, set_at=now))
        else:
            override.category_id = category_id
            override.set_at = now
        metrics.incr("overrides_set_total")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("recategorize", result)
    return result


async def bulk_dismiss_chip(session: AsyncSession, ticket_ids: list[str]) -> BulkResult:
    """Dismiss the resolution chip on N tickets."""

    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_dismiss_chip(row)

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("dismiss_chip", result)
    return result


# ── Follow-ups ────────────────────────────────────────────────────────────────


async def bulk_set_followup(
    session: AsyncSession,
    ticket_ids: list[str],
    due_at: datetime,
    reason: str | None,
) -> BulkResult:
    """Upsert the same follow-up on N tickets. Per-id failures are unlikely
    here — the followups table is keyed by ticket_id alone (no FK), so unknown
    ids still insert. Mirrored from the single-id path."""

    async def per_id(tid: str) -> None:
        await followups_svc.apply_set_followup(session, tid, due_at, reason)
        metrics.incr("followups_set_total")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("followup_set", result)
    return result


async def bulk_clear_followup(session: AsyncSession, ticket_ids: list[str]) -> BulkResult:
    """Clear follow-ups on N tickets. Idempotent — ids without a follow-up
    row land in `ok_ids` (matches the single-id DELETE contract)."""

    async def per_id(tid: str) -> None:
        deleted = await followups_svc.apply_delete_followup(session, tid)
        if deleted:
            metrics.incr("followups_cleared_total")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("followup_clear", result)
    return result

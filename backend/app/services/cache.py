"""AI cache read/write. Reference: plan.md §7, tasks.md T017.

A cache row is invalid when its TTL has elapsed OR the incoming `signature` is
newer than the stored one (the *customer-visible* thread advanced).

`signature` is conceptually the last-part timestamp of the conversation
(see `services.tickets._content_signature`), not Intercom's `updated_at` — so
internal teammate notes, assignment changes, and snoozes don't invalidate the
cache. The column name `ticket_updated_at` is retained for backward compat with
existing rows; treat it as "content signature".
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.models import AICacheEntry
from app.util import naive_utcnow


async def get_cached(
    session: AsyncSession,
    ticket_id: str,
    signature: datetime,
    ttl_seconds: int,
) -> CategorizationResult | None:
    """Return a valid cached result, or `None` on miss / stale / expired."""
    row = await session.get(AICacheEntry, ticket_id)
    if row is None:
        return None
    # Stale: a new customer-visible message arrived since we cached.
    if signature > row.ticket_updated_at:
        return None
    # Expired: TTL elapsed.
    if naive_utcnow() - row.cached_at > timedelta(seconds=ttl_seconds):
        return None
    return CategorizationResult(
        category_id=row.category_id,
        proposal_id=row.proposal_id,
        summary=row.summary,
        confidence=row.confidence,
        subject=row.subject or "",
        ai_resolution_verdict=row.ai_resolution_verdict,  # type: ignore[arg-type]
        ai_resolution_confidence=row.ai_resolution_confidence,
        ai_resolution_reason=row.ai_resolution_reason,
        non_actionable_kind=row.non_actionable_kind,  # type: ignore[arg-type]
        ai_priority=row.ai_priority or "normal",  # type: ignore[arg-type]
        ai_sentiment=row.ai_sentiment or "neutral",  # type: ignore[arg-type]
        ai_labels=list(row.ai_labels or []),
        # US-044 — without this the record pass sees no verdict on a cache HIT,
        # so a re-synced bug would silently stop being reported.
        bug_severity=row.bug_severity,  # type: ignore[arg-type]
        bug_confidence=row.bug_confidence,
        bug_evidence=row.bug_evidence,
    )


async def set_cached(
    session: AsyncSession,
    ticket_id: str,
    result: CategorizationResult,
    signature: datetime,
) -> None:
    """Upsert a cache row. Exactly one of `category_id` / `proposal_id` is set —
    the DB XOR check rejects anything else."""
    row = await session.get(AICacheEntry, ticket_id)
    now = naive_utcnow()
    if row is None:
        session.add(
            AICacheEntry(
                ticket_id=ticket_id,
                category_id=result.category_id,
                proposal_id=result.proposal_id,
                summary=result.summary,
                subject=result.subject,
                confidence=result.confidence,
                ticket_updated_at=signature,
                cached_at=now,
                ai_resolution_verdict=result.ai_resolution_verdict,
                ai_resolution_confidence=result.ai_resolution_confidence,
                ai_resolution_reason=result.ai_resolution_reason,
                non_actionable_kind=result.non_actionable_kind,
                ai_priority=result.ai_priority,
                ai_sentiment=result.ai_sentiment,
                ai_labels=result.ai_labels,
                bug_severity=result.bug_severity,
                bug_confidence=result.bug_confidence,
                bug_evidence=result.bug_evidence,
            ),
        )
        return
    row.category_id = result.category_id
    row.proposal_id = result.proposal_id
    row.summary = result.summary
    row.subject = result.subject
    row.confidence = result.confidence
    row.ticket_updated_at = signature
    row.cached_at = now
    row.ai_resolution_verdict = result.ai_resolution_verdict
    row.ai_resolution_confidence = result.ai_resolution_confidence
    row.ai_resolution_reason = result.ai_resolution_reason
    row.non_actionable_kind = result.non_actionable_kind
    row.ai_priority = result.ai_priority
    row.ai_sentiment = result.ai_sentiment
    row.ai_labels = result.ai_labels
    # Unconditional assignment, including back to None: a conversation that stops
    # reading as a bug report must clear its verdict, not keep a stale one.
    row.bug_severity = result.bug_severity
    row.bug_confidence = result.bug_confidence
    row.bug_evidence = result.bug_evidence


async def sweep_expired(session: AsyncSession, ttl_seconds: int) -> int:
    """Delete cache rows whose TTL has elapsed.

    Stale-on-signature rows are left alone -- they'll be overwritten the next
    time the ticket is re-categorized, and they're typically the most
    interesting historical data. Only TTL-expired rows are deleted here.

    Returns the count of rows deleted.
    """
    cutoff = naive_utcnow() - timedelta(seconds=ttl_seconds)
    result: CursorResult[tuple[()]] = await session.execute(
        delete(AICacheEntry).where(AICacheEntry.cached_at < cutoff),
    )
    await session.commit()
    return result.rowcount

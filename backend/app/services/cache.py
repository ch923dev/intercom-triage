"""AI cache read/write. Reference: plan.md §7, tasks.md T017.

A cache row is invalid when its TTL has elapsed OR the incoming ticket's
`updated_at` is newer than the cached one (the conversation changed).
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.models import AICacheEntry
from app.util import naive_utcnow


async def get_cached(
    session: AsyncSession,
    ticket_id: str,
    ticket_updated_at: datetime,
    ttl_seconds: int,
) -> CategorizationResult | None:
    """Return a valid cached result, or `None` on miss / stale / expired."""
    row = await session.get(AICacheEntry, ticket_id)
    if row is None:
        return None
    # Stale: the conversation advanced since we cached.
    if ticket_updated_at > row.ticket_updated_at:
        return None
    # Expired: TTL elapsed.
    if naive_utcnow() - row.cached_at > timedelta(seconds=ttl_seconds):
        return None
    return CategorizationResult(
        category_id=row.category_id,
        proposal_id=row.proposal_id,
        summary=row.summary,
        confidence=row.confidence,
    )


async def set_cached(
    session: AsyncSession,
    ticket_id: str,
    result: CategorizationResult,
    ticket_updated_at: datetime,
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
                confidence=result.confidence,
                ticket_updated_at=ticket_updated_at,
                cached_at=now,
            ),
        )
        return
    row.category_id = result.category_id
    row.proposal_id = result.proposal_id
    row.summary = result.summary
    row.confidence = result.confidence
    row.ticket_updated_at = ticket_updated_at
    row.cached_at = now

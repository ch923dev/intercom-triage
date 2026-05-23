"""Follow-up reminders — read/upsert/snooze/fire/delete. Reference: tasks.md T046.

The backend is a passive store for follow-ups (plan §8a): alarm evaluation runs
client-side. Every row is keyed by `ticket_id`, so `PUT` upserts. Timestamps are
stored as naive UTC to match the schema's naive `DateTime` columns.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import Followup
from app.util import naive_utcnow


def _to_naive_utc(value: datetime) -> datetime:
    """Normalize an incoming timestamp to naive UTC for storage."""
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


async def list_followups(session: AsyncSession) -> list[Followup]:
    """Every active follow-up — one row per ticket."""
    return list((await session.scalars(select(Followup))).all())


async def apply_set_followup(
    session: AsyncSession,
    ticket_id: str,
    due_at: datetime,
    reason: str | None,
) -> Followup:
    """Upsert a follow-up row. Does NOT commit. Setting a new `due_at` is a
    fresh reminder — `fired` is reset so the client alarm loop rings again."""
    now = naive_utcnow()
    stored_due = _to_naive_utc(due_at)

    row = await session.get(Followup, ticket_id)
    if row is None:
        row = Followup(
            ticket_id=ticket_id,
            due_at=stored_due,
            reason=reason,
            fired=False,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.due_at = stored_due
        row.reason = reason
        row.fired = False
        row.updated_at = now
    return row


async def set_followup(
    session: AsyncSession,
    ticket_id: str,
    due_at: datetime,
    reason: str | None,
) -> Followup:
    """Upsert + commit. See `apply_set_followup` for the row-level mutation."""
    row = await apply_set_followup(session, ticket_id, due_at, reason)
    await session.commit()
    await session.refresh(row)
    metrics.incr("followups_set_total")
    return row


async def snooze_followup(
    session: AsyncSession,
    ticket_id: str,
    minutes: int,
) -> Followup:
    """Reschedule `due_at` to `now + minutes` and clear `fired` (FR-022)."""
    row = await session.get(Followup, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no follow-up for ticket {ticket_id}")
    now = naive_utcnow()
    row.due_at = now + timedelta(minutes=minutes)
    row.fired = False
    row.updated_at = now
    await session.commit()
    await session.refresh(row)
    metrics.incr("followups_snoozed_total")
    return row


async def mark_fired(session: AsyncSession, ticket_id: str) -> None:
    """Flag the alarm as rung (FR-021) without touching `due_at`."""
    row = await session.get(Followup, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no follow-up for ticket {ticket_id}")
    row.fired = True
    row.updated_at = naive_utcnow()
    await session.commit()
    metrics.incr("followups_fired_total")


async def apply_delete_followup(session: AsyncSession, ticket_id: str) -> bool:
    """Delete a follow-up row. Does NOT commit. Returns True if a row was
    deleted, False if the row was absent (idempotent contract)."""
    row = await session.get(Followup, ticket_id)
    if row is None:
        return False
    await session.delete(row)
    return True


async def delete_followup(session: AsyncSession, ticket_id: str) -> None:
    """Clear a follow-up. Idempotent — deleting an absent row is a no-op."""
    deleted = await apply_delete_followup(session, ticket_id)
    if deleted:
        await session.commit()
        metrics.incr("followups_cleared_total")

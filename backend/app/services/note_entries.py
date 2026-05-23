"""Note entries — append-only per-ticket investigation log.

Spec: docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md

`add_entry` is the only mutation that touches `followups`: when `timer_min`
is set, it upserts the row inside the same transaction. The existing
`followups.apply_set_followup` is reused — it mutates the row but does not
commit, so this service controls atomicity.

Soft-deletes use `deleted_at`; entries are otherwise immutable.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import NoteEntry
from app.services import followups as followups_svc
from app.util import naive_utcnow


async def list_all(session: AsyncSession) -> list[NoteEntry]:
    """Every non-deleted entry, asc by created_at. Used to seed the frontend store."""
    stmt = (
        select(NoteEntry)
        .where(NoteEntry.deleted_at.is_(None))
        .order_by(NoteEntry.created_at.asc(), NoteEntry.id.asc())
    )
    return list((await session.scalars(stmt)).all())


async def list_for_ticket(session: AsyncSession, ticket_id: str) -> list[NoteEntry]:
    """Non-deleted entries for one ticket, asc by created_at."""
    stmt = (
        select(NoteEntry)
        .where(NoteEntry.ticket_id == ticket_id, NoteEntry.deleted_at.is_(None))
        .order_by(NoteEntry.created_at.asc(), NoteEntry.id.asc())
    )
    return list((await session.scalars(stmt)).all())


async def add_entry(
    session: AsyncSession,
    ticket_id: str,
    body: str,
    timer_min: int | None = None,
    reason: str | None = None,
) -> NoteEntry:
    """Insert a new entry. When `timer_min` is set, upsert the ticket's
    `followups` row inside the same transaction. Latest timer entry wins."""
    entry = NoteEntry(
        ticket_id=ticket_id,
        body=body,
        timer_min=timer_min,
        reason=reason,
        created_at=naive_utcnow(),
    )
    session.add(entry)

    if timer_min is not None:
        due_at = naive_utcnow() + timedelta(minutes=timer_min)
        await followups_svc.apply_set_followup(session, ticket_id, due_at, reason)

    await session.commit()
    await session.refresh(entry)
    metrics.incr("note_entries_added_total")
    if timer_min is not None:
        metrics.incr("note_entries_added_with_timer_total")
    return entry


async def soft_delete(session: AsyncSession, entry_id: int) -> NoteEntry:
    """Stamp `deleted_at`. Idempotent on a row already deleted."""
    row = await session.get(NoteEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no note entry {entry_id}")
    if row.deleted_at is None:
        row.deleted_at = naive_utcnow()
        await session.commit()
        await session.refresh(row)
        metrics.incr("note_entries_deleted_total")
    return row

"""Per-ticket next-step notes — read/upsert/delete. Reference: tasks.md T047.

One row per ticket, keyed by `ticket_id`. An empty (or whitespace-only) body
deletes the row, so every stored note is non-empty by invariant (FR-023).
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import TicketNote
from app.util import naive_utcnow


async def list_notes(session: AsyncSession) -> list[TicketNote]:
    """Every stored note — all non-empty by invariant."""
    return list((await session.scalars(select(TicketNote))).all())


async def set_note(
    session: AsyncSession,
    ticket_id: str,
    body: str,
) -> TicketNote | None:
    """Upsert a note. An empty body deletes the row and returns `None`."""
    row = await session.get(TicketNote, ticket_id)

    if not body.strip():
        if row is not None:
            await session.delete(row)
            await session.commit()
            metrics.incr("notes_cleared_total")
        return None

    now = naive_utcnow()
    if row is None:
        row = TicketNote(ticket_id=ticket_id, body=body, updated_at=now)
        session.add(row)
    else:
        row.body = body
        row.updated_at = now
    await session.commit()
    await session.refresh(row)
    metrics.incr("notes_set_total")
    return row

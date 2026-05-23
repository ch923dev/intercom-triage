"""Note-entries endpoints — time-tabled notes spec.

Spec: docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import NoteEntryCreate, NoteEntryDeleted, NoteEntryRead
from app.services import note_entries as svc

router = APIRouter(prefix="/notes/entries", tags=["notes"])


@router.get("", response_model=list[NoteEntryRead])
async def list_entries(session: AsyncSession = Depends(get_session)) -> list[NoteEntryRead]:
    """Every non-deleted entry, asc by created_at. Used to seed the store."""
    rows = await svc.list_all(session)
    return [NoteEntryRead.model_validate(row) for row in rows]


@router.get("/{ticket_id}", response_model=list[NoteEntryRead])
async def list_entries_for_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[NoteEntryRead]:
    """Non-deleted entries for one ticket, asc by created_at."""
    rows = await svc.list_for_ticket(session, ticket_id)
    return [NoteEntryRead.model_validate(row) for row in rows]


@router.post("", response_model=NoteEntryRead)
async def create_entry(
    body: NoteEntryCreate,
    session: AsyncSession = Depends(get_session),
) -> NoteEntryRead:
    """Insert a new entry. When `timer_min` set, upserts the ticket's
    follow-up row in the same transaction (latest timer entry wins)."""
    row = await svc.add_entry(
        session,
        ticket_id=body.ticket_id,
        body=body.body,
        timer_min=body.timer_min,
        reason=body.reason,
    )
    return NoteEntryRead.model_validate(row)


@router.delete("/{entry_id}", response_model=NoteEntryDeleted)
async def delete_entry(
    entry_id: int,
    session: AsyncSession = Depends(get_session),
) -> NoteEntryDeleted:
    """Soft-delete (sets `deleted_at`). Idempotent on a row already deleted."""
    row = await svc.soft_delete(session, entry_id)
    return NoteEntryDeleted(id=row.id)

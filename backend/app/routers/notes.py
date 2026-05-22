"""Notes endpoints. Reference: plan.md §4 §8a, tasks.md T047."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import NoteDeletedResponse, TicketNoteRead, TicketNoteSet
from app.services import notes as svc

router = APIRouter(prefix="/notes", tags=["notes"])


@router.get("", response_model=list[TicketNoteRead])
async def list_notes(session: AsyncSession = Depends(get_session)) -> list[TicketNoteRead]:
    """T047 — every stored note (all non-empty)."""
    rows = await svc.list_notes(session)
    return [TicketNoteRead.model_validate(row) for row in rows]


@router.put("/{ticket_id}", response_model=TicketNoteRead | NoteDeletedResponse)
async def set_note(
    ticket_id: str,
    body: TicketNoteSet,
    session: AsyncSession = Depends(get_session),
) -> TicketNoteRead | NoteDeletedResponse:
    """T047 — upsert a note. An empty body deletes the row."""
    row = await svc.set_note(session, ticket_id, body.body)
    if row is None:
        return NoteDeletedResponse()
    return TicketNoteRead.model_validate(row)

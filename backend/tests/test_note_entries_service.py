"""Service-level tests for note_entries (spec: time-tabled notes)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteEntry


@pytest.mark.asyncio
async def test_note_entry_model_persists(session: AsyncSession) -> None:
    """Insert a note_entry row + read it back."""
    row = NoteEntry(ticket_id="T1", body="investigating", timer_min=15, reason="bug")
    session.add(row)
    await session.commit()

    found = (await session.scalars(select(NoteEntry).where(NoteEntry.ticket_id == "T1"))).one()
    assert found.body == "investigating"
    assert found.timer_min == 15
    assert found.reason == "bug"
    assert found.deleted_at is None
    assert found.created_at is not None

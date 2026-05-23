"""Service-level tests for note_attachments (spec: note attachments)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteAttachment


@pytest.mark.asyncio
async def test_note_attachment_model_persists(session: AsyncSession) -> None:
    """Insert a note_attachments row + read it back."""
    row = NoteAttachment(
        owner_kind="ticket",
        owner_id="T1",
        ticket_id="T1",
        filename="trace.csv",
        mime="text/csv",
        size_bytes=42,
        sha256="a" * 64,
        stored_path="aa/aaaa.csv",
    )
    session.add(row)
    await session.commit()

    found = (
        await session.scalars(select(NoteAttachment).where(NoteAttachment.id == row.id))
    ).one()
    assert found.owner_kind == "ticket"
    assert found.owner_id == "T1"
    assert found.ticket_id == "T1"
    assert found.filename == "trace.csv"
    assert found.mime == "text/csv"
    assert found.size_bytes == 42
    assert found.sha256 == "a" * 64
    assert found.stored_path == "aa/aaaa.csv"
    assert found.deleted_at is None
    assert found.created_at is not None

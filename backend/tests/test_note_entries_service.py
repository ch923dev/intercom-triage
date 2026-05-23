"""Service-level tests for note_entries (spec: time-tabled notes)."""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Followup, NoteEntry
from app.services import note_entries as svc
from app.util import naive_utcnow


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


@pytest.mark.asyncio
async def test_add_entry_without_timer_does_not_create_followup(session: AsyncSession) -> None:
    entry = await svc.add_entry(session, ticket_id="T1", body="note only")
    assert entry.id is not None
    assert entry.timer_min is None

    fu = await session.get(Followup, "T1")
    assert fu is None


@pytest.mark.asyncio
async def test_add_entry_with_timer_upserts_followup(session: AsyncSession) -> None:
    before = naive_utcnow()
    entry = await svc.add_entry(
        session,
        ticket_id="T1",
        body="investigating",
        timer_min=15,
        reason="check retry policy",
    )
    assert entry.timer_min == 15

    fu = await session.get(Followup, "T1")
    assert fu is not None
    assert fu.reason == "check retry policy"
    assert fu.fired is False
    expected_due = before + timedelta(minutes=15)
    assert abs((fu.due_at - expected_due).total_seconds()) < 5


@pytest.mark.asyncio
async def test_new_timer_entry_overwrites_prior_followup(session: AsyncSession) -> None:
    await svc.add_entry(session, ticket_id="T1", body="first", timer_min=5, reason="r1")
    fu_first = await session.get(Followup, "T1")
    assert fu_first is not None
    first_due = fu_first.due_at

    await svc.add_entry(session, ticket_id="T1", body="second", timer_min=60, reason="r2")
    await session.refresh(fu_first)
    assert fu_first.reason == "r2"
    assert fu_first.due_at > first_due


@pytest.mark.asyncio
async def test_list_for_ticket_returns_asc_by_created_at(session: AsyncSession) -> None:
    await svc.add_entry(session, ticket_id="T1", body="a")
    await svc.add_entry(session, ticket_id="T1", body="b")
    await svc.add_entry(session, ticket_id="T2", body="x")

    rows = await svc.list_for_ticket(session, "T1")
    assert [r.body for r in rows] == ["a", "b"]


@pytest.mark.asyncio
async def test_list_all_excludes_soft_deleted(session: AsyncSession) -> None:
    e1 = await svc.add_entry(session, ticket_id="T1", body="kept")
    e2 = await svc.add_entry(session, ticket_id="T1", body="gone")
    await svc.soft_delete(session, e2.id)

    rows = await svc.list_all(session)
    assert {r.id for r in rows} == {e1.id}


@pytest.mark.asyncio
async def test_soft_delete_missing_id_raises_404(session: AsyncSession) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.soft_delete(session, 99999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_entry_rejects_empty_body(session: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await svc.add_entry(session, ticket_id="T1", body="")

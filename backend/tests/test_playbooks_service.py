"""Playbooks service tests. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Playbook


@pytest.mark.asyncio
async def test_playbook_row_round_trips(session: AsyncSession) -> None:
    session.add(
        Playbook(
            category_id=1,
            label="double-charge after upgrade",
            body="1. Confirm the duplicate invoice. 2. Issue refund. 3. Reply.",
        )
    )
    await session.commit()
    rows = list((await session.scalars(select(Playbook))).all())
    assert len(rows) == 1
    assert rows[0].label == "double-charge after upgrade"
    assert rows[0].archived_at is None
    assert rows[0].source_ticket_id is None


from app.services import playbooks as svc


@pytest.mark.asyncio
async def test_create_then_list_for_category(session: AsyncSession) -> None:
    a = await svc.create(session, category_id=1, label="issue A", body="steps A")
    await svc.create(session, category_id=1, label="issue B", body="steps B")
    await svc.create(session, category_id=2, label="other", body="steps C")

    rows = await svc.list_for_category(session, 1)
    labels = [r.label for r in rows]
    assert labels == ["issue A", "issue B"]
    assert a.id is not None


@pytest.mark.asyncio
async def test_list_for_category_hides_archived_by_default(session: AsyncSession) -> None:
    p = await svc.create(session, category_id=1, label="issue A", body="steps A")
    await svc.archive(session, p.id)

    assert await svc.list_for_category(session, 1) == []
    archived = await svc.list_for_category(session, 1, include_archived=True)
    assert [r.label for r in archived] == ["issue A"]


from datetime import timedelta

from app.models import Override, Ticket
from app.util import naive_utcnow


def _make_ticket(ticket_id: str, category_id: int, updated_at) -> Ticket:
    return Ticket(
        id=ticket_id,
        title="t",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=updated_at,
        updated_at=updated_at,
        category_id=category_id,
        summary="",
        ai_confidence=0.0,
    )


@pytest.mark.asyncio
async def test_list_for_ticket_uses_ai_category(session: AsyncSession) -> None:
    now = naive_utcnow()
    session.add(_make_ticket("TCK1", category_id=1, updated_at=now))
    await session.commit()
    await svc.create(session, category_id=1, label="ai-cat", body="steps")

    rows = await svc.list_for_ticket(session, "TCK1")
    assert [r.label for r in rows] == ["ai-cat"]


@pytest.mark.asyncio
async def test_list_for_ticket_override_beats_ai(session: AsyncSession) -> None:
    now = naive_utcnow()
    session.add(_make_ticket("TCK2", category_id=1, updated_at=now))
    # Override set AFTER the ticket's updated_at → override wins.
    session.add(Override(ticket_id="TCK2", category_id=2, set_at=now + timedelta(minutes=5)))
    await session.commit()
    await svc.create(session, category_id=1, label="ai-cat", body="x")
    await svc.create(session, category_id=2, label="override-cat", body="y")

    rows = await svc.list_for_ticket(session, "TCK2")
    assert [r.label for r in rows] == ["override-cat"]


@pytest.mark.asyncio
async def test_list_for_ticket_404_when_missing(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await svc.list_for_ticket(session, "nope")
    assert exc.value.status_code == 404

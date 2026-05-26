"""Playbooks service tests. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.models import NoteEntry, Override, Playbook, Ticket, TicketNote
from app.schemas import HydratedTicket, TicketAuthorSchema
from app.services import playbooks as svc
from app.services.tickets import ingest_tickets
from app.util import naive_utcnow


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


@pytest.mark.asyncio
async def test_update_changes_fields_and_bumps_updated_at(session: AsyncSession) -> None:
    p = await svc.create(session, category_id=1, label="old", body="old body")
    before = p.updated_at
    updated = await svc.update(session, p.id, label="new", body=None)
    assert updated.label == "new"
    assert updated.body == "old body"
    assert updated.updated_at >= before


@pytest.mark.asyncio
async def test_restore_clears_archived_at(session: AsyncSession) -> None:
    p = await svc.create(session, category_id=1, label="x", body="y")
    await svc.archive(session, p.id)
    restored = await svc.restore(session, p.id)
    assert restored.archived_at is None
    assert [r.label for r in await svc.list_for_category(session, 1)] == ["x"]


@pytest.mark.asyncio
async def test_list_all_spans_categories(session: AsyncSession) -> None:
    await svc.create(session, category_id=1, label="a", body="1")
    await svc.create(session, category_id=2, label="b", body="2")
    rows = await svc.list_all(session)
    assert {r.label for r in rows} == {"a", "b"}


@pytest.mark.asyncio
async def test_update_404_when_missing(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await svc.update(session, 999, label="x", body=None)
    assert exc.value.status_code == 404


def _ticket_with_notes() -> Ticket:
    now = naive_utcnow()
    t = _make_ticket("TDRAFT", category_id=1, updated_at=now)
    t.parts = [
        {
            "author": {"type": "user", "name": "Cust"},
            "body": "I was double charged",
            "created_at": "2026-05-26T10:00:00Z",
            "is_admin": False,
        },
        {
            "author": {"type": "admin", "name": "Op"},
            "body": "Refund issued",
            "created_at": "2026-05-26T10:05:00Z",
            "is_admin": True,
        },
    ]
    t.internal_notes = [
        {
            "author": {"type": "admin", "name": "Op"},
            "body": "SECRET_INTERNAL_FLAG",
            "created_at": "2026-05-26T10:06:00Z",
            "is_admin": True,
        },
    ]
    return t


def test_build_draft_messages_excludes_internal_notes() -> None:
    ticket = _ticket_with_notes()
    entries = [NoteEntry(id=1, ticket_id="TDRAFT", body="checked Stripe dashboard")]
    note = TicketNote(ticket_id="TDRAFT", body="customer on Pro plan")

    messages = svc.build_draft_messages(ticket, entries, note)
    blob = "\n".join(m["content"] for m in messages)

    assert "double charged" in blob
    assert "checked Stripe dashboard" in blob
    assert "customer on Pro plan" in blob
    assert "SECRET_INTERNAL_FLAG" not in blob  # invariant #4


class _FakeClient:
    def __init__(self, reply: str) -> None:
        self.reply = reply

    async def complete(self, *, model: str, messages: list[dict[str, str]], ticket_id: str) -> str:
        return self.reply


@pytest.mark.asyncio
async def test_draft_from_ticket_returns_text(session: AsyncSession) -> None:
    session.add(_ticket_with_notes())
    await session.commit()
    text = await svc.draft_from_ticket(
        session, "TDRAFT", client=_FakeClient("  1. Refund. 2. Reply.  "), model="m"
    )
    assert text == "1. Refund. 2. Reply."


@pytest.mark.asyncio
async def test_draft_from_ticket_503_without_client(session: AsyncSession) -> None:
    session.add(_ticket_with_notes())
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await svc.draft_from_ticket(session, "TDRAFT", client=None, model="m")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_draft_from_ticket_404_when_missing(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await svc.draft_from_ticket(session, "nope", client=_FakeClient("x"), model="m")
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_playbook_survives_ticket_resync(
    session: AsyncSession,
    test_config: AppConfig,
) -> None:
    """Invariant #13 — a full ingest / re-sync must not touch playbook rows."""
    saved = await svc.create(session, category_id=1, label="keepme", body="steps")

    hydrated = HydratedTicket(
        id="TCKRESYNC",
        title="Refund please",
        state="open",
        priority=None,
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        author=TicketAuthorSchema(type="user", name="Cust"),
        url=None,
        parts=[],
        internal_notes=[],
    )
    # No AI configured → fallback categorization; this is a real ingest pass.
    await ingest_tickets(
        session=session, openrouter=None, config=test_config, hydrated=[hydrated]
    )

    refreshed = await session.get(Playbook, saved.id)
    assert refreshed is not None
    assert refreshed.body == "steps"
    assert refreshed.archived_at is None
    assert [r.label for r in await svc.list_for_category(session, 1)] == ["keepme"]

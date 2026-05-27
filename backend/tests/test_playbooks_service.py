"""Playbooks service tests. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embeddings
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


# ── RAG draft reply (roadmap 2.6) ─────────────────────────────────────────────


class _CapturingClient:
    """Records the messages it was asked to complete so tests can assert what
    reached the prompt. Accepts `response_format` (the RAG drafter passes it)."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.last_messages: list[dict[str, str]] = []
        self.last_response_format: dict[str, str] | None = None

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        ticket_id: str,
        response_format: dict[str, str] | None = None,
    ) -> str:
        self.last_messages = messages
        self.last_response_format = response_format
        return self.reply


def _resolved_ticket(ticket_id: str, *, part_body: str, internal_note: str | None = None) -> Ticket:
    now = naive_utcnow()
    t = _make_ticket(ticket_id, category_id=1, updated_at=now)
    t.parts = [
        {
            "author": {"type": "user", "name": "Cust"},
            "body": part_body,
            "created_at": "2026-05-26T10:00:00Z",
            "is_admin": False,
        }
    ]
    if internal_note is not None:
        t.internal_notes = [
            {
                "author": {"type": "admin", "name": "Op"},
                "body": internal_note,
                "created_at": "2026-05-26T10:06:00Z",
                "is_admin": True,
            }
        ]
    t.resolved_at = now
    t.resolved_source = "manual"
    return t


async def _store_embedding(session: AsyncSession, ticket: Ticket) -> None:
    """Embed a ticket's customer-visible text into the vec store (test helper).

    Mirrors what ingest does, using the deterministic fake encoder so identical
    text yields ~0 distance."""
    text = svc._query_text(ticket)
    vector = embeddings.embed_text(text)
    await embeddings.store_embedding(session, ticket.id, vector)


@pytest.mark.asyncio
async def test_draft_reply_grounds_in_resolved_precedent(session: AsyncSession) -> None:
    """The nearest RESOLVED ticket's customer-visible parts reach the prompt and
    its id is reported as grounding."""
    past = _resolved_ticket("TPAST", part_body="refund the duplicate charge from Stripe")
    current = _make_ticket("TCUR", category_id=1, updated_at=naive_utcnow())
    current.parts = [
        {
            "author": {"type": "user", "name": "Cust"},
            "body": "refund the duplicate charge from Stripe",
            "created_at": "2026-05-26T11:00:00Z",
            "is_admin": False,
        }
    ]
    session.add_all([past, current])
    await session.commit()
    await _store_embedding(session, past)
    await session.commit()

    client = _CapturingClient("Sorry about that — see TPAST.")
    draft = await svc.draft_reply_from_ticket(session, "TCUR", client=client, model="m")

    assert draft.grounding_ticket_ids == ["TPAST"]
    blob = "\n".join(m["content"] for m in client.last_messages)
    assert "refund the duplicate charge from Stripe" in blob
    assert "TPAST" in blob  # precedent block is labelled with the ticket id
    # The RAG drafter asks for free-text output, not a JSON object.
    assert client.last_response_format == {"type": "text"}


@pytest.mark.asyncio
async def test_draft_reply_excludes_internal_notes_of_precedents(session: AsyncSession) -> None:
    """Invariant #4: a resolved precedent's internal_notes must NEVER be
    reachable in the draft-prompt messages."""
    sentinel = "SENTINEL_INTERNAL_NOTE_DO_NOT_LEAK"
    past = _resolved_ticket(
        "TPAST",
        part_body="my export to CSV is missing fields",
        internal_note=sentinel,
    )
    current = _make_ticket("TCUR", category_id=1, updated_at=naive_utcnow())
    current.parts = [
        {
            "author": {"type": "user", "name": "Cust"},
            "body": "my export to CSV is missing fields",
            "created_at": "2026-05-26T11:00:00Z",
            "is_admin": False,
        }
    ]
    session.add_all([past, current])
    await session.commit()
    await _store_embedding(session, past)
    await session.commit()

    client = _CapturingClient("Here is how to fix the export.")
    draft = await svc.draft_reply_from_ticket(session, "TCUR", client=client, model="m")

    # The precedent WAS retrieved (proves the path is exercised)...
    assert draft.grounding_ticket_ids == ["TPAST"]
    # ...but the sentinel never reached the prompt OR the returned body.
    blob = "\n".join(m["content"] for m in client.last_messages)
    assert sentinel not in blob
    assert sentinel not in draft.body


@pytest.mark.asyncio
async def test_draft_reply_excludes_unresolved_neighbours(session: AsyncSession) -> None:
    """Only RESOLVED tickets are precedent — an unresolved nearest neighbour is
    filtered out even though it embeds identically."""
    body = "password reset email never arrives"
    unresolved = _make_ticket("TOPEN", category_id=1, updated_at=naive_utcnow())
    unresolved.parts = [
        {
            "author": {"type": "user", "name": "Cust"},
            "body": body,
            "created_at": "2026-05-26T10:00:00Z",
            "is_admin": False,
        }
    ]
    current = _make_ticket("TCUR", category_id=1, updated_at=naive_utcnow())
    current.parts = [
        {
            "author": {"type": "user", "name": "Cust"},
            "body": body,
            "created_at": "2026-05-26T11:00:00Z",
            "is_admin": False,
        }
    ]
    session.add_all([unresolved, current])
    await session.commit()
    await _store_embedding(session, unresolved)
    await session.commit()

    client = _CapturingClient("reply")
    draft = await svc.draft_reply_from_ticket(session, "TCUR", client=client, model="m")
    assert draft.grounding_ticket_ids == []


@pytest.mark.asyncio
async def test_draft_reply_grounds_in_effective_category_playbooks(session: AsyncSession) -> None:
    """Invariant #13: the draft sees playbooks for the ticket's effective
    category (override beats AI)."""
    now = naive_utcnow()
    current = _make_ticket("TCUR", category_id=1, updated_at=now)
    current.parts = [
        {
            "author": {"type": "user", "name": "Cust"},
            "body": "billing question",
            "created_at": "2026-05-26T11:00:00Z",
            "is_admin": False,
        }
    ]
    session.add(current)
    session.add(Override(ticket_id="TCUR", category_id=2, set_at=now + timedelta(minutes=5)))
    await session.commit()
    await svc.create(session, category_id=1, label="ai-cat-playbook", body="ai steps")
    pb = await svc.create(session, category_id=2, label="override-playbook", body="override steps")

    client = _CapturingClient("reply")
    draft = await svc.draft_reply_from_ticket(session, "TCUR", client=client, model="m")

    assert draft.playbook_ids == [pb.id]
    blob = "\n".join(m["content"] for m in client.last_messages)
    assert "override-playbook" in blob
    assert "ai-cat-playbook" not in blob


@pytest.mark.asyncio
async def test_draft_reply_excludes_self(session: AsyncSession) -> None:
    """A ticket must not ground itself even if its own embedding is the nearest
    match."""
    current = _resolved_ticket("TSELF", part_body="self-similar text")
    session.add(current)
    await session.commit()
    await _store_embedding(session, current)
    await session.commit()

    client = _CapturingClient("reply")
    draft = await svc.draft_reply_from_ticket(session, "TSELF", client=client, model="m")
    assert "TSELF" not in draft.grounding_ticket_ids


@pytest.mark.asyncio
async def test_draft_reply_503_without_client(session: AsyncSession) -> None:
    session.add(_make_ticket("TCUR", category_id=1, updated_at=naive_utcnow()))
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await svc.draft_reply_from_ticket(session, "TCUR", client=None, model="m")
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_draft_reply_404_when_missing(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await svc.draft_reply_from_ticket(session, "nope", client=_CapturingClient("x"), model="m")
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
    await ingest_tickets(session=session, openrouter=None, config=test_config, hydrated=[hydrated])

    refreshed = await session.get(Playbook, saved.id)
    assert refreshed is not None
    assert refreshed.body == "steps"
    assert refreshed.archived_at is None
    assert [r.label for r in await svc.list_for_category(session, 1)] == ["keepme"]

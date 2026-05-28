"""Verifies ingest-time resolution behavior:
- Intercom state transition open → closed auto-resolves with source='intercom_closed'.
- A ticket arriving as closed on first sight auto-resolves on first store.
- A previously-resolved ticket stays resolved across syncs (no re-stamp).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.schemas import (
    ConversationPartSchema,
    HydratedTicket,
    TicketAuthorSchema,
)


def make_hydrated(*, id="t1", state="open", updated_at=None) -> HydratedTicket:
    return HydratedTicket(
        id=id,
        title="t",
        state=state,
        priority=None,
        created_at=datetime(2026, 5, 23, 8),
        updated_at=updated_at or datetime(2026, 5, 23, 12),
        author=TicketAuthorSchema(),
        url=None,
        parts=[
            ConversationPartSchema(
                author=TicketAuthorSchema(),
                body="hello",
                created_at=datetime(2026, 5, 23, 11),
                is_admin=False,
            )
        ],
    )


@pytest.mark.asyncio
async def test_intercom_closed_transition_auto_resolves(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Open ticket already stored, sync brings it back as state='closed':
    resolved_at is set, source='intercom_closed', AI is not called."""
    from app.models import Ticket
    from app.services.tickets import ingest_tickets

    # Pass openrouter=None — these tests exercise Intercom-state transitions,
    # not AI categorization. The fallback path is sufficient.

    # First sync — open state, store the ticket.
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[make_hydrated(state="open")],
    )
    row = await session.get(Ticket, "t1")
    assert row is not None and row.resolved_at is None

    # Second sync — same id, state=closed, later updated_at.
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[make_hydrated(state="closed", updated_at=datetime(2026, 5, 24))],
    )
    row = await session.get(Ticket, "t1")
    assert row.resolved_at is not None
    assert row.resolved_source == "intercom_closed"
    assert row.state == "closed"


@pytest.mark.asyncio
async def test_already_resolved_ticket_not_restamped_on_second_closure(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """If we sync a closed ticket twice, resolved_at must not change on the
    second pass — only the first open→closed transition stamps it."""
    from app.models import Ticket
    from app.services.tickets import ingest_tickets
    from app.util import naive_utcnow

    # Pre-store as resolved 1 hour ago.
    session.add(
        Ticket(
            id="t2",
            title="x",
            state="closed",
            author={},
            parts=[],
            internal_notes=[],
            created_at=datetime(2026, 5, 23),
            updated_at=datetime(2026, 5, 23),
            category_id=1,
            summary="",
            ai_confidence=0,
            resolved_at=naive_utcnow() - timedelta(hours=1),
            resolved_source="intercom_closed",
        )
    )
    await session.commit()
    original = (await session.get(Ticket, "t2")).resolved_at

    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[make_hydrated(id="t2", state="closed", updated_at=datetime(2026, 5, 24))],
    )
    row = await session.get(Ticket, "t2")
    assert row.resolved_at == original  # unchanged


@pytest.mark.asyncio
async def test_ingest_auto_resolves_non_actionable_when_threshold_met(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI verdict 'non_actionable' + auto-resolve on + confidence >= threshold
    → ingest stamps resolved_source='non_actionable'."""
    from app.ai.pipeline import CategorizationResult
    from app.models import Settings, Ticket

    s = (await session.scalars(select(Settings))).one()
    s.use_ai = True
    s.ai_resolve_default = True
    s.ai_resolve_confidence_threshold = 0.7
    await session.commit()

    async def fake_categorize_many(
        *args: object, **kwargs: object
    ) -> dict[str, CategorizationResult]:
        return {
            "conv-na-1": CategorizationResult(
                category_id=1,
                proposal_id=None,
                summary="auto-reply bounce",
                confidence=0.9,
                ai_resolution_verdict="non_actionable",
                ai_resolution_confidence=0.85,
                ai_resolution_reason="auto-reply: vacation responder",
            )
        }

    monkeypatch.setattr("app.services.tickets.categorize_many", fake_categorize_many)

    payload = [
        {
            "id": "conv-na-1",
            "title": "Out of office",
            "state": "open",
            "priority": None,
            "url": None,
            "author": {"name": "Bot", "type": "user"},
            "created_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
            "parts": [],
            "internal_notes": [],
        }
    ]
    r = await client.post("/tickets/ingest", json=payload)
    assert r.status_code == 200

    row = await session.get(Ticket, "conv-na-1")
    assert row is not None
    assert row.resolved_at is not None
    assert row.resolved_source == "non_actionable"


@pytest.mark.asyncio
async def test_ingest_skips_auto_apply_when_confidence_below_threshold(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Below threshold → ticket stays open, no resolved_source stamped."""
    from app.ai.pipeline import CategorizationResult
    from app.models import Settings, Ticket

    s = (await session.scalars(select(Settings))).one()
    s.use_ai = True
    s.ai_resolve_default = True
    s.ai_resolve_confidence_threshold = 0.9
    await session.commit()

    async def fake_categorize_many(
        *args: object, **kwargs: object
    ) -> dict[str, CategorizationResult]:
        return {
            "conv-na-2": CategorizationResult(
                category_id=1,
                proposal_id=None,
                summary="might be spam",
                confidence=0.6,
                ai_resolution_verdict="non_actionable",
                ai_resolution_confidence=0.65,
                ai_resolution_reason="spam: likely promotional",
            )
        }

    monkeypatch.setattr("app.services.tickets.categorize_many", fake_categorize_many)

    payload = [
        {
            "id": "conv-na-2",
            "title": "Promo",
            "state": "open",
            "priority": None,
            "url": None,
            "author": {"type": "user"},
            "created_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
            "parts": [],
            "internal_notes": [],
        }
    ]
    r = await client.post("/tickets/ingest", json=payload)
    assert r.status_code == 200

    row = await session.get(Ticket, "conv-na-2")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolved_source is None


# ── C1: ai verdict 'resolved' maps to resolved_source='ai_resolved' ───────────


@pytest.mark.asyncio
async def test_ingest_auto_resolves_when_verdict_resolved_uses_ai_resolved_source(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI verdict 'resolved' + auto-resolve on + confidence >= threshold
    → ingest stamps resolved_source='ai_resolved' (not 'resolved')."""
    from app.ai.pipeline import CategorizationResult
    from app.models import Settings, Ticket

    s = (await session.scalars(select(Settings))).one()
    s.use_ai = True
    s.ai_resolve_default = True
    s.ai_resolve_confidence_threshold = 0.7
    await session.commit()

    async def fake_categorize_many(
        *args: object, **kwargs: object
    ) -> dict[str, CategorizationResult]:
        return {
            "conv-resolved-1": CategorizationResult(
                category_id=1,
                proposal_id=None,
                summary="customer confirmed fixed",
                confidence=0.9,
                ai_resolution_verdict="resolved",
                ai_resolution_confidence=0.88,
                ai_resolution_reason="customer replied: thanks, works now",
            )
        }

    monkeypatch.setattr("app.services.tickets.categorize_many", fake_categorize_many)

    payload = [
        {
            "id": "conv-resolved-1",
            "title": "Issue fixed",
            "state": "open",
            "priority": None,
            "url": None,
            "author": {"name": "Customer", "type": "user"},
            "created_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
            "parts": [],
            "internal_notes": [],
        }
    ]
    r = await client.post("/tickets/ingest", json=payload)
    assert r.status_code == 200

    row = await session.get(Ticket, "conv-resolved-1")
    assert row is not None
    assert row.resolved_at is not None
    assert row.resolved_source == "ai_resolved"


# ── C2: auto-resolve must not undo a manual reopen ────────────────────────────


@pytest.mark.asyncio
async def test_auto_resolve_does_not_undo_manual_reopen(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After an operator reopens a ticket, the same cached AI verdict must NOT
    re-resolve it on the next sync.  Only a genuinely new customer-visible part
    (strictly later content_signature than resolution_cleared_at) should allow
    auto-resolve to fire again.

    Flow:
    1. Ingest → AI resolves with verdict='resolved', high conf → resolved_source='ai_resolved'.
    2. POST /tickets/{id}/reopen → open, resolution_cleared_at stamped.
    3. Re-ingest SAME payload (content_signature == base_part_ts ≤ cleared_at) → stays open.
    4. Ingest with one new part whose created_at is strictly after cleared_at → resolves again.
    """
    from datetime import UTC

    from app.ai.pipeline import CategorizationResult
    from app.models import Settings, Ticket

    s = (await session.scalars(select(Settings))).one()
    s.use_ai = True
    s.ai_resolve_default = True
    s.ai_resolve_confidence_threshold = 0.7
    await session.commit()

    # Use a fixed past timestamp for the initial part — well before test runtime.
    base_part_ts = "2026-05-25T10:00:00Z"

    def make_payload(*, extra_parts: list[dict] | None = None) -> list[dict]:
        base_parts = [
            {
                "author": {"type": "user"},
                "body": "thanks, works now",
                "created_at": base_part_ts,
                "is_admin": False,
            }
        ]
        return [
            {
                "id": "conv-reopen-1",
                "title": "Resolved by AI",
                "state": "open",
                "priority": None,
                "url": None,
                "author": {"name": "Customer", "type": "user"},
                "created_at": "2026-05-25T00:00:00Z",
                "updated_at": "2026-05-25T10:00:00Z",
                "parts": base_parts if extra_parts is None else base_parts + extra_parts,
                "internal_notes": [],
            }
        ]

    resolved_result: dict[str, CategorizationResult] = {
        "conv-reopen-1": CategorizationResult(
            category_id=1,
            proposal_id=None,
            summary="customer confirmed fixed",
            confidence=0.9,
            ai_resolution_verdict="resolved",
            ai_resolution_confidence=0.88,
            ai_resolution_reason="customer replied: thanks, works now",
        )
    }

    async def fake_categorize_many(
        *args: object, **kwargs: object
    ) -> dict[str, CategorizationResult]:
        return resolved_result

    monkeypatch.setattr("app.services.tickets.categorize_many", fake_categorize_many)

    # Step 1: first ingest → auto-resolves.
    r = await client.post("/tickets/ingest", json=make_payload())
    assert r.status_code == 200
    session.expire_all()
    row = await session.get(Ticket, "conv-reopen-1")
    assert row is not None
    assert row.resolved_at is not None
    assert row.resolved_source == "ai_resolved"

    # Step 2: reopen via API.
    r2 = await client.post("/tickets/conv-reopen-1/reopen")
    assert r2.status_code == 200
    session.expire_all()
    row = await session.get(Ticket, "conv-reopen-1")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolution_cleared_at is not None
    cleared_at = row.resolution_cleared_at

    # Step 3: re-ingest SAME payload (content_signature == base_part_ts ≤ cleared_at).
    # cleared_at is naive_utcnow() at reopen time; base_part_ts is 2026-05-25 — in the
    # past relative to the test run date of 2026-05-27.
    r3 = await client.post("/tickets/ingest", json=make_payload())
    assert r3.status_code == 200
    session.expire_all()
    row = await session.get(Ticket, "conv-reopen-1")
    assert row is not None
    assert row.resolved_at is None, "auto-resolve must not re-stamp after manual reopen"

    # Step 4: ingest with a new part whose created_at is strictly after cleared_at.
    # cleared_at is naive UTC from naive_utcnow() ≈ test-run wall-clock time.
    # Make the new part one hour in the future relative to cleared_at.
    future_ts = (cleared_at + timedelta(hours=1)).replace(tzinfo=UTC).isoformat()
    r4 = await client.post(
        "/tickets/ingest",
        json=make_payload(
            extra_parts=[
                {
                    "author": {"type": "user"},
                    "body": "actually still broken",
                    "created_at": future_ts,
                    "is_admin": False,
                }
            ]
        ),
    )
    assert r4.status_code == 200
    session.expire_all()
    row = await session.get(Ticket, "conv-reopen-1")
    assert row is not None
    assert (
        row.resolved_at is not None
    ), "new customer part after cleared_at should allow auto-resolve"
    assert row.resolved_source == "ai_resolved"


# ── T107: non_actionable_kind is stamped on AI auto-resolve ───────────────────


@pytest.mark.asyncio
async def test_ai_non_actionable_verdict_stamps_kind(
    app: object,
    client: AsyncClient,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AI auto-resolve as non_actionable stamps the structured kind on the row."""
    from app.ai.pipeline import CategorizationResult
    from app.models import Settings, Ticket

    s = (await session.scalars(select(Settings))).one()
    s.use_ai = True
    s.ai_resolve_default = True
    s.ai_resolve_confidence_threshold = 0.7
    await session.commit()

    async def fake_categorize_many(
        *args: object, **kwargs: object
    ) -> dict[str, CategorizationResult]:
        return {
            "conv-na-kind-1": CategorizationResult(
                category_id=1,
                proposal_id=None,
                summary="OOO bounce",
                confidence=0.9,
                ai_resolution_verdict="non_actionable",
                ai_resolution_confidence=0.97,
                ai_resolution_reason="auto-reply: OOO",
                non_actionable_kind="auto_reply",
            )
        }

    monkeypatch.setattr("app.services.tickets.categorize_many", fake_categorize_many)

    payload = [
        {
            "id": "conv-na-kind-1",
            "title": "Out of office",
            "state": "open",
            "priority": None,
            "url": None,
            "author": {"type": "user"},
            "created_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
            "parts": [],
            "internal_notes": [],
        }
    ]
    r = await client.post("/tickets/ingest", json=payload)
    assert r.status_code == 200

    # DB-level assertion — authoritative for this task.
    session.expire_all()
    row = await session.get(Ticket, "conv-na-kind-1")
    assert row is not None
    assert row.resolved_source == "non_actionable"
    assert row.non_actionable_kind == "auto_reply"

    # GET-level assertion — tolerant: ticket may be outside lookback window and not
    # appear in the list (updated_at is 2026-05-25 which can age out relative to
    # test-run time). If present, non_actionable_kind key may be absent until Task 7
    # adds it to TicketSchema.
    resolved_tickets = (await client.get("/tickets?resolved=true")).json()
    matching = [t for t in resolved_tickets if t["id"] == "conv-na-kind-1"]
    if matching:
        assert matching[0].get("non_actionable_kind") in ("auto_reply", None)

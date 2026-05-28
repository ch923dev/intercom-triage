"""Guard against the bug class that shipped the parked trio broken (T106):
``get_tickets`` composing ``TicketSchema`` and forgetting a row column, so the
field serializes as its schema default (None / empty) for every ticket
regardless of the DB row.

Two layers:
  1. ``test_every_ticketschema_field_is_classified`` fails when a new
     ``TicketSchema`` field appears, forcing a conscious pass-through-vs-derived
     choice (and thus coverage below) instead of silently shipping unwired.
  2. The sentinel tests set every pass-through column to a non-default value and
     assert the ``GET /tickets`` board response reflects it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.schemas import TicketSchema
from app.util import naive_utcnow

# Fields whose value is a direct pass-through of a `tickets` row column in
# services/tickets.py:get_tickets. Each must be reflected on the board response.
PASSTHROUGH_FIELDS = {
    "id",
    "title",
    "state",
    "priority",
    "created_at",
    "updated_at",
    "author",
    "url",
    "parts",
    "internal_notes",
    "summary",
    "ai_confidence",
    "title_user_edited",
    "summary_user_edited",
    "ai_resolve_override",  # = row.ai_resolve_enabled
    "ai_priority",
    "ai_sentiment",
    "ai_labels",
    "parked_at",
    "parked_until",
    "parked_reason",
    "parked_note",
    "resolved_at",
    "resolved_source",
    "non_actionable_kind",
}

# Fields get_tickets DERIVES (override logic, side tables, ai_cache, computed) —
# legitimately not a straight row pass-through, so excluded from the sentinel
# check. Listed explicitly so a newly added field forces a conscious choice.
DERIVED_FIELDS = {
    "category_id",
    "proposal_id",
    "user_override",
    "ai_resolve_enabled",  # effective value after merging with settings default
    "followup",
    "note",
    "ai_resolution_verdict",
    "ai_resolution_confidence",
    "ai_resolution_reason",
    "resolution_chip_state",
}


def test_every_ticketschema_field_is_classified() -> None:
    """A new TicketSchema field must be classified pass-through or derived — and
    a pass-through field then gets sentinel coverage below — rather than shipping
    unwired like the parked trio did."""
    assert set(TicketSchema.model_fields) == PASSTHROUGH_FIELDS | DERIVED_FIELDS


def _author() -> dict[str, Any]:
    return {
        "id": "u1",
        "name": "Ada",
        "email": "ada@example.io",
        "type": "user",
        "location": "NYC",
        "timezone": "UTC",
        "phone": "555",
        "company": "Acme",
    }


async def test_open_passthrough_fields_surface_on_board(
    client: AsyncClient, session: AsyncSession
) -> None:
    now = naive_utcnow()
    iso = now.isoformat() + "Z"
    session.add(
        Ticket(
            id="cov-open",
            title="sentinel-title",
            state="open",
            priority="priority",
            url="https://app.intercom.com/x",
            author=_author(),
            parts=[{"author": _author(), "body": "hello", "created_at": iso, "is_admin": False}],
            internal_notes=[
                {"author": _author(), "body": "note", "created_at": iso, "is_admin": True}
            ],
            created_at=now,
            updated_at=now,
            summary="sentinel-summary",
            ai_confidence=0.5,
            ai_priority="high",
            ai_sentiment="negative",
            ai_labels=["billing"],
            title_user_edited=True,
            summary_user_edited=True,
            ai_resolve_enabled=True,
            parked_at=now,
            parked_until=now + timedelta(hours=1),
            parked_reason="other",
            parked_note="resume soon",
        )
    )
    await session.commit()

    r = await client.get("/tickets")
    assert r.status_code == 200, r.text
    t = next(x for x in r.json() if x["id"] == "cov-open")

    assert t["title"] == "sentinel-title"
    assert t["state"] == "open"
    assert t["priority"] == "priority"
    assert t["url"] == "https://app.intercom.com/x"
    assert t["author"]["company"] == "Acme"
    assert len(t["parts"]) == 1 and t["parts"][0]["body"] == "hello"
    assert len(t["internal_notes"]) == 1
    assert t["created_at"] is not None
    assert t["updated_at"] is not None
    assert t["summary"] == "sentinel-summary"
    assert t["ai_confidence"] == 0.5
    assert t["ai_priority"] == "high"
    assert t["ai_sentiment"] == "negative"
    assert t["ai_labels"] == ["billing"]
    assert t["title_user_edited"] is True
    assert t["summary_user_edited"] is True
    assert t["ai_resolve_override"] is True
    assert t["parked_at"] is not None
    assert t["parked_until"] is not None
    assert t["parked_reason"] == "other"
    assert t["parked_note"] == "resume soon"


async def test_resolved_passthrough_fields_surface_on_board(
    client: AsyncClient, session: AsyncSession
) -> None:
    now = naive_utcnow()
    session.add(
        Ticket(
            id="cov-res",
            title="t",
            state="open",
            priority=None,
            url=None,
            author={},
            parts=[],
            internal_notes=[],
            created_at=now,
            updated_at=now,
            summary="",
            ai_confidence=0.0,
            resolved_at=now,
            resolved_source="non_actionable",
            non_actionable_kind="spam",
        )
    )
    await session.commit()

    r = await client.get("/tickets?resolved=true")
    assert r.status_code == 200, r.text
    t = next(x for x in r.json() if x["id"] == "cov-res")
    assert t["resolved_at"] is not None
    assert t["resolved_source"] == "non_actionable"
    assert t["non_actionable_kind"] == "spam"

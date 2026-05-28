"""The single 'override beats AI' rule (invariant #11), extracted so the board,
playbooks, clusters, and stats can't drift apart (they had — stats omitted the
timestamp check entirely)."""

from __future__ import annotations

from datetime import timedelta

from app.models import Override, Ticket
from app.services.categorization_rule import effective_category
from app.util import naive_utcnow


def _ticket(category_id: int | None, proposal_id: int | None = None) -> Ticket:
    now = naive_utcnow()
    return Ticket(
        id="t",
        title=None,
        state="open",
        priority=None,
        url=None,
        author={},
        parts=[],
        internal_notes=[],
        created_at=now,
        updated_at=now,
        category_id=category_id,
        proposal_id=proposal_id,
        summary="",
        ai_confidence=0.0,
    )


def _override(category_id: int, *, newer: bool) -> Override:
    t = _ticket(None)
    delta = timedelta(minutes=5)
    return Override(
        ticket_id="t",
        category_id=category_id,
        set_at=t.updated_at + delta if newer else t.updated_at - delta,
    )


def test_no_override_passes_through_ai_category() -> None:
    t = _ticket(category_id=3, proposal_id=None)
    assert effective_category(t, None) == (3, None, False)


def test_no_override_keeps_proposal() -> None:
    t = _ticket(category_id=None, proposal_id=9)
    assert effective_category(t, None) == (None, 9, False)


def test_override_at_least_as_new_wins_and_clears_proposal() -> None:
    t = _ticket(category_id=3, proposal_id=9)
    ov = _override(7, newer=True)
    assert effective_category(t, ov) == (7, None, True)


def test_override_equal_timestamp_wins() -> None:
    t = _ticket(category_id=3)
    ov = Override(ticket_id="t", category_id=7, set_at=t.updated_at)
    assert effective_category(t, ov) == (7, None, True)


def test_stale_override_loses_to_ai() -> None:
    t = _ticket(category_id=3, proposal_id=None)
    ov = _override(7, newer=False)
    assert effective_category(t, ov) == (3, None, False)

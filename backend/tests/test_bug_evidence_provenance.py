"""The evidence quote must be the CUSTOMER's words. Reference: US-044, NFR-016.

Live traffic produced a card quoting our own support agent ("I noticed that your
analytics aren't displaying properly") as if the customer had reported it. The
prompt already asked for the customer's words; only a deterministic check
survives a model swap, so that check is what these tests pin.
"""

from __future__ import annotations

from datetime import datetime

from app.ai.pipeline import ParsedAssignment, verify_bug_evidence
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema

NOW = datetime(2026, 8, 13, 12, 0, 0)


def _part(body: str, *, is_admin: bool) -> ConversationPartSchema:
    return ConversationPartSchema(
        author=TicketAuthorSchema(type="admin" if is_admin else "user", name="X"),
        body=body,
        created_at=NOW,
        is_admin=is_admin,
    )


def _ticket(*parts: ConversationPartSchema) -> HydratedTicket:
    return HydratedTicket(
        id="T1",
        title="t",
        state="open",
        priority=None,
        created_at=NOW,
        updated_at=NOW,
        author=TicketAuthorSchema(type="user", name="X"),
        url=None,
        parts=list(parts),
        internal_notes=[],
    )


def _parsed(evidence: str | None) -> ParsedAssignment:
    return ParsedAssignment(
        kind="existing",
        summary="s",
        confidence=0.9,
        subject="s",
        category_id=1,
        bug_severity="medium",
        bug_confidence=0.8,
        bug_evidence=evidence,
    )


def test_a_verbatim_customer_quote_is_kept() -> None:
    ticket = _ticket(_part("the export button does nothing at all", is_admin=False))
    out = verify_bug_evidence(_parsed("export button does nothing"), ticket)
    assert out.bug_evidence == "export button does nothing"


def test_an_agent_quote_is_rejected() -> None:
    """The regression that shipped: the model quoted the support rep."""
    ticket = _ticket(
        _part("Can we confirm my waiting list ppl are getting messages", is_admin=False),
        _part("I noticed that your analytics aren't displaying properly", is_admin=True),
    )
    out = verify_bug_evidence(
        _parsed("I noticed that your analytics aren't displaying properly"), ticket
    )
    assert out.bug_evidence is None


def test_rejecting_the_quote_keeps_the_verdict() -> None:
    """An evidence-less bug report is still a bug report — do not drop it."""
    ticket = _ticket(_part("agent words", is_admin=True))
    out = verify_bug_evidence(_parsed("agent words"), ticket)
    assert out.bug_evidence is None
    assert out.bug_severity == "medium"
    assert out.bug_confidence == 0.8


def test_smart_quotes_still_match() -> None:
    """Observed live: the model straightens the customer's curly punctuation.

    Without typography folding this genuine quote would be thrown away.
    """
    ticket = _ticket(
        _part("The workflow “OE All MP” suddenly stopped — messages aren’t going", is_admin=False)
    )
    out = verify_bug_evidence(
        _parsed('The workflow "OE All MP" suddenly stopped - messages aren\'t going'), ticket
    )
    assert out.bug_evidence is not None


def test_whitespace_and_case_differences_still_match() -> None:
    ticket = _ticket(_part("Export\n  fails   every time", is_admin=False))
    out = verify_bug_evidence(_parsed("export fails every time"), ticket)
    assert out.bug_evidence is not None


def test_a_quote_stitched_across_two_messages_is_rejected() -> None:
    """Containment is per part: nobody said this in one breath."""
    ticket = _ticket(
        _part("export fails", is_admin=False),
        _part("every single time", is_admin=False),
    )
    out = verify_bug_evidence(_parsed("export fails every single time"), ticket)
    assert out.bug_evidence is None


def test_a_paraphrase_is_rejected() -> None:
    ticket = _ticket(_part("i cant get the csv out of the thing", is_admin=False))
    out = verify_bug_evidence(_parsed("The customer is unable to export a CSV file."), ticket)
    assert out.bug_evidence is None


def test_no_evidence_passes_through_untouched() -> None:
    ticket = _ticket(_part("anything", is_admin=False))
    parsed = _parsed(None)
    assert verify_bug_evidence(parsed, ticket) is parsed


def test_a_ticket_with_no_customer_parts_rejects_everything() -> None:
    ticket = _ticket(_part("only the agent spoke", is_admin=True))
    assert verify_bug_evidence(_parsed("only the agent spoke"), ticket).bug_evidence is None

"""Roadmap 2.5 — few-shot categorization from confirmed overrides.

Offline via the autouse `fake_encoder` fixture: identical text → identical
vector → distance ~0, so a query ticket whose parts match a stored neighbour
retrieves that neighbour deterministically.

Covers:
- Examples are retrieved for a ticket whose nearest neighbour has a confirmed
  `Override` row, and the confirmed category name is surfaced.
- Invariant #4: a neighbour's `internal_notes` text NEVER leaks into the built
  prompt (sentinel assertion).
- Unconfirmed neighbours (no Override) are filtered out.
- The no-examples path (cold corpus / disabled) leaves the prompt unchanged.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fewshot import gather_fewshot_examples
from app.ai.pipeline import categorize_many
from app.ai.prompt import build_messages
from app.config import AppConfig
from app.models import Category, Override
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema
from app.services.tickets import ingest_tickets
from tests.helpers import FakeOpenRouter, existing_assignment, make_hydrated

_DT = datetime(2026, 5, 23, 12, 0, 0)
_NEIGHBOUR_BODY = "my export to CSV is missing custom fields and breaks nightly"


def _hydrated(
    ticket_id: str,
    *,
    title: str,
    part_body: str,
    internal_note_body: str | None = None,
) -> HydratedTicket:
    author = TicketAuthorSchema(id="u1", name="Customer", type="user")
    internal_notes = []
    if internal_note_body is not None:
        internal_notes = [
            ConversationPartSchema(author=author, body=internal_note_body, created_at=_DT)
        ]
    return HydratedTicket(
        id=ticket_id,
        title=title,
        state="open",
        priority=None,
        created_at=_DT,
        updated_at=_DT,
        author=author,
        url=None,
        parts=[ConversationPartSchema(author=author, body=part_body, created_at=_DT)],
        internal_notes=internal_notes,
    )


async def _active_non_fallback_category(session: AsyncSession) -> Category:
    cat = (
        await session.scalars(
            select(Category).where(Category.is_active.is_(True), Category.is_fallback.is_(False))
        )
    ).first()
    assert cat is not None
    return cat


async def _fallback_id(session: AsyncSession) -> int:
    cid = await session.scalar(select(Category.id).where(Category.is_fallback.is_(True)))
    assert cid is not None
    return cid


async def _ingest_confirmed_neighbour(
    session: AsyncSession,
    test_config: AppConfig,
    *,
    ticket_id: str,
    internal_note_body: str | None,
) -> Category:
    """Ingest a neighbour ticket (stores embedding + ticket row) and confirm it
    with an Override row. Returns the confirmed category."""
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[
            _hydrated(
                ticket_id,
                title="CSV export issue",
                part_body=_NEIGHBOUR_BODY,
                internal_note_body=internal_note_body,
            )
        ],
    )
    cat = await _active_non_fallback_category(session)
    session.add(Override(ticket_id=ticket_id, category_id=cat.id))
    await session.commit()
    return cat


@pytest.mark.asyncio
async def test_gather_returns_confirmed_override_neighbour(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """A query ticket whose text matches a confirmed-override neighbour retrieves
    it, with the operator's confirmed category name."""
    cat = await _ingest_confirmed_neighbour(
        session, test_config, ticket_id="n1", internal_note_body=None
    )

    # Query ticket: same parts text → distance ~0 → n1 is the nearest neighbour.
    query = _hydrated("q1", title="csv broken", part_body=_NEIGHBOUR_BODY)
    examples = await gather_fewshot_examples(session, [query], max_examples=3)

    assert "q1" in examples
    assert len(examples["q1"]) == 1
    assert examples["q1"][0].category_name == cat.name
    assert "export to CSV is missing" in examples["q1"][0].text


@pytest.mark.asyncio
async def test_unconfirmed_neighbour_is_filtered_out(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """A nearest neighbour WITHOUT an Override row contributes no example."""
    # Ingest a neighbour but DO NOT add an Override → not a confirmed label.
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[_hydrated("n1", title="CSV", part_body=_NEIGHBOUR_BODY)],
    )
    query = _hydrated("q1", title="csv broken", part_body=_NEIGHBOUR_BODY)
    examples = await gather_fewshot_examples(session, [query], max_examples=3)
    assert examples == {}


@pytest.mark.asyncio
async def test_max_examples_zero_short_circuits(
    session: AsyncSession, test_config: AppConfig
) -> None:
    await _ingest_confirmed_neighbour(session, test_config, ticket_id="n1", internal_note_body=None)
    query = _hydrated("q1", title="csv broken", part_body=_NEIGHBOUR_BODY)
    assert await gather_fewshot_examples(session, [query], max_examples=0) == {}


@pytest.mark.asyncio
async def test_internal_notes_never_leak_into_prompt(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Invariant #4: a confirmed neighbour's internal-note text must NEVER appear
    in the categorization messages built with its few-shot example."""
    secret = "SECRET-INTERNAL-NOTE-MUST-NOT-LEAK"
    await _ingest_confirmed_neighbour(
        session, test_config, ticket_id="n1", internal_note_body=secret
    )

    query = _hydrated("q1", title="csv broken", part_body=_NEIGHBOUR_BODY)
    examples = await gather_fewshot_examples(session, [query], max_examples=3)
    assert "q1" in examples, "expected the confirmed neighbour to be retrieved"

    cats = (await session.scalars(select(Category))).all()
    messages = build_messages(query, cats, [], [], examples["q1"])
    blob = "\n".join(m["content"] for m in messages)

    # The example block is present...
    assert "EXAMPLES OF HOW SIMILAR TICKETS WERE CATEGORIZED" in blob
    assert "export to CSV is missing" in blob
    # ...but the neighbour's internal note never made it in.
    assert secret not in blob


@pytest.mark.asyncio
async def test_no_examples_prompt_matches_prior_behavior(session: AsyncSession) -> None:
    """Cold corpus: build_messages with no examples is byte-for-byte the old prompt."""
    cats = (await session.scalars(select(Category))).all()
    ticket = make_hydrated("X")
    without_arg = build_messages(ticket, cats, [], ["Outage"])
    with_empty = build_messages(ticket, cats, [], ["Outage"], None)
    with_empty_list = build_messages(ticket, cats, [], ["Outage"], [])
    assert without_arg == with_empty == with_empty_list
    # No examples block leaks into the cold-corpus prompt.
    assert "EXAMPLES OF HOW SIMILAR TICKETS" not in without_arg[1]["content"]


@pytest.mark.asyncio
async def test_categorize_many_injects_examples_into_call(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """End-to-end through categorize_many: the confirmed neighbour's example +
    its internal-note sentinel — example present, sentinel absent in the prompt
    actually sent to the model."""
    secret = "SECRET-INTERNAL-NOTE-MUST-NOT-LEAK"
    await _ingest_confirmed_neighbour(
        session, test_config, ticket_id="n1", internal_note_body=secret
    )
    fb = await _fallback_id(session)

    query = _hydrated("q1", title="csv broken", part_body=_NEIGHBOUR_BODY)
    fake = CapturingOpenRouter({"q1": existing_assignment(1)})
    out = await categorize_many(
        [query],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
        fewshot_examples=3,
    )
    assert out["q1"].category_id == 1
    sent = "\n".join(m["content"] for m in fake.last_messages or [])
    assert "EXAMPLES OF HOW SIMILAR TICKETS WERE CATEGORIZED" in sent
    assert "export to CSV is missing" in sent
    assert secret not in sent


@pytest.mark.asyncio
async def test_categorize_many_no_fewshot_when_disabled(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """fewshot_examples=0 (default) → no examples block even with a confirmed
    neighbour available; behaves exactly as before."""
    await _ingest_confirmed_neighbour(session, test_config, ticket_id="n1", internal_note_body=None)
    fb = await _fallback_id(session)
    query = _hydrated("q1", title="csv broken", part_body=_NEIGHBOUR_BODY)
    fake = CapturingOpenRouter({"q1": existing_assignment(1)})
    await categorize_many(
        [query],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
        # fewshot_examples defaults to 0
    )
    sent = "\n".join(m["content"] for m in fake.last_messages or [])
    assert "EXAMPLES OF HOW SIMILAR TICKETS" not in sent


class CapturingOpenRouter(FakeOpenRouter):
    """FakeOpenRouter that also records the last `messages` array it was sent."""

    def __init__(self, by_ticket: dict[str, str]) -> None:
        super().__init__(by_ticket)
        self.last_messages: list[dict[str, str]] | None = None

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        ticket_id: str | None = None,
        response_format: dict[str, object] | None = None,
    ) -> str:
        self.last_messages = messages
        return await super().complete(
            model=model,
            messages=messages,
            ticket_id=ticket_id,
            response_format=response_format,  # type: ignore[arg-type]
        )

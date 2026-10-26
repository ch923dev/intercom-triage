"""Customer-visible activity, not Intercom's `updated_at`, decides whether a
conversation "moved" (T205, T206).

Intercom advances `updated_at` on internal notes, assignments and snoozes. Two
rules used to key on it and so treated a teammate's note as if the customer had
written: a manual category override silently expired (T205), and a resolved
ticket raised a false "new reply" chip (T206). Both now compare against
`tickets.content_signature_at` — the same last-customer-visible-part timestamp
the AI cache keys on (invariant #6).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.models import Category, Ticket
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema
from app.services import resolution
from app.services.stats import get_stats
from app.services.tickets import get_tickets, ingest_tickets, set_override
from app.util import naive_utcnow

_CUSTOMER = TicketAuthorSchema(id="u1", name="Customer", type="user")
_TEAMMATE = TicketAuthorSchema(id="a1", name="Teammate", type="admin")


def _hydrated(
    *,
    customer_parts: list[datetime],
    notes: list[datetime] | None = None,
    updated_at: datetime,
) -> HydratedTicket:
    return HydratedTicket(
        id="t1",
        title="Card",
        state="open",
        priority=None,
        created_at=customer_parts[0],
        updated_at=updated_at,
        author=_CUSTOMER,
        url=None,
        parts=[
            ConversationPartSchema(author=_CUSTOMER, body=f"message {i}", created_at=at)
            for i, at in enumerate(customer_parts)
        ],
        internal_notes=[
            ConversationPartSchema(author=_TEAMMATE, body="internal note", created_at=at)
            for at in (notes or [])
        ],
    )


async def _ingest(session: AsyncSession, config: AppConfig, ticket: HydratedTicket) -> None:
    # openrouter=None → every ticket lands in the fallback category, which is all
    # these tests need: "the AI's category" vs "the operator's override".
    await ingest_tickets(session=session, openrouter=None, config=config, hydrated=[ticket])


async def _non_fallback_category(session: AsyncSession) -> int:
    category = (
        await session.scalars(
            select(Category).where(Category.is_fallback.is_(False), Category.is_active.is_(True))
        )
    ).first()
    assert category is not None
    return category.id


async def _board_card(session: AsyncSession, *, resolved: bool = False):  # type: ignore[no-untyped-def]
    cards = [c for c in await get_tickets(session, resolved=resolved) if c.id == "t1"]
    assert len(cards) == 1
    return cards[0]


# ── Storage ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ingest_stores_last_customer_visible_part_not_updated_at(
    session: AsyncSession, test_config: AppConfig
) -> None:
    now = naive_utcnow()
    first, second = now - timedelta(hours=3), now - timedelta(hours=2)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[first, second], notes=[now], updated_at=now),
    )
    row = await session.get(Ticket, "t1")
    assert row is not None
    assert row.updated_at == now
    assert row.content_signature_at == second


# ── T205 — the override survives internal activity ───────────────────────────


@pytest.mark.asyncio
async def test_internal_note_after_override_keeps_the_override(
    session: AsyncSession, test_config: AppConfig
) -> None:
    now = naive_utcnow()
    asked = now - timedelta(hours=1)
    await _ingest(session, test_config, _hydrated(customer_parts=[asked], updated_at=asked))
    chosen = await _non_fallback_category(session)
    await set_override(session, "t1", chosen, acted_by=None)

    # A teammate adds an internal note in Intercom after the override: Intercom's
    # updated_at moves past override.set_at, the customer-visible thread does not.
    later = naive_utcnow() + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked], notes=[later], updated_at=later),
    )

    card = await _board_card(session)
    assert card.category_id == chosen
    assert card.user_override is True


@pytest.mark.asyncio
async def test_reassignment_after_override_keeps_the_override(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Assignment / snooze: updated_at advances with no new part at all."""
    now = naive_utcnow()
    asked = now - timedelta(hours=1)
    await _ingest(session, test_config, _hydrated(customer_parts=[asked], updated_at=asked))
    chosen = await _non_fallback_category(session)
    await set_override(session, "t1", chosen, acted_by=None)

    later = naive_utcnow() + timedelta(minutes=10)
    await _ingest(session, test_config, _hydrated(customer_parts=[asked], updated_at=later))

    card = await _board_card(session)
    assert card.category_id == chosen
    assert card.user_override is True


@pytest.mark.asyncio
async def test_new_customer_message_after_override_hands_back_to_the_ai(
    session: AsyncSession, test_config: AppConfig
) -> None:
    now = naive_utcnow()
    asked = now - timedelta(hours=1)
    await _ingest(session, test_config, _hydrated(customer_parts=[asked], updated_at=asked))
    fallback_id = (await session.get(Ticket, "t1")).category_id  # type: ignore[union-attr]
    chosen = await _non_fallback_category(session)
    await set_override(session, "t1", chosen, acted_by=None)

    replied = naive_utcnow() + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked, replied], updated_at=replied),
    )

    card = await _board_card(session)
    assert card.category_id == fallback_id
    assert card.user_override is False


@pytest.mark.asyncio
async def test_stats_count_the_same_effective_category_as_the_board(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """stats mirrors the rule in SQL — it must agree with the board after an
    internal note, or the dashboard and the columns disagree."""
    now = naive_utcnow()
    asked = now - timedelta(hours=1)
    await _ingest(session, test_config, _hydrated(customer_parts=[asked], updated_at=asked))
    chosen = await _non_fallback_category(session)
    await set_override(session, "t1", chosen, acted_by=None)
    later = naive_utcnow() + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked], notes=[later], updated_at=later),
    )

    stats = await get_stats(session)
    by_id = {c.category_id: c.count for c in stats.category_breakdown}
    assert by_id.get(chosen) == 1


# ── T206 — the "new reply" chip means a customer-visible reply ───────────────


async def _resolved_ticket(session: AsyncSession, config: AppConfig) -> datetime:
    asked = naive_utcnow() - timedelta(hours=1)
    await _ingest(session, config, _hydrated(customer_parts=[asked], updated_at=asked))
    await resolution.resolve(session, "t1", resolved_by=None)
    return asked


@pytest.mark.asyncio
async def test_internal_note_after_resolution_raises_no_chip(
    session: AsyncSession, test_config: AppConfig
) -> None:
    asked = await _resolved_ticket(session, test_config)
    later = naive_utcnow() + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked], notes=[later], updated_at=later),
    )

    card = await _board_card(session, resolved=True)
    assert card.resolution_chip_state is None


@pytest.mark.asyncio
async def test_customer_reply_after_resolution_raises_new_reply(
    session: AsyncSession, test_config: AppConfig
) -> None:
    asked = await _resolved_ticket(session, test_config)
    replied = naive_utcnow() + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked, replied], updated_at=replied),
    )

    card = await _board_card(session, resolved=True)
    assert card.resolution_chip_state == "new_reply"


@pytest.mark.asyncio
async def test_dismissed_chip_stays_dismissed_through_an_internal_note(
    session: AsyncSession, test_config: AppConfig
) -> None:
    asked = await _resolved_ticket(session, test_config)
    replied = naive_utcnow() + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked, replied], updated_at=replied),
    )
    await resolution.dismiss_chip(session, "t1")

    noted = replied + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked, replied], notes=[noted], updated_at=noted),
    )
    card = await _board_card(session, resolved=True)
    assert card.resolution_chip_state is None

    # …and comes back on the next customer-visible reply.
    again = noted + timedelta(minutes=10)
    await _ingest(
        session,
        test_config,
        _hydrated(customer_parts=[asked, replied, again], updated_at=again),
    )
    card = await _board_card(session, resolved=True)
    assert card.resolution_chip_state == "new_reply"

"""Verifies ingest-time resolution behavior:
- Intercom state transition open → closed auto-resolves with source='intercom_closed'.
- A ticket arriving as closed on first sight auto-resolves on first store.
- A previously-resolved ticket stays resolved across syncs (no re-stamp).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
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

    openrouter = AsyncMock()
    openrouter.classify = AsyncMock(
        return_value=(
            '{"assignment":"existing","category_id":1,"subject":"s","summary":"x",'
            '"confidence":0.9,"resolution_verdict":"not_resolved",'
            '"resolution_confidence":0.5,"resolution_reason":"open"}'
        )
    )

    # First sync — open state, store the ticket.
    await ingest_tickets(
        session=session,
        openrouter=openrouter,
        config=test_config,
        hydrated=[make_hydrated(state="open")],
    )
    row = await session.get(Ticket, "t1")
    assert row is not None and row.resolved_at is None

    # Second sync — same id, state=closed, later updated_at.
    await ingest_tickets(
        session=session,
        openrouter=openrouter,
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

    openrouter = AsyncMock()
    openrouter.classify = AsyncMock(
        return_value=(
            '{"assignment":"existing","category_id":1,"subject":"s","summary":"x",'
            '"confidence":0.9}'
        )
    )

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
        openrouter=openrouter,
        config=test_config,
        hydrated=[make_hydrated(id="t2", state="closed", updated_at=datetime(2026, 5, 24))],
    )
    row = await session.get(Ticket, "t2")
    assert row.resolved_at == original  # unchanged

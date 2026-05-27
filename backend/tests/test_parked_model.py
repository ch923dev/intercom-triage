from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.util import naive_utcnow


async def _make_open_ticket(session: AsyncSession, tid: str = "park-1") -> Ticket:
    row = Ticket(
        id=tid, title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        summary="", ai_confidence=0.0,
    )
    session.add(row)
    await session.commit()
    return row


async def test_full_parked_trio_is_allowed(session: AsyncSession) -> None:
    row = await _make_open_ticket(session)
    now = naive_utcnow()
    row.parked_at = now
    row.parked_until = now
    row.parked_reason = "waiting_on_customer"
    await session.commit()
    fetched = (await session.scalars(select(Ticket).where(Ticket.id == "park-1"))).one()
    assert fetched.parked_reason == "waiting_on_customer"


async def test_half_parked_trio_is_rejected(session: AsyncSession) -> None:
    row = await _make_open_ticket(session, "park-2")
    row.parked_at = naive_utcnow()  # but not parked_until / parked_reason
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_parked_reason_enum_is_enforced(session: AsyncSession) -> None:
    row = await _make_open_ticket(session, "park-3")
    now = naive_utcnow()
    row.parked_at, row.parked_until, row.parked_reason = now, now, "bogus"
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_parked_and_resolved_is_rejected(session: AsyncSession) -> None:
    row = await _make_open_ticket(session, "park-4")
    now = naive_utcnow()
    row.resolved_at, row.resolved_source = now, "manual"
    row.parked_at, row.parked_until, row.parked_reason = now, now, "other"
    with pytest.raises(IntegrityError):
        await session.commit()

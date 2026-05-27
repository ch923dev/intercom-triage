from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services import resolution as svc
from app.util import naive_utcnow


async def _open(session: AsyncSession, tid: str) -> Ticket:
    row = Ticket(
        id=tid,
        title="t",
        state="open",
        priority=None,
        url=None,
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        summary="",
        ai_confidence=0.0,
    )
    session.add(row)
    await session.commit()
    return row


async def test_park_then_unpark(session: AsyncSession) -> None:
    row = await _open(session, "p1")
    until = naive_utcnow() + timedelta(hours=2)
    out = svc.apply_park(row, until, "waiting_on_customer")
    assert out.parked_until == until
    assert row.parked_at is not None
    svc.apply_unpark(row)
    assert row.parked_at is None and row.parked_until is None and row.parked_reason is None


async def test_park_twice_is_409(session: AsyncSession) -> None:
    row = await _open(session, "p2")
    svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "other")
    with pytest.raises(HTTPException) as exc:
        svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "other")
    assert exc.value.status_code == 409


async def test_unpark_when_not_parked_is_409(session: AsyncSession) -> None:
    row = await _open(session, "p3")
    with pytest.raises(HTTPException) as exc:
        svc.apply_unpark(row)
    assert exc.value.status_code == 409


async def test_cannot_park_resolved_ticket(session: AsyncSession) -> None:
    row = await _open(session, "p4")
    svc.apply_resolve(row)
    with pytest.raises(HTTPException) as exc:
        svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "other")
    assert exc.value.status_code == 409


async def test_resolving_a_parked_ticket_clears_park(session: AsyncSession) -> None:
    row = await _open(session, "p5")
    svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "waiting_internal")
    svc.apply_resolve(row)
    await session.commit()  # would raise if parked + resolved both set
    assert row.parked_at is None
    assert row.resolved_source == "manual"

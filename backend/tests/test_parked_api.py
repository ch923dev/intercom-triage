from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.util import naive_utcnow


async def _seed_open(session: AsyncSession, tid: str = "api-1") -> None:
    session.add(Ticket(
        id=tid, title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(), summary="", ai_confidence=0.0,
    ))
    await session.commit()


async def test_park_and_unpark_roundtrip(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session)
    until = (naive_utcnow() + timedelta(hours=1)).isoformat() + "Z"
    r = await client.post("/tickets/api-1/park", json={"until_at": until, "reason": "waiting_on_customer"})
    assert r.status_code == 200, r.text
    assert r.json()["parked_reason"] == "waiting_on_customer"
    r2 = await client.post("/tickets/api-1/unpark", json={})
    assert r2.status_code == 200 and r2.json()["ok"] is True


async def test_park_past_time_is_422(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session, "api-2")
    past = (naive_utcnow() - timedelta(hours=1)).isoformat() + "Z"
    r = await client.post("/tickets/api-2/park", json={"until_at": past, "reason": "other"})
    assert r.status_code == 422


async def test_unpark_not_parked_is_409(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session, "api-3")
    r = await client.post("/tickets/api-3/unpark", json={})
    assert r.status_code == 409


async def test_bulk_park(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session, "api-4")
    until = (naive_utcnow() + timedelta(hours=1)).isoformat() + "Z"
    r = await client.post(
        "/tickets/bulk/park",
        json={"ticket_ids": ["api-4"], "until_at": until, "reason": "waiting_internal"},
    )
    assert r.status_code == 200 and r.json()["ok_ids"] == ["api-4"]

"""Assignment: PATCH /tickets/{id}/assign + bulk; null clears."""

from __future__ import annotations

from app.config import MAX_BULK_IDS
from app.models import Ticket
from app.util import naive_utcnow


async def _seed(session, tid: str) -> None:
    session.add(
        Ticket(
            id=tid,
            title="x",
            state="open",
            author={},
            parts=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
        )
    )
    await session.commit()


async def test_assign_sets_and_clears(client, session) -> None:
    await _seed(session, "t1")
    resp = await client.patch("/tickets/t1/assign", json={"user_id": 1})
    assert resp.status_code == 200
    row = await session.get(Ticket, "t1")
    assert row is not None and row.assigned_to == 1 and row.assigned_at is not None
    # null clears
    resp = await client.patch("/tickets/t1/assign", json={"user_id": None})
    assert resp.status_code == 200
    session.expire_all()  # flush identity map so next get re-fetches from DB
    row = await session.get(Ticket, "t1")
    assert row is not None and row.assigned_to is None and row.assigned_at is None


async def test_assign_unknown_user_422(client, session) -> None:
    await _seed(session, "t2")
    resp = await client.patch("/tickets/t2/assign", json={"user_id": 999})
    assert resp.status_code == 422


async def test_bulk_assign(client, session) -> None:
    await _seed(session, "a")
    await _seed(session, "b")
    resp = await client.patch("/tickets/bulk/assign", json={"ticket_ids": ["a", "b"], "user_id": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["ok_ids"]) == {"a", "b"}
    # Verify DB state: bulk closure actually mutated both rows.
    session.expire_all()
    for tid in ("a", "b"):
        row = await session.get(Ticket, tid)
        assert row is not None and row.assigned_to == 1 and row.assigned_at is not None


async def test_bulk_assign_over_cap_422(client) -> None:
    ids = [f"t{i}" for i in range(MAX_BULK_IDS + 1)]
    resp = await client.patch("/tickets/bulk/assign", json={"ticket_ids": ids, "user_id": 1})
    assert resp.status_code == 422

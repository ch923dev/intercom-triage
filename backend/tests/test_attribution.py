"""Attribution capture: resolve stamps resolved_by; override stamps acted_by."""

from __future__ import annotations

from app.models import Override, Ticket
from app.util import naive_utcnow


async def _seed_ticket(session, tid: str = "t1") -> None:
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


async def test_manual_resolve_stamps_resolved_by(client, session) -> None:
    await _seed_ticket(session)
    resp = await client.post("/tickets/t1/resolve")
    assert resp.status_code == 200
    row = await session.get(Ticket, "t1")
    assert row is not None and row.resolved_by == 1


async def test_override_stamps_acted_by(client, session) -> None:
    await _seed_ticket(session)
    resp = await client.patch("/tickets/t1/category", json={"category_id": 1})
    assert resp.status_code == 200
    ov = await session.get(Override, "t1")
    assert ov is not None and ov.acted_by == 1


async def test_manual_non_actionable_stamps_resolved_by(client, session) -> None:
    await _seed_ticket(session, "tna")
    resp = await client.post("/tickets/tna/non-actionable")
    assert resp.status_code == 200
    row = await session.get(Ticket, "tna")
    assert row is not None and row.resolved_by == 1 and row.resolved_source == "non_actionable"


async def test_bulk_resolve_stamps_resolved_by(client, session) -> None:
    await _seed_ticket(session, "b1")
    await _seed_ticket(session, "b2")
    resp = await client.post("/tickets/bulk/resolve", json={"ticket_ids": ["b1", "b2"]})
    assert resp.status_code == 200
    for tid in ("b1", "b2"):
        row = await session.get(Ticket, tid)
        assert row is not None and row.resolved_by == 1


async def test_bulk_non_actionable_stamps_resolved_by(client, session) -> None:
    await _seed_ticket(session, "bna1")
    await _seed_ticket(session, "bna2")
    resp = await client.post("/tickets/bulk/non-actionable", json={"ticket_ids": ["bna1", "bna2"]})
    assert resp.status_code == 200
    for tid in ("bna1", "bna2"):
        row = await session.get(Ticket, tid)
        assert row is not None and row.resolved_by == 1 and row.resolved_source == "non_actionable"


async def test_board_surfaces_resolved_by_name(client, session) -> None:
    await _seed_ticket(session, "t2")
    await client.post("/tickets/t2/resolve")
    resp = await client.get("/tickets?resolved=true")
    assert resp.status_code == 200
    row = next(t for t in resp.json() if t["id"] == "t2")
    assert row["resolved_by"] == {"id": 1, "name": "Seed Operator"}


async def test_board_surfaces_acted_by_name(client, session) -> None:
    await _seed_ticket(session, "t3")
    await client.patch("/tickets/t3/category", json={"category_id": 1})
    resp = await client.get("/tickets")
    assert resp.status_code == 200
    row = next(t for t in resp.json() if t["id"] == "t3")
    assert row["acted_by"] == {"id": 1, "name": "Seed Operator"}

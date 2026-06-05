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

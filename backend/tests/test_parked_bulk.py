from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services import bulk as bulk_svc
from app.services import resolution as svc
from app.util import naive_utcnow


async def _open(session: AsyncSession, tid: str) -> None:
    session.add(
        Ticket(
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
    )
    await session.commit()


async def test_bulk_park_then_unpark(session: AsyncSession) -> None:
    for t in ("b1", "b2"):
        await _open(session, t)
    until = naive_utcnow() + timedelta(hours=3)
    res = await bulk_svc.bulk_park(session, ["b1", "b2"], until, "waiting_on_third_party")
    assert set(res.ok_ids) == {"b1", "b2"} and res.failed == []
    res2 = await bulk_svc.bulk_unpark(session, ["b1", "b2"])
    assert set(res2.ok_ids) == {"b1", "b2"}


async def test_bulk_park_skips_already_parked(session: AsyncSession) -> None:
    await _open(session, "b3")
    svc.apply_park(
        await svc.get_or_404(session, "b3"), naive_utcnow() + timedelta(hours=1), "other"
    )
    await session.commit()
    res = await bulk_svc.bulk_park(session, ["b3"], naive_utcnow() + timedelta(hours=2), "other")
    assert res.ok_ids == [] and len(res.failed) == 1

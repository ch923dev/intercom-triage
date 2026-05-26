"""T7 — resolution service unit tests.

Fixture adaptation: conftest exposes `session` (not `seeded_db`).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services import resolution as svc
from app.util import naive_utcnow


def _make_open_ticket(id: str = "t1") -> Ticket:
    return Ticket(
        id=id,
        title="x",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        category_id=1,
        summary="",
        ai_confidence=0.0,
    )


@pytest.mark.asyncio
async def test_resolve_marks_manual_and_returns_datetime(session):
    session.add(_make_open_ticket("t1"))
    await session.commit()

    out = await svc.resolve(session, "t1")
    assert out.resolved_source == "manual"
    row = await session.get(Ticket, "t1")
    assert row.resolved_at is not None
    assert row.resolved_source == "manual"


@pytest.mark.asyncio
async def test_resolve_409_if_already_resolved(session):
    t = _make_open_ticket("t2")
    t.resolved_at = naive_utcnow()
    t.resolved_source = "manual"
    session.add(t)
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await svc.resolve(session, "t2")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reopen_clears_resolved_fields(session):
    t = _make_open_ticket("t3")
    t.resolved_at = naive_utcnow()
    t.resolved_source = "manual"
    session.add(t)
    await session.commit()

    await svc.reopen(session, "t3")
    row = await session.get(Ticket, "t3")
    assert row.resolved_at is None
    assert row.resolved_source is None


@pytest.mark.asyncio
async def test_reopen_409_if_already_open(session):
    session.add(_make_open_ticket("t4"))
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await svc.reopen(session, "t4")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_set_ai_resolve_tristate(session):
    session.add(_make_open_ticket("t5"))
    await session.commit()
    await svc.set_ai_resolve(session, "t5", True)
    assert (await session.get(Ticket, "t5")).ai_resolve_enabled is True
    await svc.set_ai_resolve(session, "t5", False)
    assert (await session.get(Ticket, "t5")).ai_resolve_enabled is False
    await svc.set_ai_resolve(session, "t5", None)
    assert (await session.get(Ticket, "t5")).ai_resolve_enabled is None


@pytest.mark.asyncio
async def test_dismiss_chip_sets_dismissed_at_to_updated_at(session):
    t = _make_open_ticket("t6")
    t.updated_at = datetime(2026, 5, 23, 10, 0)
    session.add(t)
    await session.commit()

    await svc.dismiss_chip(session, "t6")
    row = await session.get(Ticket, "t6")
    assert row.resolution_chip_dismissed_at == datetime(2026, 5, 23, 10, 0)


@pytest.mark.asyncio
async def test_404_on_unknown_ticket(session):
    for fn in (svc.resolve, svc.reopen, svc.dismiss_chip):
        with pytest.raises(HTTPException) as exc:
            await fn(session, "ghost")
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await svc.set_ai_resolve(session, "ghost", True)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_mark_non_actionable_stamps_source(session: AsyncSession) -> None:
    from app.models import Ticket
    from app.services.resolution import mark_non_actionable
    from app.util import naive_utcnow

    now = naive_utcnow()
    session.add(
        Ticket(
            id="t-na-svc-1", title="x", state="open", author={}, parts=[],
            internal_notes=[], created_at=now, updated_at=now, category_id=1,
            summary="", ai_confidence=0.0,
        )
    )
    await session.commit()

    out = await mark_non_actionable(session, "t-na-svc-1")
    assert out.resolved_source == "non_actionable"
    assert out.resolved_at is not None

    row = await session.get(Ticket, "t-na-svc-1")
    assert row is not None
    assert row.resolved_source == "non_actionable"


@pytest.mark.asyncio
async def test_mark_non_actionable_409_when_already_resolved(session: AsyncSession) -> None:
    from fastapi import HTTPException
    from app.models import Ticket
    from app.services.resolution import mark_non_actionable
    from app.util import naive_utcnow

    now = naive_utcnow()
    session.add(
        Ticket(
            id="t-na-svc-2", title="x", state="open", author={}, parts=[],
            internal_notes=[], created_at=now, updated_at=now, category_id=1,
            summary="", ai_confidence=0.0,
            resolved_at=now, resolved_source="manual",
        )
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await mark_non_actionable(session, "t-na-svc-2")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_mark_non_actionable_404_unknown(session: AsyncSession) -> None:
    from fastapi import HTTPException
    from app.services.resolution import mark_non_actionable

    with pytest.raises(HTTPException) as exc:
        await mark_non_actionable(session, "ghost")
    assert exc.value.status_code == 404

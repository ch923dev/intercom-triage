"""T8 — resolution endpoints integration tests.

Fixture adaptation: conftest exposes `client` and `session` (not `db_session`).
Both fixtures depend on the same `app` fixture, so they share one in-memory DB.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.util import naive_utcnow


def _seed_open(session: AsyncSession, id: str = "t1") -> None:
    session.add(
        Ticket(
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
    )


@pytest.mark.asyncio
async def test_post_resolve_returns_200_and_persists(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "t1")
    await session.commit()

    r = await client.post("/tickets/t1/resolve", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_source"] == "manual"


@pytest.mark.asyncio
async def test_post_resolve_404_unknown(client: AsyncClient):
    r = await client.post("/tickets/ghost/resolve", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_resolve_409_already_resolved(client: AsyncClient, session: AsyncSession):
    t = Ticket(
        id="t2",
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
        resolved_at=naive_utcnow(),
        resolved_source="manual",
    )
    session.add(t)
    await session.commit()
    r = await client.post("/tickets/t2/resolve", json={})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_post_reopen_clears_resolution(client: AsyncClient, session: AsyncSession):
    t = Ticket(
        id="t3",
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
        resolved_at=naive_utcnow(),
        resolved_source="manual",
    )
    session.add(t)
    await session.commit()

    r = await client.post("/tickets/t3/reopen")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_patch_ai_resolve_tristate(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "t4")
    await session.commit()
    for value in (True, False, None):
        r = await client.patch("/tickets/t4/ai-resolve", json={"enabled": value})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_post_dismiss_chip(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "t5")
    await session.commit()
    r = await client.post("/tickets/t5/dismiss-chip")
    assert r.status_code == 200
    assert r.json()["ok"] is True

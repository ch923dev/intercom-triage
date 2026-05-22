"""T018–T020 — category create / patch / archive / merge."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AICacheEntry, Category


async def _fallback_id(session: AsyncSession) -> int:
    cid = await session.scalar(select(Category.id).where(Category.is_fallback.is_(True)))
    assert cid is not None
    return cid


@pytest.mark.asyncio
async def test_create_category(client: AsyncClient) -> None:
    resp = await client.post(
        "/categories",
        json={"name": "Onboarding", "description": "Setup help"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Onboarding" and body["source"] == "user_created"


@pytest.mark.asyncio
async def test_create_duplicate_name_conflicts(client: AsyncClient) -> None:
    resp = await client.post(
        "/categories",
        json={"name": "Urgent", "description": "dup"},
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_patch_preserves_id(client: AsyncClient) -> None:
    resp = await client.patch("/categories/1", json={"name": "Critical"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == 1 and body["name"] == "Critical"


@pytest.mark.asyncio
async def test_archive_fallback_returns_409(client: AsyncClient, session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    resp = await client.post(f"/categories/{fb}/archive")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_archive_sweeps_cache_to_fallback(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    # Cache row pointing at category 2 (Bug).
    from datetime import datetime

    session.add(
        AICacheEntry(
            ticket_id="T-arch",
            category_id=2,
            proposal_id=None,
            summary="s",
            confidence=0.5,
            ticket_updated_at=datetime(2026, 1, 1),
        ),
    )
    await session.commit()

    resp = await client.post("/categories/2/archive")
    assert resp.status_code == 200

    session.expire_all()
    fb = await _fallback_id(session)
    remaining = await session.scalar(
        select(func.count()).select_from(AICacheEntry).where(AICacheEntry.category_id == 2),
    )
    assert remaining == 0
    swept = await session.get(AICacheEntry, "T-arch")
    assert swept is not None and swept.category_id == fb


@pytest.mark.asyncio
async def test_merge_moves_tickets_and_archives_src(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    from datetime import datetime

    session.add(
        AICacheEntry(
            ticket_id="T-merge",
            category_id=3,
            proposal_id=None,
            summary="s",
            confidence=0.5,
            ticket_updated_at=datetime(2026, 1, 1),
        ),
    )
    await session.commit()

    resp = await client.post("/categories/3/merge-into/4")
    assert resp.status_code == 200
    assert resp.json()["moved_count"] == 1

    session.expire_all()
    moved = await session.get(AICacheEntry, "T-merge")
    assert moved is not None and moved.category_id == 4
    src = await session.get(Category, 3)
    assert src is not None and src.is_active is False

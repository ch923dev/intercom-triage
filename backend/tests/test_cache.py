"""T017 — AI cache read/write: hit, miss-on-stale, miss-on-TTL-expiry."""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.services.cache import get_cached, set_cached


@pytest.mark.asyncio
async def test_cache_hit_within_ttl(session: AsyncSession) -> None:
    updated = datetime(2026, 1, 1, 12, 0, 0)
    await set_cached(
        session,
        "T1",
        CategorizationResult(1, None, "summary", 0.9),
        updated,
    )
    await session.commit()

    hit = await get_cached(session, "T1", updated, ttl_seconds=300)
    assert hit is not None and hit.category_id == 1 and hit.confidence == 0.9


@pytest.mark.asyncio
async def test_cache_miss_on_newer_updated_at(session: AsyncSession) -> None:
    updated = datetime(2026, 1, 1, 12, 0, 0)
    await set_cached(session, "T1", CategorizationResult(1, None, "s", 0.9), updated)
    await session.commit()

    newer = datetime(2026, 1, 2, 12, 0, 0)
    assert await get_cached(session, "T1", newer, ttl_seconds=300) is None


@pytest.mark.asyncio
async def test_cache_miss_on_ttl_expiry(session: AsyncSession) -> None:
    updated = datetime(2026, 1, 1, 12, 0, 0)
    await set_cached(session, "T1", CategorizationResult(1, None, "s", 0.9), updated)
    await session.commit()

    # ttl_seconds=0 → any elapsed time expires the row.
    assert await get_cached(session, "T1", updated, ttl_seconds=0) is None


@pytest.mark.asyncio
async def test_cache_miss_when_absent(session: AsyncSession) -> None:
    assert await get_cached(session, "nope", datetime(2026, 1, 1), 300) is None

"""T017 — AI cache read/write: hit, miss-on-stale, miss-on-TTL-expiry."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.models import AICacheEntry
from app.services.cache import get_cached, set_cached, sweep_expired
from app.util import naive_utcnow


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


@pytest.mark.asyncio
async def test_sweep_deletes_expired_rows(session: AsyncSession) -> None:
    """Stale row (cached_at well in the past) is deleted; fresh row is kept."""
    sig = datetime(2026, 1, 1, 12, 0, 0)

    # Insert two rows via set_cached (both get cached_at = now).
    await set_cached(session, "stale", CategorizationResult(1, None, "old", 0.7), sig)
    await set_cached(session, "fresh", CategorizationResult(1, None, "new", 0.9), sig)
    await session.commit()

    # Back-date the stale row so it is clearly beyond any reasonable TTL.
    stale_row = await session.get(AICacheEntry, "stale")
    assert stale_row is not None
    stale_row.cached_at = naive_utcnow() - timedelta(seconds=7200)
    await session.commit()

    deleted = await sweep_expired(session, ttl_seconds=3600)

    assert deleted == 1
    assert await session.get(AICacheEntry, "stale") is None
    assert await session.get(AICacheEntry, "fresh") is not None


@pytest.mark.asyncio
async def test_sweep_keeps_rows_within_ttl(session: AsyncSession) -> None:
    """A row cached moments ago must survive a sweep."""
    sig = datetime(2026, 1, 1, 12, 0, 0)
    await set_cached(session, "T_fresh", CategorizationResult(1, None, "s", 0.8), sig)
    await session.commit()

    deleted = await sweep_expired(session, ttl_seconds=3600)

    assert deleted == 0
    assert await session.get(AICacheEntry, "T_fresh") is not None

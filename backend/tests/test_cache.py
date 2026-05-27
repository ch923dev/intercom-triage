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


@pytest.mark.asyncio
async def test_cache_round_trip_resolution_fields(session: AsyncSession) -> None:
    """Cache write + read preserves verdict, confidence, reason."""
    sig = datetime(2026, 5, 23, 12, 0)
    result = CategorizationResult(
        category_id=1,
        proposal_id=None,
        summary="s",
        confidence=0.9,
        ai_resolution_verdict="resolved",
        ai_resolution_confidence=0.88,
        ai_resolution_reason="closed loop",
    )
    await set_cached(session, "t1", result, sig)
    await session.commit()

    cached = await get_cached(session, "t1", sig, ttl_seconds=300)
    assert cached is not None
    assert cached.ai_resolution_verdict == "resolved"
    assert cached.ai_resolution_confidence == 0.88
    assert cached.ai_resolution_reason == "closed loop"


@pytest.mark.asyncio
async def test_cache_round_trip_triage_facets(session: AsyncSession) -> None:
    """Cache write + read preserves priority, sentiment, labels (roadmap 0.2)."""
    sig = datetime(2026, 5, 27, 12, 0)
    result = CategorizationResult(
        category_id=1,
        proposal_id=None,
        summary="s",
        confidence=0.9,
        ai_priority="urgent",
        ai_sentiment="negative",
        ai_labels=["refund", "billing"],
    )
    await set_cached(session, "t-triage", result, sig)
    await session.commit()

    cached = await get_cached(session, "t-triage", sig, ttl_seconds=300)
    assert cached is not None
    assert cached.ai_priority == "urgent"
    assert cached.ai_sentiment == "negative"
    assert cached.ai_labels == ["refund", "billing"]


@pytest.mark.asyncio
async def test_cache_legacy_row_has_neutral_triage(session: AsyncSession) -> None:
    """A pre-0.2 cache row (null priority/sentiment) reads back as neutral
    defaults rather than None — keeps the ticket-row write well-typed."""
    session.add(
        AICacheEntry(
            ticket_id="legacy-triage",
            category_id=1,
            proposal_id=None,
            summary="s",
            confidence=0.5,
            ticket_updated_at=datetime(2026, 5, 27),
        )
    )
    await session.commit()

    cached = await get_cached(session, "legacy-triage", datetime(2026, 5, 27), 300)
    assert cached is not None
    assert cached.ai_priority == "normal"
    assert cached.ai_sentiment == "neutral"
    assert cached.ai_labels == []


@pytest.mark.asyncio
async def test_cache_legacy_row_has_null_resolution(session: AsyncSession) -> None:
    """An older cache row written before this feature has null verdict;
    get_cached returns None values without crashing."""
    session.add(
        AICacheEntry(
            ticket_id="legacy",
            category_id=1,
            proposal_id=None,
            summary="s",
            confidence=0.5,
            ticket_updated_at=datetime(2026, 5, 23),
        )
    )
    await session.commit()

    cached = await get_cached(session, "legacy", datetime(2026, 5, 23), 300)
    assert cached is not None
    assert cached.ai_resolution_verdict is None
    assert cached.ai_resolution_confidence is None
    assert cached.ai_resolution_reason is None

"""US-044 — the bug verdict survives the ai_cache round-trip.

All three cache sites (read reconstruction, insert branch, update branch) must
carry the verdict. Missing the read site drops the verdict on a warm cache hit;
missing the update branch keeps a stale verdict alive after the bug stops being
reported.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.models import AICacheEntry
from app.services.cache import get_cached, set_cached
from app.util import naive_utcnow


def _result(**overrides: object) -> CategorizationResult:
    fields: dict[str, object] = {
        "category_id": 1,
        "proposal_id": None,
        "summary": "Export is broken.",
        "confidence": 0.9,
        "subject": "Export broken",
    }
    fields.update(overrides)
    return CategorizationResult(**fields)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_verdict_round_trips_through_the_cache(session: AsyncSession) -> None:
    signature = naive_utcnow()
    await set_cached(
        session,
        "T1",
        _result(bug_severity="high", bug_confidence=0.88, bug_evidence="nothing exports"),
        signature,
    )
    await session.commit()

    cached = await get_cached(session, "T1", signature, ttl_seconds=300)
    assert cached is not None
    assert cached.bug_severity == "high"
    assert cached.bug_confidence == pytest.approx(0.88)
    assert cached.bug_evidence == "nothing exports"


@pytest.mark.asyncio
async def test_update_branch_clears_a_verdict_that_went_away(session: AsyncSession) -> None:
    signature = naive_utcnow()
    await set_cached(session, "T1", _result(bug_severity="high", bug_confidence=0.9), signature)
    await session.commit()

    # Same ticket re-categorized, this time not a bug.
    await set_cached(session, "T1", _result(), signature)
    await session.commit()

    row = await session.get(AICacheEntry, "T1")
    assert row is not None
    assert row.bug_severity is None
    assert row.bug_confidence is None
    assert row.bug_evidence is None

    cached = await get_cached(session, "T1", signature, ttl_seconds=300)
    assert cached is not None
    assert cached.bug_severity is None


@pytest.mark.asyncio
async def test_legacy_row_without_a_verdict_reads_back_as_none(session: AsyncSession) -> None:
    """Pre-0027 rows are never backfilled (design decision 3) — they must read
    back as "not a bug" rather than blowing up the reconstruction."""
    signature = naive_utcnow()
    session.add(
        AICacheEntry(
            ticket_id="T9",
            category_id=1,
            summary="s",
            confidence=0.5,
            ticket_updated_at=signature,
            cached_at=naive_utcnow(),
        )
    )
    await session.commit()

    cached = await get_cached(session, "T9", signature, ttl_seconds=300)
    assert cached is not None
    assert cached.bug_severity is None
    assert cached.bug_confidence is None
    assert cached.bug_evidence is None

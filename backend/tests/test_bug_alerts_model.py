"""US-044 — `bug_alerts` table constraints + migration 0027 fallout.

Deliberately NOT in `tests/test_models.py` — staging that file trips a
pre-existing pre-commit hook issue (see the plan's Conventions section).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AICacheEntry, BugAlert
from app.util import naive_utcnow


def _alert(ticket_id: str = "T1", **overrides: object) -> BugAlert:
    now = naive_utcnow()
    fields: dict[str, object] = {
        "ticket_id": ticket_id,
        "severity": "high",
        "confidence": 0.9,
        "evidence": "the export button does nothing",
        "first_detected_at": now,
        "last_detected_at": now,
    }
    fields.update(overrides)
    return BugAlert(**fields)


@pytest.mark.asyncio
async def test_row_round_trips_with_occurrences_defaulting_to_one(session: AsyncSession) -> None:
    session.add(_alert())
    await session.commit()

    row = await session.get(BugAlert, "T1")
    assert row is not None
    assert row.occurrences == 1
    # Undelivered by default — `posted_at IS NULL` is the outbox.
    assert row.posted_at is None
    assert row.posted_severity is None
    assert row.dismissed_at is None


@pytest.mark.asyncio
async def test_severity_outside_the_enum_is_rejected(session: AsyncSession) -> None:
    session.add(_alert(severity="critical"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_posted_severity_outside_the_enum_is_rejected(session: AsyncSession) -> None:
    session.add(_alert(posted_severity="urgent"))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_evidence_over_200_chars_is_rejected(session: AsyncSession) -> None:
    session.add(_alert(evidence="x" * 201))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_occurrences_below_one_is_rejected(session: AsyncSession) -> None:
    session.add(_alert(occurrences=0))
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_duplicate_ticket_id_is_rejected(session: AsyncSession) -> None:
    """The PK IS the dedup guarantee — two rows for one ticket cannot exist,
    so Slack cannot be told about the same ticket twice."""
    session.add(_alert("T1"))
    await session.commit()
    with pytest.raises(IntegrityError):
        await session.execute(
            text(
                "INSERT INTO bug_alerts "
                "(ticket_id, severity, confidence, occurrences, "
                " first_detected_at, last_detected_at) "
                "VALUES ('T1', 'low', 0.1, 1, '2026-01-01', '2026-01-01')"
            )
        )


# ── Migration 0027 fallout on ai_cache ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ai_cache_carries_the_bug_verdict_columns(session: AsyncSession) -> None:
    session.add(
        AICacheEntry(
            ticket_id="T1",
            category_id=1,
            summary="s",
            confidence=0.5,
            ticket_updated_at=naive_utcnow(),
            cached_at=naive_utcnow(),
            bug_severity="medium",
            bug_confidence=0.7,
            bug_evidence="it 500s",
        )
    )
    await session.commit()
    row = await session.get(AICacheEntry, "T1")
    assert row is not None
    assert (row.bug_severity, row.bug_confidence, row.bug_evidence) == ("medium", 0.7, "it 500s")


@pytest.mark.asyncio
async def test_ai_cache_bug_severity_enum_is_enforced(session: AsyncSession) -> None:
    session.add(
        AICacheEntry(
            ticket_id="T2",
            category_id=1,
            summary="s",
            confidence=0.5,
            ticket_updated_at=naive_utcnow(),
            cached_at=naive_utcnow(),
            bug_severity="catastrophic",
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_migration_0027_preserved_the_ai_cache_xor_check(session: AsyncSession) -> None:
    """0027 adds CHECKs to `ai_cache` via `batch_alter_table`, which recreates the
    table on SQLite. If reflection ever drops the pre-existing constraints, the
    XOR (`category_id` ⊕ `proposal_id`) goes silently — assert it still bites."""
    session.add(
        AICacheEntry(
            ticket_id="T3",
            category_id=None,
            proposal_id=None,
            summary="s",
            confidence=0.5,
            ticket_updated_at=naive_utcnow(),
            cached_at=naive_utcnow(),
        )
    )
    with pytest.raises(IntegrityError):
        await session.commit()

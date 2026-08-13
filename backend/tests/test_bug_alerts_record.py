"""US-044 — the record pass: dedup, escalation, and ingest safety."""

from __future__ import annotations

from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.config import AppConfig
from app.models import BugAlert
from app.services.bug_alerts import record_bug_alerts
from app.util import naive_utcnow


def _config(**overrides: object) -> AppConfig:
    fields: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "session_jwt_secret": "test-session-secret",
        "bug_alerts_enabled": True,
        "bug_alert_min_confidence": 0.6,
    }
    fields.update(overrides)
    return AppConfig(**fields)  # type: ignore[arg-type]


def _verdict(severity: str = "high", confidence: float = 0.9) -> CategorizationResult:
    return CategorizationResult(
        category_id=1,
        proposal_id=None,
        summary="Export is broken.",
        confidence=0.8,
        subject="Export broken",
        bug_severity=severity,  # type: ignore[arg-type]
        bug_confidence=confidence,
        bug_evidence="the export button does nothing",
    )


@pytest.mark.asyncio
async def test_first_detection_creates_a_row(session: AsyncSession) -> None:
    await record_bug_alerts(session, {"T1": _verdict()}, _config())

    row = await session.get(BugAlert, "T1")
    assert row is not None
    assert row.severity == "high"
    assert row.occurrences == 1
    assert row.evidence == "the export button does nothing"
    assert row.posted_at is None


@pytest.mark.asyncio
async def test_second_pass_bumps_instead_of_duplicating(session: AsyncSession) -> None:
    """The PK is the dedup guarantee — a re-detection can only ever bump."""
    await record_bug_alerts(session, {"T1": _verdict()}, _config())
    first = await session.get(BugAlert, "T1")
    assert first is not None
    first_detected = first.first_detected_at

    await record_bug_alerts(session, {"T1": _verdict()}, _config())

    assert len((await session.scalars(select(BugAlert))).all()) == 1
    row = await session.get(BugAlert, "T1")
    assert row is not None
    await session.refresh(row)
    assert row.occurrences == 2
    assert row.first_detected_at == first_detected


@pytest.mark.asyncio
async def test_escalation_raises_severity_and_refreshes_evidence(session: AsyncSession) -> None:
    await record_bug_alerts(session, {"T1": _verdict("medium", 0.7)}, _config())

    worse = replace(
        _verdict("high", 0.95),
        bug_evidence="all our data is gone",
    )
    await record_bug_alerts(session, {"T1": worse}, _config())

    row = await session.get(BugAlert, "T1")
    assert row is not None
    await session.refresh(row)
    assert row.severity == "high"
    assert row.confidence == pytest.approx(0.95)
    assert row.evidence == "all our data is gone"
    assert row.occurrences == 2


@pytest.mark.asyncio
async def test_a_lower_severity_re_detection_does_not_downgrade(session: AsyncSession) -> None:
    await record_bug_alerts(session, {"T1": _verdict("high", 0.9)}, _config())
    await record_bug_alerts(session, {"T1": _verdict("low", 0.9)}, _config())

    row = await session.get(BugAlert, "T1")
    assert row is not None
    await session.refresh(row)
    assert row.severity == "high"
    assert row.occurrences == 2


@pytest.mark.asyncio
async def test_low_severity_is_recorded_not_dropped(session: AsyncSession) -> None:
    """Locked decision 1: `low` is recorded, just never posted. Recording it is
    what makes the delivery floor calibratable from real traffic."""
    await record_bug_alerts(session, {"T1": _verdict("low", 0.9)}, _config())
    assert await session.get(BugAlert, "T1") is not None


@pytest.mark.asyncio
async def test_below_the_confidence_floor_is_not_recorded(session: AsyncSession) -> None:
    await record_bug_alerts(session, {"T1": _verdict("high", 0.4)}, _config())
    assert await session.get(BugAlert, "T1") is None


@pytest.mark.asyncio
async def test_a_verdict_without_a_confidence_is_not_recorded(session: AsyncSession) -> None:
    result = _verdict()
    result.bug_confidence = None
    await record_bug_alerts(session, {"T1": result}, _config())
    assert await session.get(BugAlert, "T1") is None


@pytest.mark.asyncio
async def test_a_result_with_no_verdict_is_ignored(session: AsyncSession) -> None:
    plain = CategorizationResult(category_id=1, proposal_id=None, summary="s", confidence=0.9)
    await record_bug_alerts(session, {"T1": plain}, _config())
    assert await session.get(BugAlert, "T1") is None


@pytest.mark.asyncio
async def test_a_fallback_result_can_never_produce_an_alert(session: AsyncSession) -> None:
    """Invariant #7 by construction: the verdict fields default to None, so a
    fallback carries no bug report even though it carries a category."""
    fallback = CategorizationResult(
        category_id=1, proposal_id=None, summary="s", confidence=0.0, fallback=True
    )
    assert fallback.bug_severity is None
    await record_bug_alerts(session, {"T1": fallback}, _config())
    assert await session.get(BugAlert, "T1") is None


@pytest.mark.asyncio
async def test_disabled_is_a_no_op(session: AsyncSession) -> None:
    await record_bug_alerts(session, {"T1": _verdict()}, _config(bug_alerts_enabled=False))
    assert await session.get(BugAlert, "T1") is None


@pytest.mark.asyncio
async def test_dismissal_survives_a_re_detection(session: AsyncSession) -> None:
    """The operator's "not a bug" call outranks the model's insistence."""
    await record_bug_alerts(session, {"T1": _verdict()}, _config())
    row = await session.get(BugAlert, "T1")
    assert row is not None

    dismissed = naive_utcnow()
    row.dismissed_at = dismissed
    await session.commit()

    await record_bug_alerts(session, {"T1": _verdict()}, _config())
    await session.refresh(row)
    assert row.dismissed_at == dismissed
    assert row.occurrences == 2


@pytest.mark.asyncio
async def test_delivery_state_survives_a_re_detection(session: AsyncSession) -> None:
    """`posted_*` is delivery truth and the model does not get to revise it —
    otherwise every re-sync would look undelivered and repost."""
    await record_bug_alerts(session, {"T1": _verdict("medium", 0.9)}, _config())
    row = await session.get(BugAlert, "T1")
    assert row is not None

    posted = naive_utcnow()
    row.posted_at = posted
    row.posted_severity = "medium"
    row.slack_ts = "1723456789.000100"
    row.slack_channel = "C123"
    await session.commit()

    await record_bug_alerts(session, {"T1": _verdict("medium", 0.9)}, _config())
    await session.refresh(row)
    assert row.posted_at == posted
    assert row.posted_severity == "medium"
    assert row.slack_ts == "1723456789.000100"


@pytest.mark.asyncio
async def test_a_failing_record_pass_never_breaks_the_caller(session: AsyncSession) -> None:
    """The pass runs post-commit on the ingest path; it must swallow its own
    failures rather than take an ingest down with it."""
    broken = _verdict()
    broken.bug_severity = "catastrophic"  # type: ignore[assignment]
    broken.bug_confidence = 0.9

    # Returns normally despite the CHECK violation, and leaves the session usable.
    await record_bug_alerts(session, {"T1": broken}, _config())
    assert await session.get(BugAlert, "T1") is None

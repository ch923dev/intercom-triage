"""Early bug detection — record pass. Reference: US-044, FR-075..FR-079.

The verdict itself is produced upstream as a fifth facet on the categorization
call (`app.ai.pipeline`); this module is where it becomes durable state.

Two properties are load-bearing and easy to lose in a refactor:

1. **`bug_alerts.ticket_id` is the PK, and that IS the dedup guarantee.** Slack
   has no idempotency key, so "did I already post this?" cannot be answered by
   asking Slack. It is answered by the row existing. Anything that makes the
   table keyed on something else (a surrogate id, a `(ticket_id, severity)`
   pair) silently reintroduces duplicate posts.
2. **The pass is best-effort and runs AFTER ingest has committed.** A bug-alert
   failure must never roll back or abort an ingest; the worst case is a missing
   row that the next sync refills.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, cast

from sqlalchemy import ColumnElement, case
from sqlalchemy.dialects.sqlite import Insert as OnConflictInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.config import AppConfig
from app.metrics import metrics
from app.models import BugAlert
from app.util import naive_utcnow

logger = logging.getLogger(__name__)

# Ordering for "is this worse than what we already have / already posted?".
SEVERITY_RANK: dict[str, int] = {"low": 1, "medium": 2, "high": 3}


def _rank(column: Any) -> ColumnElement[int]:
    """SQL-side severity rank, so escalation can be decided inside the upsert."""
    return case(SEVERITY_RANK, value=column, else_=0)


def _insert(session: AsyncSession) -> Callable[..., OnConflictInsert]:
    """Dialect-appropriate INSERT supporting `ON CONFLICT DO UPDATE`.

    SQLite and Postgres expose the same `.excluded` / `.on_conflict_do_update`
    surface, so the only dialect-specific thing here is which constructor to
    call — hence the cast, which asserts that shared surface rather than a
    shared class. A generic `insert()` has no upsert at all, and
    SELECT-then-INSERT would reintroduce the very race the primary key exists to
    prevent (two ingests of one ticket in flight at once).
    """
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return cast("Callable[..., OnConflictInsert]", pg_insert)
    return sqlite_insert


async def record_bug_alerts(
    session: AsyncSession,
    results: dict[str, CategorizationResult],
    config: AppConfig,
) -> None:
    """Best-effort record pass over a just-ingested batch.

    Runs AFTER ingest has already committed, in its own transaction, so a
    failure can never roll back or break ingest — the worst case is a missing
    alert row that the next sync refills. Mirrors `_embed_ingested_tickets`.

    Records EVERY severity, including `low`: the delivery floor
    (`bug_alert_min_severity`) is applied at delivery time, not here, so the
    operator can read the full distribution off `GET /bug-alerts` and calibrate
    before anything is allowed to post.
    """
    if not config.bug_alerts_enabled:
        return

    now = naive_utcnow()
    rows = [
        {
            "ticket_id": ticket_id,
            "severity": result.bug_severity,
            "confidence": result.bug_confidence,
            "evidence": result.bug_evidence,
            "occurrences": 1,
            "first_detected_at": now,
            "last_detected_at": now,
        }
        for ticket_id, result in results.items()
        # A verdict needs both halves: a severity we recognise and a confidence
        # we can compare. Either missing means the model's output was not
        # trustworthy enough to raise an alert on.
        if result.bug_severity is not None
        and result.bug_confidence is not None
        and result.bug_confidence >= config.bug_alert_min_confidence
    ]
    if not rows:
        return

    try:
        insert = _insert(session)
        stmt = insert(BugAlert).values(rows)
        # Escalation is decided in SQL so insert-or-bump stays ONE statement.
        escalating = _rank(stmt.excluded.severity) > _rank(BugAlert.severity)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[BugAlert.ticket_id],
                set_={
                    # Only a WORSE verdict overwrites; a re-detection at the same
                    # or lower severity just bumps the counter.
                    "severity": case((escalating, stmt.excluded.severity), else_=BugAlert.severity),
                    "confidence": case(
                        (escalating, stmt.excluded.confidence), else_=BugAlert.confidence
                    ),
                    "evidence": case((escalating, stmt.excluded.evidence), else_=BugAlert.evidence),
                    "occurrences": BugAlert.occurrences + 1,
                    "last_detected_at": stmt.excluded.last_detected_at,
                    # `posted_*` and `dismissed_at` are deliberately untouched:
                    # delivery state and the operator's dismissal are not the
                    # model's to revise. Escalation past `posted_severity` is
                    # what re-opens delivery, and that is read, not written, here.
                },
            )
        )
        await session.commit()
        metrics.incr("bug_alerts_recorded_total", len(rows))
    except Exception:
        # Auxiliary pass — log and move on. Roll back so a partial failure does
        # not leave the session dirty for the caller.
        await session.rollback()
        logger.warning("bug alert record pass failed for ingest batch", exc_info=True)

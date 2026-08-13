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

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, case, or_, select
from sqlalchemy.dialects.sqlite import Insert as OnConflictInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.clients.slack import SlackAuthError, SlackClient
from app.config import AppConfig
from app.metrics import metrics
from app.models import BugAlert, Category, Ticket
from app.observability import log_event
from app.schemas import BugAlertRead
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


# ── Delivery ──────────────────────────────────────────────────────────────────

_SEVERITY_EMOJI: dict[str, str] = {"high": "🔴", "medium": "🟠", "low": "🟡"}


def _at_or_above(floor: str) -> list[str]:
    """Severities that clear the delivery floor."""
    threshold = SEVERITY_RANK[floor]
    return [name for name, rank in SEVERITY_RANK.items() if rank >= threshold]


def _fallback_text(alert: BugAlert, title: str | None) -> str:
    """Notification line for clients that cannot render blocks.

    Carries no evidence quote: this string ends up in push notifications and
    channel previews, where a raw customer sentence is the least appropriate
    place for it to surface.
    """
    return f"{alert.severity.upper()} bug — {title or alert.ticket_id}"


def _alert_blocks(
    alert: BugAlert,
    *,
    title: str | None,
    category: str | None,
    url: str | None,
) -> list[dict[str, Any]]:
    """Block Kit body for a first-time alert."""
    emoji = _SEVERITY_EMOJI.get(alert.severity, "⚪")
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{alert.severity.upper()} bug* — {title or alert.ticket_id}",
            },
        }
    ]
    if alert.evidence:
        # A verbatim customer quote is the whole point: it lets an engineer
        # judge the report without opening Intercom.
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"> {alert.evidence}"},
            }
        )
    facts = [
        f"*Category:* {category or 'uncategorized'}",
        f"*Confidence:* {alert.confidence:.0%}",
        f"*Seen:* {alert.occurrences}x",
    ]
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(facts)}]})
    if url:
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Open in Intercom"},
                        "url": url,
                    }
                ],
            }
        )
    return blocks


def _escalation_text(alert: BugAlert) -> str:
    """A reply, not a re-post: the original card already carries the detail."""
    return f"⬆️ Escalated {alert.posted_severity} → {alert.severity} (seen {alert.occurrences}x)"


async def deliver_pending_bug_alerts(
    session: AsyncSession,
    client: SlackClient,
    config: AppConfig,
) -> int:
    """Post undelivered alerts (and severity escalations) to Slack.

    Returns the number of Slack messages sent.

    Two rules make this safe to run on a loop:

    * **Never inside `SYNC_LOCK`.** A hanging Slack request would stall the whole
      sync cycle, and Slack's ~1 msg/sec/channel budget makes a burst slow by
      nature. `bug_alert_max_per_cycle` bounds each pass; the rest waits in the
      outbox.
    * **Post, then store the `ts`, then mark delivered.** A crash between those
      steps leaves the row in the outbox and risks ONE duplicate post. The
      reverse order risks losing an alert permanently. Duplicate is the cheaper
      failure, so the ordering is deliberate.
    """
    if not config.slack_configured:
        return 0

    eligible = _at_or_above(config.bug_alert_min_severity)
    rows = (
        await session.scalars(
            select(BugAlert)
            .where(
                BugAlert.dismissed_at.is_(None),
                BugAlert.severity.in_(eligible),
                or_(
                    # Never posted — the outbox.
                    BugAlert.posted_at.is_(None),
                    # Posted, but the verdict has since got worse: reply in
                    # thread rather than start a second conversation.
                    and_(
                        BugAlert.posted_severity.is_not(None),
                        _rank(BugAlert.severity) > _rank(BugAlert.posted_severity),
                    ),
                ),
            )
            # Worst first: a burst that hits the per-cycle cap should spend it on
            # the alerts that matter, not on whatever was detected first.
            .order_by(_rank(BugAlert.severity).desc(), BugAlert.first_detected_at.asc())
            .limit(config.bug_alert_max_per_cycle)
        )
    ).all()
    if not rows:
        return 0

    ticket_ids = [row.ticket_id for row in rows]
    context = {
        tid: (title, url, category)
        for tid, title, url, category in (
            await session.execute(
                select(Ticket.id, Ticket.title, Ticket.url, Category.name)
                .outerjoin(Category, Ticket.category_id == Category.id)
                # A ticket row is normally present (the alert came from an
                # ingest), but the alert table has no FK on purpose, so treat
                # absence as "no context" rather than as an error.
                .where(Ticket.id.in_(ticket_ids))
            )
        ).all()
    }

    sent = 0
    for alert in rows:
        title, url, category = context.get(alert.ticket_id, (None, None, None))
        is_escalation = alert.posted_at is not None
        try:
            if is_escalation:
                ts = await client.post_message(
                    channel=config.slack_bug_channel,
                    text=_escalation_text(alert),
                    thread_ts=alert.slack_ts,
                    ticket_id=alert.ticket_id,
                )
            else:
                ts = await client.post_message(
                    channel=config.slack_bug_channel,
                    text=_fallback_text(alert, title),
                    blocks=_alert_blocks(alert, title=title, category=category, url=url),
                    ticket_id=alert.ticket_id,
                )
        except SlackAuthError:
            # A revoked token fails every remaining row identically. Stop the
            # pass; the outbox holds and self-heals once the token is fixed.
            log_event("bug_alert_delivery_auth_error", level=logging.WARNING, op="delivery")
            await session.rollback()
            return sent
        except Exception as exc:
            # One bad row must not stall the rest. `posted_at` stays NULL, so
            # the next pass retries it — nothing is lost.
            log_event(
                "bug_alert_delivery_error",
                level=logging.WARNING,
                op="delivery",
                ticket_id=alert.ticket_id,
                error=str(exc),
            )
            continue

        if not is_escalation:
            # Store the ts FIRST: without it a later escalation cannot thread.
            alert.slack_ts = ts
            alert.slack_channel = config.slack_bug_channel
            alert.posted_at = naive_utcnow()
        alert.posted_severity = alert.severity
        await session.commit()
        sent += 1
        metrics.incr("bug_alerts_escalated_total" if is_escalation else "bug_alerts_posted_total")

    return sent


# ── Read + dismiss ────────────────────────────────────────────────────────────


async def list_bug_alerts(
    session: AsyncSession,
    *,
    severity: str | None = None,
    delivered: bool | None = None,
) -> list[BugAlertRead]:
    """Every recorded alert, worst and newest first, with ticket context.

    This is the calibration surface: it deliberately includes `low` and
    dismissed rows so the operator can see what detection is doing BEFORE
    letting anything post (see `bug_alert_min_confidence`, an admitted guess).
    """
    stmt = (
        select(BugAlert, Ticket.title, Ticket.url)
        .outerjoin(Ticket, Ticket.id == BugAlert.ticket_id)
        .order_by(_rank(BugAlert.severity).desc(), BugAlert.last_detected_at.desc())
    )
    if severity is not None:
        stmt = stmt.where(BugAlert.severity == severity)
    if delivered is True:
        stmt = stmt.where(BugAlert.posted_at.is_not(None))
    elif delivered is False:
        stmt = stmt.where(BugAlert.posted_at.is_(None))

    return [
        BugAlertRead.model_validate(alert).model_copy(update={"title": title, "url": url})
        for alert, title, url in (await session.execute(stmt)).all()
    ]


async def dismiss_bug_alert(session: AsyncSession, ticket_id: str) -> BugAlertRead:
    """Mark an alert as "not a bug" / handled. Idempotent — a second dismiss
    keeps the original timestamp rather than moving it.

    Dismissal outranks re-detection: the record pass never clears
    `dismissed_at`, so a model that keeps insisting cannot resurrect the alert.
    """
    alert = await session.get(BugAlert, ticket_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="bug alert not found")
    if alert.dismissed_at is None:
        alert.dismissed_at = naive_utcnow()
        await session.commit()
    return BugAlertRead.model_validate(alert)

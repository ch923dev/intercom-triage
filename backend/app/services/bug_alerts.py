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
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, case, or_, select
from sqlalchemy.dialects.sqlite import Insert as OnConflictInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.ai.pipeline import CategorizationResult
from app.clients.slack import SlackAuthError, SlackClient
from app.config import AppConfig
from app.metrics import metrics
from app.models import BugAlert, Category, Ticket, User
from app.observability import log_event
from app.schemas import BugAlertRead, UserRef
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
                    # `posted_*`, `dismissed_at`, and `acked_at`/`acked_by` are
                    # deliberately untouched: delivery state, the operator's
                    # dismissal, and who acknowledged it are not the model's to
                    # revise (FR-085). Escalation past `posted_severity` is what
                    # re-opens delivery, and that is read, not written, here.
                    # This set-clause being explicit is what makes that hold —
                    # a blanket "update everything from excluded" would erase an
                    # acknowledgement on the next re-detection.
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
# Left-rail colour. Only reachable via an attachment `color` — Block Kit has no
# equivalent — and it is the one cue that reads as severity before any text does.
_SEVERITY_COLOR: dict[str, str] = {"high": "#E01E5A", "medium": "#ECB22E", "low": "#868F96"}

# Slack renders `fields` two per row and hard-caps the list at 10.
_MAX_FIELDS = 10
# The card is a triage prompt, not the ticket. Anything longer belongs in Intercom.
_SUMMARY_CHARS = 300


def _at_or_above(floor: str) -> list[str]:
    """Severities that clear the delivery floor."""
    threshold = SEVERITY_RANK[floor]
    return [name for name, rank in SEVERITY_RANK.items() if rank >= threshold]


@dataclass(frozen=True)
class TicketContext:
    """Board-side detail composed onto the Slack card.

    Everything here is already denormalized onto `tickets` (or one `users` join),
    so enriching the card costs one wider SELECT and no extra AI call. It is
    deliberately a value object rather than the ORM row: the delivery loop must
    keep working for an alert whose ticket has since been deleted, and a missing
    ticket then degrades to every field `None` instead of an attribute error.
    """

    title: str | None = None
    url: str | None = None
    category: str | None = None
    state: str | None = None
    summary: str | None = None
    created_at: datetime | None = None
    sentiment: str | None = None
    priority: str | None = None
    labels: list[str] = field(default_factory=list)
    author: dict[str, Any] = field(default_factory=dict)
    assignee: str | None = None


def _humanize_age(created_at: datetime | None) -> str | None:
    """ "2h ago" / "3d ago" — coarse on purpose; the exact stamp is in Intercom."""
    if created_at is None:
        return None
    seconds = (naive_utcnow() - created_at).total_seconds()
    if seconds < 90:
        return "just now"
    if seconds < 5400:
        return f"{round(seconds / 60)}m ago"
    if seconds < 172800:
        return f"{round(seconds / 3600)}h ago"
    return f"{round(seconds / 86400)}d ago"


def _fallback_text(alert: BugAlert, ctx: TicketContext) -> str:
    """Notification line for clients that cannot render blocks.

    Carries no evidence quote: this string ends up in push notifications and
    channel previews, where a raw customer sentence is the least appropriate
    place for it to surface.
    """
    return f"{alert.severity.upper()} bug — {ctx.title or alert.ticket_id}"


def _clip(text: str, limit: int) -> str:
    """Truncate on a word boundary with an ellipsis — a card cut mid-word reads
    as a rendering bug rather than as a deliberate summary."""
    if len(text) <= limit:
        return text
    head = text[: limit - 1]
    cut = head.rsplit(" ", 1)[0] if " " in head else head
    return f"{cut.rstrip(' ,;:.')}…"


def _field(label: str, value: str | None) -> dict[str, str] | None:
    """A Block Kit field, or None when there is nothing worth a slot."""
    if not value:
        return None
    return {"type": "mrkdwn", "text": f"*{label}*\n{value}"}


def _identity_fields(ctx: TicketContext) -> list[dict[str, str]]:
    """Who reported it and how to reach them — the first thing anyone triaging asks."""
    author = ctx.author or {}
    name = author.get("name")
    email = author.get("email")
    user_id = author.get("id")
    candidates = [
        _field("Reported by", str(name) if name else None),
        _field("Email", str(email) if email else None),
        # Intercom's user-facing "User id" when the contact carries an
        # external_id, else the contact record id — the normalizer already
        # prefers the former so this matches what the Intercom panel shows.
        _field("User id", f"`{user_id}`" if user_id else None),
        _field("Phone", str(author["phone"]) if author.get("phone") else None),
        _field("Location", str(author["location"]) if author.get("location") else None),
        _field("Company", str(author["company"]) if author.get("company") else None),
    ]
    return [f for f in candidates if f is not None]


def _ack_line(alert: BugAlert, acker: str | None) -> str | None:
    """ "Acknowledged by X · <time>", or None when nobody has.

    The stamp uses Slack's `!date` token so each reader sees it in their own
    timezone — the message is durable, so a relative age ("5m ago") would be a
    lie the moment anyone scrolled back to it. The text after `|` is what
    clients that cannot render the token show instead.
    """
    if alert.acked_at is None:
        return None
    epoch = int(alert.acked_at.replace(tzinfo=UTC).timestamp())
    stamp = f"<!date^{epoch}^{{date_short_pretty}} {{time}}|{alert.acked_at:%Y-%m-%d %H:%M} UTC>"
    return f"✅ Acknowledged by {acker or 'an operator'} · {stamp}"


def _alert_attachments(
    alert: BugAlert, ctx: TicketContext, *, acker: str | None = None
) -> list[dict[str, Any]]:
    """The full alert card, wrapped in a severity-coloured attachment.

    Also the builder for the acknowledgement edit (FR-086) — deliberately one
    builder, so the evidence quote cannot end up in the top-level `text` /
    `fallback` on the edit path after being kept out of it on the post path
    (NFR-016).
    """
    emoji = _SEVERITY_EMOJI.get(alert.severity, "⚪")
    headline = ctx.title or alert.ticket_id
    # Inline link rather than an actions button: Slack badges link buttons from
    # non-Marketplace apps with a warning glyph, and the title is the natural
    # click target anyway.
    linked = f"<{ctx.url}|{headline}>" if ctx.url else headline
    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{emoji} *{alert.severity.upper()} bug* — {linked}",
            },
        }
    ]

    if alert.evidence:
        # A verbatim CUSTOMER quote is the whole point: it lets an engineer judge
        # the report without opening Intercom. Provenance is enforced upstream
        # (`pipeline.verify_bug_evidence`), so anything reaching here was said by
        # the customer, not by our own agent.
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": f"> {alert.evidence}"}}
        )

    status = " · ".join(p for p in (ctx.state, _humanize_age(ctx.created_at)) if p)
    fields = [
        *_identity_fields(ctx),
        _field("Status", status),
        _field("Owner", ctx.assignee or "unassigned"),
    ]
    trimmed = [f for f in fields if f is not None][:_MAX_FIELDS]
    if trimmed:
        blocks.append({"type": "section", "fields": trimmed})

    if ctx.summary:
        blocks.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"_{_clip(ctx.summary, _SUMMARY_CHARS)}_"},
            }
        )

    facts = [
        f"*{ctx.category or 'uncategorized'}*",
        f"{alert.confidence:.0%} confident",
        f"seen {alert.occurrences}x",
    ]
    if ctx.priority:
        facts.append(f"priority {ctx.priority}")
    if ctx.sentiment:
        facts.append(f"sentiment {ctx.sentiment}")
    if ctx.labels:
        facts.append(" ".join(f"`{label}`" for label in ctx.labels[:5]))
    facts.append(f"`{alert.ticket_id}`")
    blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": " · ".join(facts)}]})

    ack = _ack_line(alert, acker)
    if ack is not None:
        blocks.append({"type": "context", "elements": [{"type": "mrkdwn", "text": ack}]})

    return [
        {
            "color": _SEVERITY_COLOR.get(alert.severity, "#868F96"),
            "blocks": blocks,
            # Required when blocks live inside an attachment; Slack falls back to
            # it for clients that cannot render them. No evidence quote, for the
            # same reason as `_fallback_text`.
            "fallback": _fallback_text(alert, ctx),
        }
    ]


async def _ticket_contexts(
    session: AsyncSession, ticket_ids: list[str]
) -> dict[str, TicketContext]:
    """Board-side card context for the given tickets, keyed by ticket id.

    Shared by delivery and by the acknowledgement mirror so an edited card is
    built from the same data as the original post — a second copy of this join
    is how the two would drift apart.
    """
    if not ticket_ids:
        return {}
    assignee = aliased(User)
    return {
        row.id: TicketContext(
            title=row.title,
            url=row.url,
            category=row.category,
            state=row.state,
            summary=row.summary or None,
            created_at=row.created_at,
            sentiment=row.ai_sentiment,
            priority=row.ai_priority,
            labels=list(row.ai_labels or []),
            author=dict(row.author or {}),
            assignee=row.assignee,
        )
        for row in (
            await session.execute(
                select(
                    Ticket.id,
                    Ticket.title,
                    Ticket.url,
                    Ticket.state,
                    Ticket.summary,
                    Ticket.created_at,
                    Ticket.ai_sentiment,
                    Ticket.ai_priority,
                    Ticket.ai_labels,
                    Ticket.author,
                    Category.name.label("category"),
                    assignee.name.label("assignee"),
                )
                .outerjoin(Category, Ticket.category_id == Category.id)
                .outerjoin(assignee, Ticket.assigned_to == assignee.id)
                # A ticket row is normally present (the alert came from an
                # ingest), but the alert table has no FK on purpose, so treat
                # absence as "no context" rather than as an error.
                .where(Ticket.id.in_(ticket_ids))
            )
        ).all()
    }


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

    context = await _ticket_contexts(session, [row.ticket_id for row in rows])

    sent = 0
    for alert in rows:
        ctx = context.get(alert.ticket_id, TicketContext())
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
                    text=_fallback_text(alert, ctx),
                    attachments=_alert_attachments(alert, ctx),
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


# ── Read + dismiss + ack ──────────────────────────────────────────────────────


def _to_read(
    alert: BugAlert,
    *,
    title: str | None = None,
    url: str | None = None,
    acked_by: UserRef | None = None,
) -> BugAlertRead:
    """Build the wire shape explicitly.

    NOT `model_validate(alert)`: the ORM row's `acked_by` is a user id, while the
    schema field of that name is a `UserRef`, so attribute-based validation would
    try to coerce an int into a model and fail on every acknowledged row. The
    same reason `TicketSchema` is constructed field-by-field (invariant #17).
    One converter, so the list / dismiss / ack paths cannot disagree.
    """
    return BugAlertRead(
        ticket_id=alert.ticket_id,
        severity=cast("Any", alert.severity),
        confidence=alert.confidence,
        evidence=alert.evidence,
        occurrences=alert.occurrences,
        first_detected_at=alert.first_detected_at,
        last_detected_at=alert.last_detected_at,
        posted_at=alert.posted_at,
        posted_severity=cast("Any", alert.posted_severity),
        slack_channel=alert.slack_channel,
        slack_ts=alert.slack_ts,
        dismissed_at=alert.dismissed_at,
        acked_at=alert.acked_at,
        acked_by=acked_by,
        title=title,
        url=url,
    )


async def _user_refs(session: AsyncSession, ids: set[int]) -> dict[int, UserRef]:
    """`{id: UserRef}` for the ids given — the attribution join, done once."""
    if not ids:
        return {}
    return {
        u.id: UserRef(id=u.id, name=u.name)
        for u in (await session.scalars(select(User).where(User.id.in_(ids)))).all()
    }


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

    rows = (await session.execute(stmt)).all()
    users = await _user_refs(
        session, {alert.acked_by for alert, _, _ in rows if alert.acked_by is not None}
    )
    return [
        _to_read(
            alert,
            title=title,
            url=url,
            acked_by=users.get(alert.acked_by) if alert.acked_by is not None else None,
        )
        for alert, title, url in rows
    ]


async def dismiss_bug_alert(session: AsyncSession, ticket_id: str) -> BugAlertRead:
    """Mark an alert as "not a bug" / handled. Idempotent — a second dismiss
    keeps the original timestamp rather than moving it.

    Dismissal outranks re-detection: the record pass never clears
    `dismissed_at`, so a model that keeps insisting cannot resurrect the alert.
    Dismissing does NOT clear an acknowledgement — who picked this up survives
    closing it out.
    """
    alert = await session.get(BugAlert, ticket_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="bug alert not found")
    if alert.dismissed_at is None:
        alert.dismissed_at = naive_utcnow()
        await session.commit()
    users = await _user_refs(session, {alert.acked_by} if alert.acked_by is not None else set())
    return _to_read(
        alert, acked_by=users.get(alert.acked_by) if alert.acked_by is not None else None
    )


async def ack_bug_alert(
    session: AsyncSession,
    ticket_id: str,
    *,
    user_id: int,
    slack: SlackClient | None,
    config: AppConfig,
) -> tuple[BugAlertRead, bool]:
    """Acknowledge an alert, then mirror it into the Slack message it came from.

    Returns `(alert, slack_updated)`.

    **Record first, mirror second** (FR-087). The acknowledgement is committed
    before Slack is touched, and a Slack failure is logged and reported as
    `slack_updated=False` rather than rolled back: the board is the record and
    the channel is a projection of it. The other order would let a Slack outage
    refuse acknowledgements, which is backwards — the fact is local.

    Idempotent (FR-084): a second acknowledgement keeps the first operator and
    timestamp and makes NO Slack call, so re-clicking cannot spam the channel.
    That also means a failed mirror is not repaired by acknowledging again —
    accepted deliberately (plan §22), because the fact is already on the board.

    Acknowledgement is not dismissal. An alert may be acknowledged (someone owns
    it) and later dismissed (it is finished); neither clears the other.
    """
    alert = await session.get(BugAlert, ticket_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="bug alert not found")

    already_acked = alert.acked_at is not None
    if not already_acked:
        alert.acked_at = naive_utcnow()
        alert.acked_by = user_id
        await session.commit()

    users = await _user_refs(session, {alert.acked_by} if alert.acked_by is not None else set())
    acker = users.get(alert.acked_by) if alert.acked_by is not None else None
    read = _to_read(alert, acked_by=acker)

    # Nothing to mirror: already acknowledged (so the message already says so),
    # Slack switched off, or an alert that was never announced — the last is a
    # normal state, not a failure (FR-086).
    if (
        already_acked
        or slack is None
        or not config.slack_configured
        or not alert.slack_channel
        or not alert.slack_ts
    ):
        return read, False

    ctx = (await _ticket_contexts(session, [alert.ticket_id])).get(alert.ticket_id, TicketContext())
    try:
        await slack.update_message(
            channel=alert.slack_channel,
            ts=alert.slack_ts,
            text=_fallback_text(alert, ctx),
            attachments=_alert_attachments(alert, ctx, acker=acker.name if acker else None),
            ticket_id=alert.ticket_id,
        )
    except Exception as exc:
        # The acknowledgement stands. Identifiers only — an alert's evidence
        # quote is customer text and never reaches a log line (NFR-016).
        log_event(
            "bug_alert_ack_mirror_error",
            level=logging.WARNING,
            op="ack",
            ticket_id=alert.ticket_id,
            error=str(exc),
        )
        return read, False

    metrics.incr("bug_alerts_acked_total")
    return read, True

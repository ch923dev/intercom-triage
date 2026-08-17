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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, cast

from fastapi import HTTPException
from sqlalchemy import ColumnElement, and_, case, or_, select
from sqlalchemy.dialects.sqlite import Insert as OnConflictInsert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.ai import embeddings
from app.ai.pipeline import CategorizationResult
from app.clients.slack import SlackAuthError, SlackClient
from app.config import AppConfig
from app.metrics import metrics
from app.models import BugAlert, Category, Ticket, User
from app.observability import log_event
from app.schemas import BugAlertRead, SimilarBug, UserRef
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
# A note may run to 2000 chars; the card shows enough to act on and links the rest.
_NOTE_CHARS = 400


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


def _seen_before_blocks(prior: SimilarBug | None) -> list[dict[str, Any]]:
    """ "We have seen this before, and here is what we learned" — or nothing.

    Absent rather than empty when there is no match: a "no similar bugs" line on
    every alert would be noise on the majority of them, and would train people to
    skip the block on the one that matters.

    The note goes in a block, never in `text`/`fallback`, for the same reason the
    evidence quote does not: an operator's note routinely quotes the customer,
    and those two fields surface in push previews (NFR-016).
    """
    if prior is None:
        return []
    where = f"<{prior.url}|{prior.title}>" if prior.url and prior.title else f"`{prior.ticket_id}`"
    who = f" — {prior.note_by.name}" if prior.note_by and prior.note_by.name else ""
    return [
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"⤷ *Seen before* · {where} · {prior.score:.0%} similar\n"
                    f">{_clip(prior.note, _NOTE_CHARS)}{who}"
                ),
            },
        },
    ]


def _alert_attachments(
    alert: BugAlert,
    ctx: TicketContext,
    *,
    acker: str | None = None,
    prior: SimilarBug | None = None,
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

    blocks.extend(_seen_before_blocks(prior))

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


async def _prior_fix_or_none(session: AsyncSession, ticket_id: str) -> SimilarBug | None:
    """The best prior noted bug for the card, or None.

    Swallows failures on purpose: an announcement must go out even if the encoder
    is broken or a vector is malformed. The suggestion is an enrichment, and the
    alert is the thing that must not be lost.
    """
    try:
        matches = await similar_noted_bugs(session, ticket_id)
    except Exception as exc:
        log_event(
            "bug_similar_lookup_error",
            level=logging.WARNING,
            op="delivery",
            ticket_id=ticket_id,
            error=str(exc),
        )
        return None
    return matches[0] if matches else None


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
                # Recurrence lookup happens here, not in the record pass: this
                # loop is already outside SYNC_LOCK (invariant #20), so the
                # embedding work cannot stall ingest. Best-effort — a matching
                # failure must not cost the announcement itself.
                prior = await _prior_fix_or_none(session, alert.ticket_id)
                ts = await client.post_message(
                    channel=config.slack_bug_channel,
                    text=_fallback_text(alert, ctx),
                    attachments=_alert_attachments(alert, ctx, prior=prior),
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
    note_by: UserRef | None = None,
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
        note=alert.note,
        note_by=note_by,
        note_at=alert.note_at,
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


def _actor_ids(alerts: Iterable[BugAlert]) -> set[int]:
    """Every user id referenced by these alerts. One place to extend when a new
    attribution column lands — otherwise a read path silently returns a null
    actor for it, which looks like "nobody did this" rather than a bug."""
    ids: set[int] = set()
    for alert in alerts:
        ids.update(i for i in (alert.acked_by, alert.note_by) if i is not None)
    return ids


async def _read_one(
    session: AsyncSession, alert: BugAlert, *, title: str | None = None, url: str | None = None
) -> BugAlertRead:
    """`_to_read` with the attribution join resolved for a single alert."""
    users = await _user_refs(session, _actor_ids([alert]))
    return _to_read(
        alert,
        title=title,
        url=url,
        acked_by=users.get(alert.acked_by) if alert.acked_by is not None else None,
        note_by=users.get(alert.note_by) if alert.note_by is not None else None,
    )


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
    users = await _user_refs(session, _actor_ids([alert for alert, _, _ in rows]))
    return [
        _to_read(
            alert,
            title=title,
            url=url,
            acked_by=users.get(alert.acked_by) if alert.acked_by is not None else None,
            note_by=users.get(alert.note_by) if alert.note_by is not None else None,
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
    return await _read_one(session, alert)


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

    The mirror rebuilds the WHOLE card, because `chat.update` replaces the message
    wholesale: anything left out of the rebuild vanishes from the channel. That is
    why the recurrence block is re-derived below rather than skipped.
    """
    alert = await session.get(BugAlert, ticket_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="bug alert not found")

    already_acked = alert.acked_at is not None
    if not already_acked:
        alert.acked_at = naive_utcnow()
        alert.acked_by = user_id
        await session.commit()

    read = await _read_one(session, alert)
    acker = read.acked_by

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
    # `chat.update` replaces the ENTIRE attachment set, so the recurrence block
    # has to be rebuilt here too — omitting it would erase the precedent from the
    # card at the exact moment someone takes ownership of the bug. Re-derived
    # rather than remembered: a note written since the announcement should reach
    # this reader as well (FR-092), which is the same reason the endpoint
    # recomputes it per request.
    prior = await _prior_fix_or_none(session, alert.ticket_id)
    try:
        await slack.update_message(
            channel=alert.slack_channel,
            ts=alert.slack_ts,
            text=_fallback_text(alert, ctx),
            attachments=_alert_attachments(
                alert, ctx, acker=acker.name if acker else None, prior=prior
            ),
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


# ── The incident record + recurrence ──────────────────────────────────────────

# Cross-category matching has no category filter to fall back on, so a floor is
# required — `suggest_playbooks` needs none because its candidates are already
# same-category. Below this we say nothing: a confidently-wrong prior fix is
# worse than silence, because someone will follow it.
#
# Measured, not guessed — but on thin evidence. Against the dev corpus (18 alerts,
# 1 noted, all one product) scored against a note on "my messages arent sending":
#
#   0.55 0.53 0.53 0.51 0.51 0.50 | 0.45 0.45 | 0.33 0.31 0.30 | 0.23 … 0.05
#
# The two hand-confirmed same-defect reports ("messages on my account are not
# working", "workflow stopped sending messages") scored 0.532 and 0.504, and an
# unmistakably unrelated one ("cant find or make me a domain name") scored 0.047.
# An earlier guess of 0.55 rejected BOTH true matches — the feature would have
# looked implemented and never fired once.
#
# 0.50 sits under both confirmed matches and ~1.5x above the middle band. Note the
# inflation risk: one product's support vocabulary overlaps heavily ("messages",
# "sending", "workflow"), so absolute scores here run high and this floor is
# calibrated on ONE note. Re-measure once a handful exist.
_SIMILAR_MIN_SCORE = 0.50
# Only the single best precedent is shown. The question a card answers is "has
# anyone solved this?", not "here are five maybes" — so the floor guards the
# quality of one suggestion rather than the length of a list.
_SIMILAR_TOP_N = 1


async def set_bug_note(
    session: AsyncSession, ticket_id: str, *, note: str, user_id: int
) -> BugAlertRead:
    """Write, replace, or clear the incident record for one alert.

    An empty (or whitespace-only) note CLEARS the trio rather than storing a
    blank, so "no note" has exactly one representation — the same rule
    `ticket_notes` follows by deleting its row.

    `note_by` is the most recent author, not the original: the board is
    team-wide, so a second operator correcting a note becomes its author. That
    is a deliberate loss — see plan §23 on why there is no history table.
    """
    alert = await session.get(BugAlert, ticket_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="bug alert not found")

    body = note.strip()
    if body:
        alert.note = body
        alert.note_by = user_id
        alert.note_at = naive_utcnow()
    else:
        # The trio is CHECK-locked, so it clears together or not at all.
        alert.note = None
        alert.note_by = None
        alert.note_at = None
    await session.commit()
    metrics.incr("bug_notes_written_total" if body else "bug_notes_cleared_total")
    return await _read_one(session, alert)


def _symptom_text(alert: BugAlert, ctx: TicketContext) -> str:
    """What the customer reported, for similarity purposes.

    Evidence first (the customer's own words about the defect), then the ticket's
    title and summary. Deliberately NOT the note: the note is the answer being
    retrieved, and embedding it would rank by remedy language — matching any
    cache-clearing fix to any other one, which is not the question. Never
    `internal_notes` (invariant #4).
    """
    parts = [alert.evidence or "", ctx.title or "", ctx.summary or ""]
    return "\n".join(p for p in parts if p).strip()


async def similar_noted_bugs(
    session: AsyncSession,
    ticket_id: str,
    *,
    top_n: int = _SIMILAR_TOP_N,
    min_score: float = _SIMILAR_MIN_SCORE,
) -> list[SimilarBug]:
    """Earlier noted bugs whose SYMPTOM resembles this one's, best first.

    Deliberately unbounded by category: the same defect arrives as a Technical
    Issue, as Billing, and as How-To depending on how the customer phrased it, so
    a category-scoped match (what `suggest_playbooks` does) would miss exactly
    the recurrence this exists to catch (plan §23).

    Candidates are the noted alerts themselves, scored directly, rather than a
    `nearest_neighbours` sweep intersected with them: k-NN needs an arbitrary
    over-fetch (a match at rank 60 is invisible at k=50) and ranks whole-ticket
    text instead of the bug symptom. An operator writes one note per real defect,
    so the candidate set is small by nature and scoring all of it is exact.

    Returns `[]` — never raises — when there is no encoder, no noted alert, or
    nothing to embed. Hosted v1 runs embeddings off by scope, so the empty result
    is the normal hosted path, not an edge case (FR-094).
    """
    if not embeddings.encoder_available():
        return []

    candidates = (
        await session.scalars(
            select(BugAlert).where(
                BugAlert.note.is_not(None),
                BugAlert.ticket_id != ticket_id,  # an alert never matches itself
            )
        )
    ).all()
    if not candidates:
        return []

    subject = await session.get(BugAlert, ticket_id)
    if subject is None:
        raise HTTPException(status_code=404, detail="bug alert not found")

    contexts = await _ticket_contexts(
        session, [subject.ticket_id, *(c.ticket_id for c in candidates)]
    )
    query_text = _symptom_text(subject, contexts.get(subject.ticket_id, TicketContext()))
    if not query_text:
        return []

    query_vec = embeddings.embed_text(query_text)
    users = await _user_refs(session, {c.note_by for c in candidates if c.note_by is not None})

    scored: list[SimilarBug] = []
    for candidate in candidates:
        ctx = contexts.get(candidate.ticket_id, TicketContext())
        candidate_text = _symptom_text(candidate, ctx)
        if not candidate_text or candidate.note is None:
            continue
        score = embeddings.cosine(query_vec, embeddings.embed_text(candidate_text))
        if score < min_score:
            continue
        scored.append(
            SimilarBug(
                ticket_id=candidate.ticket_id,
                severity=cast("Any", candidate.severity),
                score=score,
                note=candidate.note,
                note_by=users.get(candidate.note_by) if candidate.note_by is not None else None,
                note_at=candidate.note_at,
                title=ctx.title,
                url=ctx.url,
            )
        )

    scored.sort(key=lambda s: s.score, reverse=True)
    if scored:
        metrics.incr("bug_similar_hits_total")
    return scored[:top_n]

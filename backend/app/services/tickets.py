"""Ticket ingest + override + read service. Reference: tasks.md T026.

The Chrome extension fetches conversations from the operator's Intercom
browser session and pushes them to `ingest_tickets`, which categorizes and
stores them. `get_tickets` serves the stored board with no live Intercom call.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embeddings
from app.ai.pipeline import CategorizationResult, categorize_many
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.metrics import metrics
from app.models import AICacheEntry, Category, Followup, Override, Ticket, TicketNote
from app.schemas import (
    FilterSettings,
    FollowupRead,
    HydratedTicket,
    IngestResponse,
    TicketNoteRead,
    TicketSchema,
)
from app.services.cache import get_cached, set_cached
from app.services.categories import get_fallback
from app.services.settings import get_settings
from app.util import naive_utcnow

logger = logging.getLogger(__name__)


def _chip_state(
    *,
    use_ai: bool,
    effective_ai_resolve: bool,
    threshold: float,
    resolved_at: datetime | None,
    updated_at: datetime,
    dismissed_at: datetime | None,
    verdict: str | None,
    verdict_confidence: float | None,
) -> str | None:
    """Compute resolution_chip_state for the front-end.

    Returns one of 'ai_resolved' | 'ai_reopened' | 'new_reply' | None.
    """
    if dismissed_at is not None and dismissed_at >= updated_at:
        return None
    new_activity = resolved_at is None or updated_at > resolved_at
    ai_on = (
        use_ai and effective_ai_resolve and verdict is not None and verdict_confidence is not None
    )
    high_conf = ai_on and verdict_confidence is not None and verdict_confidence >= threshold

    if resolved_at is None and high_conf and verdict == "resolved":
        return "ai_resolved"
    if resolved_at is not None and new_activity and high_conf and verdict == "not_resolved":
        return "ai_reopened"
    if resolved_at is not None and new_activity and not ai_on:
        return "new_reply"
    return None


def _content_signature(ticket: HydratedTicket) -> datetime:
    """Cache key for a hydrated conversation — the timestamp of the most recent
    customer-visible part (inbound message or admin reply).

    Intercom's `updated_at` advances on assignment changes, snoozes, attribute
    edits, and internal teammate notes — none of which change the *content* the
    AI is categorizing. Using the last-part timestamp instead means the AI runs
    again only when the customer-visible thread genuinely advanced (a new
    customer message or a new admin reply), and skips re-categorizing for
    internal-only updates.

    Falls back to `created_at` when a conversation has no renderable parts —
    rare, but handles the edge cleanly.
    """
    if ticket.parts:
        return max(p.created_at for p in ticket.parts)
    return ticket.created_at


# ── T026 — override ───────────────────────────────────────────────────────────


async def set_override(
    session: AsyncSession,
    ticket_id: str,
    category_id: int,
) -> int:
    """Upsert an override row with `set_at = now`. Returns the category id.

    Drag-out reopen: if the ticket was resolved, atomically clears
    `resolved_at` / `resolved_source` in the same transaction so a drag from
    the Resolved column to any category immediately reopens the ticket.
    """
    category = await session.get(Category, category_id)
    if category is None or not category.is_active:
        raise HTTPException(status_code=404, detail=f"category {category_id} not found")

    # Drag-out reopen — must run before commit so it's atomic with the override.
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    if ticket.resolved_at is not None:
        ticket.resolved_at = None
        ticket.resolved_source = None
        ticket.resolution_cleared_at = naive_utcnow()

    override = await session.get(Override, ticket_id)
    if override is None:
        session.add(
            Override(
                ticket_id=ticket_id,
                category_id=category_id,
                set_at=naive_utcnow(),
            ),
        )
    else:
        override.category_id = category_id
        override.set_at = naive_utcnow()
    await session.commit()
    metrics.incr("overrides_set_total")
    return category_id


# ── Extension ingest + stored board ───────────────────────────────────────────


def _threshold_datetime(filter_settings: FilterSettings) -> datetime:
    """Recency cutoff as a naive-UTC datetime, for filtering stored tickets."""
    per_unit = 3600 if filter_settings.lookback_unit == "hours" else 86400
    return naive_utcnow() - timedelta(seconds=filter_settings.lookback_value * per_unit)


def _resolve_title(hydrated: HydratedTicket, result: CategorizationResult) -> str | None:
    """Pick the stored title: Intercom's conversation title wins when non-empty
    (it's what the human-set subject line would be); otherwise the AI's
    `subject`. Returns `None` only when both sides are empty."""
    intercom_title = (hydrated.title or "").strip()
    if intercom_title:
        return hydrated.title
    return result.subject or None


def _maybe_auto_resolve_from_ai(
    row: Ticket,
    result: CategorizationResult,
    settings: FilterSettings,
    now: datetime,
    content_signature: datetime,
) -> None:
    """Stamp resolved_at + resolved_source when the AI verdict + settings agree.

    Skipped when the ticket is already resolved by any source — never override
    an existing resolution. Intercom-closed transitions take precedence at the
    caller site (this helper runs only when that branch did not fire).

    Skipped when the operator manually reopened (resolution_cleared_at is set)
    and the content_signature has not advanced past that timestamp — prevents
    a cached high-confidence verdict from bouncing a ticket back to resolved
    immediately after the operator drags it out of the Resolved column.
    """
    if row.resolved_at is not None:
        return
    if row.resolution_cleared_at is not None and content_signature <= row.resolution_cleared_at:
        return
    if result.ai_resolution_verdict not in ("resolved", "non_actionable"):
        return
    if result.ai_resolution_confidence is None:
        return
    if result.ai_resolution_confidence < settings.ai_resolve_confidence_threshold:
        return
    effective = (
        row.ai_resolve_enabled
        if row.ai_resolve_enabled is not None
        else settings.ai_resolve_default
    )
    if not effective:
        return
    row.resolved_at = now
    row.resolved_source = (
        "ai_resolved" if result.ai_resolution_verdict == "resolved" else "non_actionable"
    )


async def _upsert_ticket(
    session: AsyncSession,
    hydrated: HydratedTicket,
    result: CategorizationResult,
    settings: FilterSettings,
) -> None:
    """Insert or update one stored ticket row from its hydrated + AI data.

    Operator edits are sticky: a row with `title_user_edited` / `summary_user_edited`
    keeps its existing values across re-syncs (PATCH /tickets/{id} sets these).

    Intercom-closed auto-resolution: when a previously-open stored ticket
    arrives with state='closed', stamp resolved_at + resolved_source.
    Never re-stamp an already-resolved ticket. New rows arriving as closed
    are stamped on insert.
    """
    author = hydrated.author.model_dump(mode="json")
    parts = [p.model_dump(mode="json") for p in hydrated.parts]
    internal_notes = [n.model_dump(mode="json") for n in hydrated.internal_notes]
    row = await session.get(Ticket, hydrated.id)
    now = naive_utcnow()
    content_signature = _content_signature(hydrated)
    if row is None:
        new_row = Ticket(
            id=hydrated.id,
            title=_resolve_title(hydrated, result),
            state=hydrated.state,
            priority=hydrated.priority,
            url=hydrated.url,
            author=author,
            parts=parts,
            internal_notes=internal_notes,
            created_at=hydrated.created_at,
            updated_at=hydrated.updated_at,
            category_id=result.category_id,
            proposal_id=result.proposal_id,
            summary=result.summary,
            ai_confidence=result.confidence,
            # Roadmap 0.2 — triage facets (no extra AI call; carried via the
            # same CategorizationResult, fallback gets neutral defaults).
            ai_priority=result.ai_priority,
            ai_sentiment=result.ai_sentiment,
            ai_labels=result.ai_labels,
            ingested_at=now,
        )
        if hydrated.state == "closed":
            new_row.resolved_at = now
            new_row.resolved_source = "intercom_closed"
        else:
            _maybe_auto_resolve_from_ai(new_row, result, settings, now, content_signature)
        session.add(new_row)
        return
    # Closure transition: previously not closed AND now closed AND not already
    # resolved → auto-stamp resolved_at + resolved_source (intercom_closed).
    if hydrated.state == "closed" and row.state != "closed" and row.resolved_at is None:
        row.resolved_at = now
        row.resolved_source = "intercom_closed"
    else:
        _maybe_auto_resolve_from_ai(row, result, settings, now, content_signature)
    if not row.title_user_edited:
        row.title = _resolve_title(hydrated, result)
    row.state = hydrated.state
    row.priority = hydrated.priority
    row.url = hydrated.url
    row.author = author
    row.parts = parts
    row.internal_notes = internal_notes
    row.created_at = hydrated.created_at
    row.updated_at = hydrated.updated_at
    row.category_id = result.category_id
    row.proposal_id = result.proposal_id
    if not row.summary_user_edited:
        row.summary = result.summary
    row.ai_confidence = result.confidence
    # Roadmap 0.2 — refresh triage facets on every re-sync (not operator-editable).
    row.ai_priority = result.ai_priority
    row.ai_sentiment = result.ai_sentiment
    row.ai_labels = result.ai_labels
    row.ingested_at = now


async def _embed_ingested_tickets(
    session: AsyncSession,
    hydrated: list[HydratedTicket],
    config: AppConfig,
) -> None:
    """Best-effort local-embedding pass over a just-ingested batch.

    Runs AFTER ingest has already committed, in its own transaction, so a model
    or vec-table failure can never roll back or break ingest — the worst case is
    a missing embedding row that the next sync refills. Embeds the
    customer-visible `parts[]` plus the operator's local `ticket_notes` jot ONLY;
    Intercom `internal_notes` are never embedded (invariant #4). This is a
    separate store from `ai_cache` and never touches the content signature (#6).
    """
    if not config.embeddings_enabled:
        return
    ticket_ids = [t.id for t in hydrated]
    if not ticket_ids:
        return
    try:
        note_rows = (
            await session.scalars(select(TicketNote).where(TicketNote.ticket_id.in_(ticket_ids)))
        ).all()
        notes = {n.ticket_id: n.body for n in note_rows}
        stored = 0
        for ticket in hydrated:
            if await embeddings.embed_and_store_ticket(session, ticket, notes.get(ticket.id)):
                stored += 1
        await session.commit()
        if stored:
            metrics.incr("ticket_embeddings_stored_total", stored)
    except Exception:
        # Embedding is auxiliary — log and move on. Roll back the embedding
        # transaction so a partial failure doesn't leave the session dirty.
        await session.rollback()
        logger.warning("embedding pass failed for ingest batch", exc_info=True)


async def ingest_tickets(
    *,
    session: AsyncSession,
    openrouter: OpenRouterClient | None,
    config: AppConfig,
    hydrated: list[HydratedTicket],
) -> IngestResponse:
    """Categorize a batch of extension-supplied conversations and store them.

    Cache-aware (FR-008) — an unchanged conversation skips the AI call. Without
    an OpenRouter client, or with the `use_ai` setting off, every ticket
    degrades to the fallback category and the operator fills in the subject /
    summary by hand.
    """
    fallback = await get_fallback(session)
    settings = await get_settings(session)

    if not settings.use_ai:
        # AI disabled — degrade every ticket to the fallback category. The AI
        # cache is bypassed entirely (not read, not written) so flipping the
        # toggle back on re-categorizes on the next sync.
        fallback_results = await categorize_many(
            hydrated,
            session=session,
            client=None,
            model=config.openrouter_model,
            concurrency=config.ai_concurrency,
            fallback_category_id=fallback.id,
        )
        for ticket in hydrated:
            await _upsert_ticket(session, ticket, fallback_results[ticket.id], settings)
        await session.commit()
        metrics.incr("tickets_ingested_total", len(hydrated))
        await _embed_ingested_tickets(session, hydrated, config)
        return IngestResponse(received=len(hydrated), categorized=0)

    # Cache key is the last-part timestamp (see `_content_signature`) — AI only
    # re-fires on a new customer-visible message. Internal teammate notes and
    # assignment changes bump Intercom's `updated_at` but leave parts[] alone,
    # so they get a cache hit (no AI call, no token spend).
    results: dict[str, CategorizationResult] = {}
    uncached: list[HydratedTicket] = []
    for ticket in hydrated:
        signature = _content_signature(ticket)
        cached = await get_cached(
            session,
            ticket.id,
            signature,
            config.cache_ttl_seconds,
        )
        if cached is not None:
            results[ticket.id] = cached
            metrics.incr("cache_hits_total")
        else:
            uncached.append(ticket)

    fresh = await categorize_many(
        uncached,
        session=session,
        client=openrouter,
        model=config.openrouter_model,
        concurrency=config.ai_concurrency,
        fallback_category_id=fallback.id,
    )
    for ticket in uncached:
        result = fresh[ticket.id]
        # Skip caching a fallback — a transient OpenRouter failure must retry on
        # the next sync, not poison the cache with the fallback category until a
        # new customer message arrives (see pipeline._fallback).
        if not result.fallback:
            await set_cached(session, ticket.id, result, _content_signature(ticket))
        results[ticket.id] = result

    for ticket in hydrated:
        await _upsert_ticket(session, ticket, results[ticket.id], settings)

    await session.commit()
    metrics.incr("tickets_ingested_total", len(hydrated))
    await _embed_ingested_tickets(session, hydrated, config)
    return IngestResponse(received=len(hydrated), categorized=len(uncached))


async def edit_ticket(
    session: AsyncSession,
    ticket_id: str,
    *,
    title: str | None,
    summary: str | None,
) -> None:
    """Apply operator edits to title / summary. Either field omitted → unchanged;
    `None` (explicit null) on `title` clears it back to auto. A non-None value
    sets the corresponding `*_user_edited` flag so re-syncs keep the edit.

    Raises 404 if the ticket isn't stored.
    """
    row = await session.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")

    # `title` is treated as "set to this exact string"; an empty string clears
    # the override and reverts to AI/Intercom-derived title on next sync.
    if title is not None:
        stripped = title.strip()
        if stripped:
            row.title = stripped[:200]
            row.title_user_edited = True
        else:
            row.title_user_edited = False  # next sync re-derives from AI/Intercom
    if summary is not None:
        stripped_summary = summary.strip()
        if stripped_summary:
            row.summary = stripped_summary[:600]
            row.summary_user_edited = True
        else:
            row.summary_user_edited = False
            row.summary = ""  # explicit clear; AI fills on next sync
    await session.commit()
    metrics.incr("tickets_edited_total")


async def get_sync_state(session: AsyncSession) -> dict[str, datetime]:
    """Return `{ticket_id: updated_at}` for every stored ticket.

    The Chrome extension calls this before a sync: it lists Intercom
    conversations (cheap) and only fetches the full conversation detail
    (expensive) for ids whose Intercom `last_updated` is newer than the value
    here. Tickets already stored with an unchanged conversation are skipped
    entirely — no Intercom detail call, no re-categorization.

    Timestamps are stored naive-UTC; tag them as UTC so the JSON carries an
    explicit offset and the extension's `Date.parse` agrees on the epoch.
    """
    rows = (await session.execute(select(Ticket.id, Ticket.updated_at))).all()
    return {row.id: row.updated_at.replace(tzinfo=UTC) for row in rows}


async def get_tickets(session: AsyncSession, *, resolved: bool = False) -> list[TicketSchema]:
    """Serve the board from stored tickets — no live Intercom call. Honors the
    stored filter settings (lookback / states / included categories).

    Args:
        resolved: When False (default), returns only open (unresolved) tickets.
            When True, returns only resolved tickets (Resolved column) and skips
            the include_category_ids filter.
    """
    filter_settings = await get_settings(session)
    threshold = _threshold_datetime(filter_settings)

    # Push threshold + state filters into SQL so ix_tickets_updated_at is used
    # and Python never loads rows that will be discarded.
    ticket_q = select(Ticket).where(Ticket.updated_at >= threshold)
    states = list(filter_settings.states)
    if states:
        # Mirror the Python rule: rows with state IS NULL are kept regardless;
        # rows with a non-NULL state must be in the allowed set.
        ticket_q = ticket_q.where(or_(Ticket.state.is_(None), Ticket.state.in_(states)))

    # Resolution filter — open-only by default; Resolved column passes resolved=True.
    if resolved:
        ticket_q = ticket_q.where(Ticket.resolved_at.is_not(None))
    else:
        ticket_q = ticket_q.where(Ticket.resolved_at.is_(None))

    rows = (await session.scalars(ticket_q)).all()

    # Scope side-table reads to the result set — avoids full-table scans for
    # overrides / followups / notes that belong to out-of-window tickets.
    ticket_ids = [row.id for row in rows]
    if ticket_ids:
        overrides = {
            o.ticket_id: o
            for o in (
                await session.scalars(select(Override).where(Override.ticket_id.in_(ticket_ids)))
            ).all()
        }
        followups = {
            f.ticket_id: f
            for f in (
                await session.scalars(select(Followup).where(Followup.ticket_id.in_(ticket_ids)))
            ).all()
        }
        notes = {
            n.ticket_id: n
            for n in (
                await session.scalars(
                    select(TicketNote).where(TicketNote.ticket_id.in_(ticket_ids))
                )
            ).all()
        }
        ai_cache = {
            c.ticket_id: c
            for c in (
                await session.scalars(
                    select(AICacheEntry).where(AICacheEntry.ticket_id.in_(ticket_ids))
                )
            ).all()
        }
    else:
        overrides = {}
        followups = {}
        notes = {}
        ai_cache = {}

    composed: list[TicketSchema] = []
    for row in rows:
        category_id = row.category_id
        proposal_id = row.proposal_id
        user_override = False
        override = overrides.get(row.id)
        if override is not None and row.updated_at <= override.set_at:
            category_id = override.category_id
            proposal_id = None
            user_override = True

        # Effective ai_resolve: per-ticket override wins over settings default.
        effective_ai_resolve = (
            row.ai_resolve_enabled
            if row.ai_resolve_enabled is not None
            else filter_settings.ai_resolve_default
        )

        cache_entry = ai_cache.get(row.id)
        verdict = cache_entry.ai_resolution_verdict if cache_entry is not None else None
        verdict_confidence = (
            cache_entry.ai_resolution_confidence if cache_entry is not None else None
        )
        verdict_reason = cache_entry.ai_resolution_reason if cache_entry is not None else None

        chip = _chip_state(
            use_ai=filter_settings.use_ai,
            effective_ai_resolve=effective_ai_resolve,
            threshold=filter_settings.ai_resolve_confidence_threshold,
            resolved_at=row.resolved_at,
            updated_at=row.updated_at,
            dismissed_at=row.resolution_chip_dismissed_at,
            verdict=verdict,
            verdict_confidence=verdict_confidence,
        )

        followup = followups.get(row.id)
        note = notes.get(row.id)
        composed.append(
            TicketSchema(
                id=row.id,
                title=row.title,
                state=row.state,  # type: ignore[arg-type]
                priority=row.priority,
                created_at=row.created_at,
                updated_at=row.updated_at,
                author=row.author,  # type: ignore[arg-type]
                url=row.url,
                parts=row.parts,  # type: ignore[arg-type]
                internal_notes=row.internal_notes,  # type: ignore[arg-type]
                category_id=category_id,
                proposal_id=proposal_id,
                summary=row.summary,
                ai_confidence=row.ai_confidence,
                user_override=user_override,
                title_user_edited=row.title_user_edited,
                summary_user_edited=row.summary_user_edited,
                followup=FollowupRead.model_validate(followup) if followup is not None else None,
                note=TicketNoteRead.model_validate(note) if note is not None else None,
                resolved_at=row.resolved_at,
                resolved_source=row.resolved_source,  # type: ignore[arg-type]
                ai_resolve_enabled=effective_ai_resolve,
                ai_resolve_override=row.ai_resolve_enabled,
                ai_resolution_verdict=verdict,  # type: ignore[arg-type]
                ai_resolution_confidence=verdict_confidence,
                ai_resolution_reason=verdict_reason,
                resolution_chip_state=chip,  # type: ignore[arg-type]
                ai_priority=row.ai_priority,  # type: ignore[arg-type]
                ai_sentiment=row.ai_sentiment,  # type: ignore[arg-type]
                ai_labels=list(row.ai_labels or []),
            ),
        )

    # Included-category filter (FR-011) — proposal-assigned tickets always show.
    # Skipped when resolved=True: the Resolved column shows everything.
    if not resolved and filter_settings.include_category_ids is not None:
        allowed = set(filter_settings.include_category_ids)
        composed = [t for t in composed if t.proposal_id is not None or t.category_id in allowed]

    # Sort: resolved column → most recently resolved first; open → most recently updated.
    if resolved:
        composed.sort(key=lambda t: t.resolved_at or t.updated_at, reverse=True)
    else:
        composed.sort(key=lambda t: t.updated_at, reverse=True)  # FR-013

    metrics.incr("tickets_served_total", len(composed))
    return composed

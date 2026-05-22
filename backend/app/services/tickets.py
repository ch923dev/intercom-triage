"""Ticket fetch orchestrator + override. Reference: tasks.md T025, T026.

`fetch_tickets` runs the full pipeline (plan §2 data flow):
search → hydrate → cache-split → AI on misses → write cache → apply overrides
→ filter → sort.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult, categorize_many
from app.clients.intercom import IntercomClient, IntercomError
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.metrics import metrics
from app.models import Category, Followup, Override, Ticket, TicketNote
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


def _threshold_unix(filter_settings: FilterSettings, *, now: float | None = None) -> int:
    """Convert a recency window to a unix-second cutoff."""
    now = now if now is not None else time.time()
    per_unit = 3600 if filter_settings.lookback_unit == "hours" else 86400
    return int(now - filter_settings.lookback_value * per_unit)


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


async def fetch_tickets(
    *,
    session: AsyncSession,
    intercom: IntercomClient | None,
    openrouter: OpenRouterClient | None,
    config: AppConfig,
    filter_settings: FilterSettings,
) -> list[TicketSchema]:
    if intercom is None:
        raise HTTPException(status_code=503, detail="Intercom is not configured")

    threshold = _threshold_unix(filter_settings)
    try:
        ids = await intercom.search_conversation_ids(
            threshold_unix=threshold,
            states=list(filter_settings.states),
            max_tickets=config.max_tickets_per_fetch,
        )
        hydrated = await intercom.hydrate_many(ids)
    except IntercomError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    fallback = await get_fallback(session)

    # Split cached vs uncached (FR-008). Cache key is the last-part timestamp
    # (see `_content_signature`), so AI only re-fires on a new customer-visible
    # message — internal notes / assignment changes still hit the cache.
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

    # AI on the misses; write cache.
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
        # Skip caching a fallback — a failed AI call must retry on the next
        # fetch, not pin the ticket to the fallback category (see pipeline._fallback).
        if not result.fallback:
            await set_cached(session, ticket.id, result, _content_signature(ticket))
        results[ticket.id] = result

    # Persist new proposals + cache writes before reading overrides.
    await session.commit()

    overrides = {o.ticket_id: o for o in (await session.scalars(select(Override))).all()}

    # Follow-ups + notes joined in by ticket id (T048, plan §8a).
    followups = {f.ticket_id: f for f in (await session.scalars(select(Followup))).all()}
    notes = {n.ticket_id: n for n in (await session.scalars(select(TicketNote))).all()}

    # Compose the response (FR-009 override application).
    composed: list[TicketSchema] = []
    for ticket in hydrated:
        result = results[ticket.id]
        category_id = result.category_id
        proposal_id = result.proposal_id
        user_override = False

        override = overrides.get(ticket.id)
        if override is not None and ticket.updated_at <= override.set_at:
            category_id = override.category_id
            proposal_id = None
            user_override = True

        followup = followups.get(ticket.id)
        note = notes.get(ticket.id)

        composed.append(
            TicketSchema(
                **ticket.model_dump(),
                category_id=category_id,
                proposal_id=proposal_id,
                summary=result.summary,
                ai_confidence=result.confidence,
                user_override=user_override,
                followup=FollowupRead.model_validate(followup) if followup is not None else None,
                note=TicketNoteRead.model_validate(note) if note is not None else None,
            ),
        )

    # Included-category filter (FR-011). Proposal-assigned tickets always show —
    # they are pending curation and render as their own columns.
    if filter_settings.include_category_ids is not None:
        allowed = set(filter_settings.include_category_ids)
        composed = [t for t in composed if t.proposal_id is not None or t.category_id in allowed]

    composed.sort(key=lambda t: t.updated_at, reverse=True)  # FR-013
    metrics.incr("tickets_fetched_total", len(composed))
    return composed


# ── T026 — override ───────────────────────────────────────────────────────────


async def set_override(
    session: AsyncSession,
    ticket_id: str,
    category_id: int,
) -> int:
    """Upsert an override row with `set_at = now`. Returns the category id."""
    category = await session.get(Category, category_id)
    if category is None or not category.is_active:
        raise HTTPException(status_code=404, detail=f"category {category_id} not found")

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
#
# The operator has no Intercom Access Token, so the Chrome extension fetches
# conversations from Intercom via the logged-in browser session and pushes them
# here. `ingest_tickets` categorizes + stores them; `get_tickets` serves the
# stored board with no live Intercom call. The legacy `fetch_tickets` path above
# stays dormant — usable only if an Access Token is ever configured.


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


async def _upsert_ticket(
    session: AsyncSession,
    hydrated: HydratedTicket,
    result: CategorizationResult,
) -> None:
    """Insert or update one stored ticket row from its hydrated + AI data.

    Operator edits are sticky: a row with `title_user_edited` / `summary_user_edited`
    keeps its existing values across re-syncs (PATCH /tickets/{id} sets these).
    """
    author = hydrated.author.model_dump(mode="json")
    parts = [p.model_dump(mode="json") for p in hydrated.parts]
    internal_notes = [n.model_dump(mode="json") for n in hydrated.internal_notes]
    row = await session.get(Ticket, hydrated.id)
    if row is None:
        session.add(
            Ticket(
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
                ingested_at=naive_utcnow(),
            ),
        )
        return
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
    row.ingested_at = naive_utcnow()


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
            await _upsert_ticket(session, ticket, fallback_results[ticket.id])
        await session.commit()
        metrics.incr("tickets_ingested_total", len(hydrated))
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
        await _upsert_ticket(session, ticket, results[ticket.id])

    await session.commit()
    metrics.incr("tickets_ingested_total", len(hydrated))
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
            row.title = stripped[:120]
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


async def get_tickets(session: AsyncSession) -> list[TicketSchema]:
    """Serve the board from stored tickets — no live Intercom call. Honors the
    stored filter settings (lookback / states / included categories)."""
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
    else:
        overrides = {}
        followups = {}
        notes = {}

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
            ),
        )

    # Included-category filter (FR-011) — proposal-assigned tickets always show.
    if filter_settings.include_category_ids is not None:
        allowed = set(filter_settings.include_category_ids)
        composed = [t for t in composed if t.proposal_id is not None or t.category_id in allowed]

    composed.sort(key=lambda t: t.updated_at, reverse=True)  # FR-013
    metrics.incr("tickets_served_total", len(composed))
    return composed

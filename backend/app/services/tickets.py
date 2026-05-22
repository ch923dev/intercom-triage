"""Ticket fetch orchestrator + override. Reference: tasks.md T025, T026.

`fetch_tickets` runs the full pipeline (plan §2 data flow):
search → hydrate → cache-split → AI on misses → write cache → apply overrides
→ filter → sort.
"""

from __future__ import annotations

import time

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult, categorize_many
from app.clients.intercom import IntercomClient, IntercomError
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.metrics import metrics
from app.models import Category, Override
from app.schemas import FilterSettings, HydratedTicket, TicketSchema
from app.services.cache import get_cached, set_cached
from app.services.categories import get_fallback
from app.util import naive_utcnow


def _threshold_unix(filter_settings: FilterSettings, *, now: float | None = None) -> int:
    """Convert a recency window to a unix-second cutoff."""
    now = now if now is not None else time.time()
    per_unit = 3600 if filter_settings.lookback_unit == "hours" else 86400
    return int(now - filter_settings.lookback_value * per_unit)


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

    # Split cached vs uncached (FR-008).
    results: dict[str, CategorizationResult] = {}
    uncached: list[HydratedTicket] = []
    for ticket in hydrated:
        cached = await get_cached(
            session,
            ticket.id,
            ticket.updated_at,
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
        await set_cached(session, ticket.id, result, ticket.updated_at)
        results[ticket.id] = result

    # Persist new proposals + cache writes before reading overrides.
    await session.commit()

    overrides = {o.ticket_id: o for o in (await session.scalars(select(Override))).all()}

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

        composed.append(
            TicketSchema(
                **ticket.model_dump(),
                category_id=category_id,
                proposal_id=proposal_id,
                summary=result.summary,
                ai_confidence=result.confidence,
                user_override=user_override,
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

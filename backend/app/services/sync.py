"""Backend-driven Intercom sync. Reference: plan.md §6.

One `run_sync_cycle` = one fetch+ingest pass: search Intercom for active
conversations, skip the unchanged ones (server-side skip-known), fetch detail +
contact for the new/changed ones, detect open→closed transitions, then hand the
batch to the existing `ingest_tickets` (cache-aware AI + store).

Driven by the background poller (`main._intercom_poll_loop`) and the manual
`POST /tickets/sync` endpoint. Replaces the former extension-side
`fetchHydratedBatch` + closure pass.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.intercom import IntercomAuthError, IntercomClient, IntercomError
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.models import Ticket
from app.observability import log_event
from app.schemas import HydratedTicket, SyncResponse
from app.services.intercom_normalizer import customer_contact_id, normalize_conversation
from app.services.settings import get_settings
from app.services.tickets import get_sync_state, ingest_tickets


async def _hydrate_one(
    intercom: IntercomClient,
    config: AppConfig,
    conversation_id: str,
) -> HydratedTicket | None:
    """Fetch one conversation + its customer contact and normalize it.

    Auth failures (bad/expired token) propagate so the whole cycle aborts loudly;
    any other per-conversation error is logged and dropped (best-effort, the next
    sync retries).
    """
    try:
        detail = await intercom.get_conversation(conversation_id)
    except IntercomAuthError:
        raise
    except IntercomError as exc:
        log_event(
            "intercom.detail_skip",
            level=logging.WARNING,
            conversation_id=conversation_id,
            error=str(exc),
        )
        return None

    contact = None
    contact_id = customer_contact_id(detail)
    if contact_id:
        try:
            contact = await intercom.get_contact(contact_id)
        except IntercomAuthError:
            raise
        except IntercomError as exc:
            log_event(
                "intercom.contact_skip",
                level=logging.WARNING,
                conversation_id=conversation_id,
                error=str(exc),
            )

    return normalize_conversation(
        detail,
        workspace_app_id=config.intercom_workspace_app_id,
        customer_contact=contact,
    )


async def run_sync_cycle(
    *,
    session: AsyncSession,
    openrouter: OpenRouterClient | None,
    intercom: IntercomClient,
    config: AppConfig,
) -> SyncResponse:
    """Run one Intercom fetch+ingest cycle and return its counts."""
    settings = await get_settings(session)
    states = list(settings.states) or ["open"]

    # Skip-known: the stored {id: updated_at} map, in epoch seconds for a cheap
    # numeric compare against the search summary's `updated_at`.
    known = await get_sync_state(session)
    known_epoch = {tid: dt.timestamp() for tid, dt in known.items()}

    # Closure candidates: tickets we still hold as open. Any that no longer show
    # up in the active search must be re-fetched to learn their current state.
    open_tracked = set(
        (await session.scalars(select(Ticket.id).where(Ticket.resolved_at.is_(None)))).all()
    )

    seen_ids: set[str] = set()
    to_fetch: list[str] = []
    skipped_known = 0

    async for summary in intercom.search_conversations(states=states):
        sid = str(summary.get("id"))
        seen_ids.add(sid)
        updated = summary.get("updated_at")
        known_ts = known_epoch.get(sid)
        if known_ts is not None and isinstance(updated, int | float) and updated <= known_ts:
            skipped_known += 1
            continue
        to_fetch.append(sid)

    # Closure pass — tracked-open ids absent from the active search.
    to_fetch.extend(tid for tid in open_tracked if tid not in seen_ids)

    sem = asyncio.Semaphore(config.intercom_poll_concurrency)

    async def guarded(cid: str) -> HydratedTicket | None:
        async with sem:
            return await _hydrate_one(intercom, config, cid)

    fetched = await asyncio.gather(*(guarded(cid) for cid in to_fetch))
    hydrated = [h for h in fetched if h is not None]

    # A tracked-open ticket that came back closed is an intercom_closed transition
    # (`_upsert_ticket` does the stamping; this is just the count for the caller).
    closed_detected = sum(1 for h in hydrated if h.state == "closed" and h.id in open_tracked)

    received = 0
    categorized = 0
    if hydrated:
        ingest = await ingest_tickets(
            session=session,
            openrouter=openrouter,
            config=config,
            hydrated=hydrated,
        )
        received = ingest.received
        categorized = ingest.categorized

    return SyncResponse(
        received=received,
        categorized=categorized,
        skipped_known=skipped_known,
        closed_detected=closed_detected,
    )

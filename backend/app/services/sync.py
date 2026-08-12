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
from datetime import UTC, datetime, timedelta

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

# One cycle at a time, process-wide. The background poller and the manual
# `POST /tickets/sync` (Topbar Sync button) share this lock: two concurrent
# cycles would both miss the skip-known map and double-fetch + double-categorize
# the same conversations. The router fast-fails 409 when the lock is held; the
# poller just waits its turn.
SYNC_LOCK = asyncio.Lock()


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
    lookback_hours: int | None = None,
) -> SyncResponse:
    """Run one Intercom fetch+ingest cycle and return its counts.

    Serialized on `SYNC_LOCK` — a caller arriving mid-cycle waits for the
    running one to finish (the router avoids the wait by checking
    `SYNC_LOCK.locked()` → 409 instead).

    `lookback_hours` (when > 0) bounds the search to conversations whose
    `updated_at` is within the window — a server-side Intercom filter. None/0
    keeps the historical unbounded behavior (all active conversations).
    """
    async with SYNC_LOCK:
        return await _run_sync_cycle(
            session=session,
            openrouter=openrouter,
            intercom=intercom,
            config=config,
            lookback_hours=lookback_hours,
        )


async def _run_sync_cycle(
    *,
    session: AsyncSession,
    openrouter: OpenRouterClient | None,
    intercom: IntercomClient,
    config: AppConfig,
    lookback_hours: int | None = None,
) -> SyncResponse:
    settings = await get_settings(session)
    states = list(settings.states) or ["open"]

    # POSIX epoch cutoff for the Intercom `updated_at > X` filter. Uses an
    # aware-UTC clock (not naive_utcnow) because this is an API epoch, not a DB
    # write — naive .timestamp() would assume local time and skew the window.
    updated_after: int | None = None
    if lookback_hours is not None and lookback_hours > 0:
        updated_after = int((datetime.now(UTC) - timedelta(hours=lookback_hours)).timestamp())

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

    async for summary in intercom.search_conversations(states=states, updated_after=updated_after):
        sid = str(summary.get("id"))
        seen_ids.add(sid)
        updated = summary.get("updated_at")
        known_ts = known_epoch.get(sid)
        if known_ts is not None and isinstance(updated, int | float) and updated <= known_ts:
            skipped_known += 1
            continue
        to_fetch.append(sid)

    # Closure pass — tracked-open ids absent from the active search. Under a
    # bounded fetch, absence usually just means "not updated in the fetch
    # window", so re-fetching every older open ticket would defeat the bound.
    # But the fetch lookback (e.g. 24h from the Sync button) is too narrow for
    # closure detection: a ticket closed out-of-band today whose stored
    # updated_at predates the window would be missed forever with the poller
    # off. So closure candidates use a DEDICATED, wider window
    # (`intercom_closure_lookback_seconds`, default 7d) — decoupled from the
    # fetch bound — catching aged-but-recent closures while still excluding the
    # ancient backlog. Only truly stale tickets (older than the closure window)
    # rely on an eventual unbounded poller cycle.
    if updated_after is None:
        to_fetch.extend(tid for tid in open_tracked if tid not in seen_ids)
    else:
        closure_after = (
            datetime.now(UTC) - timedelta(seconds=config.intercom_closure_lookback_seconds)
        ).timestamp()
        to_fetch.extend(
            tid
            for tid in open_tracked
            if tid not in seen_ids and known_epoch.get(tid, 0) >= closure_after
        )

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

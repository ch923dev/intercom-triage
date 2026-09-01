"""run_sync_cycle tests — skip-known, closure pass, counts.

Drives the orchestration with a FakeIntercom (no HTTP) so the assertions target
the sync logic, not the client. OpenRouter is None → every fresh ticket takes
the fallback path (the AI cache is irrelevant here).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.intercom import IntercomAuthError
from app.config import AppConfig
from app.models import Ticket
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema
from app.services.sync import run_sync_cycle
from app.services.tickets import ingest_tickets
from tests.helpers import FakeIntercom

_DT = datetime(2026, 6, 1, 12, 0, 0)


def _epoch(dt: datetime) -> int:
    return int(dt.replace(tzinfo=UTC).timestamp())


def _seed(tid: str, *, state: str = "open") -> HydratedTicket:
    author = TicketAuthorSchema(type="user", id="u1")
    return HydratedTicket(
        id=tid,
        title=tid,
        state=state,  # type: ignore[arg-type]
        priority=None,
        created_at=_DT,
        updated_at=_DT,
        author=author,
        url=None,
        parts=[ConversationPartSchema(author=author, body="hi", created_at=_DT)],
    )


def _detail(tid: str, *, state: str, updated: int) -> dict[str, Any]:
    return {
        "id": tid,
        "state": state,
        "created_at": _epoch(_DT),
        "updated_at": updated,
        "source": {"author": {"type": "user", "id": "u1"}, "body": "message"},
        "conversation_parts": {"conversation_parts": []},
    }


async def _seed_ticket(session: AsyncSession, config: AppConfig, ticket: HydratedTicket) -> None:
    await ingest_tickets(session=session, openrouter=None, config=config, hydrated=[ticket])


async def test_skip_known_avoids_detail_fetch(
    session: AsyncSession, test_config: AppConfig
) -> None:
    await _seed_ticket(session, test_config, _seed("T1"))
    fake = FakeIntercom(summaries=[{"id": "T1", "updated_at": _epoch(_DT)}])

    resp = await run_sync_cycle(session=session, openrouter=None, intercom=fake, config=test_config)

    assert resp.skipped_known == 1
    assert "T1" not in fake.detail_calls
    assert resp.received == 0


async def test_changed_conversation_is_fetched(
    session: AsyncSession, test_config: AppConfig
) -> None:
    await _seed_ticket(session, test_config, _seed("T1"))
    newer = _epoch(_DT) + 1000
    fake = FakeIntercom(
        summaries=[{"id": "T1", "updated_at": newer}],
        details={"T1": _detail("T1", state="open", updated=newer)},
    )

    resp = await run_sync_cycle(session=session, openrouter=None, intercom=fake, config=test_config)

    assert "T1" in fake.detail_calls
    assert resp.skipped_known == 0
    assert resp.received == 1


async def test_closure_pass_stamps_intercom_closed(
    session: AsyncSession, test_config: AppConfig
) -> None:
    await _seed_ticket(session, test_config, _seed("C1", state="open"))
    # C1 has dropped off the active (open) search → closure pass re-fetches it
    # and finds it closed.
    fake = FakeIntercom(
        summaries=[],
        details={"C1": _detail("C1", state="closed", updated=_epoch(_DT) + 10)},
    )

    resp = await run_sync_cycle(session=session, openrouter=None, intercom=fake, config=test_config)

    assert "C1" in fake.detail_calls
    assert resp.closed_detected == 1
    row = await session.get(Ticket, "C1")
    assert row is not None
    assert row.resolved_source == "intercom_closed"
    assert row.resolved_at is not None


async def test_bounded_sync_skips_stale_open_tickets_in_closure_pass(
    session: AsyncSession, test_config: AppConfig
) -> None:
    # Stored ticket last updated 2026-06-01 — far outside a 24h lookback. A
    # bounded sync whose search returns nothing must NOT re-fetch it (absence
    # just means "not updated in the window"), or the Sync button's bound is
    # defeated by re-fetching every older open ticket.
    await _seed_ticket(session, test_config, _seed("OLD1", state="open"))
    fake = FakeIntercom(summaries=[], details={})

    resp = await run_sync_cycle(
        session=session, openrouter=None, intercom=fake, config=test_config, lookback_hours=24
    )

    assert "OLD1" not in fake.detail_calls
    assert resp.received == 0
    assert resp.closed_detected == 0


async def test_bounded_sync_still_catches_in_window_closure(
    session: AsyncSession, test_config: AppConfig
) -> None:
    from app.util import naive_utcnow

    recent = naive_utcnow()
    seed = _seed("C2", state="open").model_copy(update={"updated_at": recent})
    await _seed_ticket(session, test_config, seed)
    # C2 was updated inside the 24h window but is absent from the bounded
    # active search → still a closure candidate; re-fetch finds it closed.
    fake = FakeIntercom(
        summaries=[],
        details={"C2": _detail("C2", state="closed", updated=_epoch(recent) + 10)},
    )

    resp = await run_sync_cycle(
        session=session, openrouter=None, intercom=fake, config=test_config, lookback_hours=24
    )

    assert "C2" in fake.detail_calls
    assert resp.closed_detected == 1


async def test_bounded_sync_catches_closure_within_closure_window(
    session: AsyncSession, test_config: AppConfig
) -> None:
    from datetime import timedelta

    from app.util import naive_utcnow

    # Aged 3 days — OUTSIDE the 24h fetch lookback but INSIDE the dedicated 7d
    # closure window. Closed out-of-band in Intercom → must still be detected,
    # or the bounded Sync button would strand it in its live column forever with
    # the poller off (review finding #2).
    aged = naive_utcnow() - timedelta(days=3)
    seed = _seed("C3", state="open").model_copy(update={"created_at": aged, "updated_at": aged})
    await _seed_ticket(session, test_config, seed)
    fake = FakeIntercom(
        summaries=[],
        details={"C3": _detail("C3", state="closed", updated=_epoch(naive_utcnow()))},
    )

    resp = await run_sync_cycle(
        session=session, openrouter=None, intercom=fake, config=test_config, lookback_hours=24
    )

    assert "C3" in fake.detail_calls
    assert resp.closed_detected == 1


async def test_new_conversation_is_ingested(session: AsyncSession, test_config: AppConfig) -> None:
    fake = FakeIntercom(
        summaries=[{"id": "N1", "updated_at": _epoch(_DT)}],
        details={"N1": _detail("N1", state="open", updated=_epoch(_DT))},
    )

    resp = await run_sync_cycle(session=session, openrouter=None, intercom=fake, config=test_config)

    assert resp.received == 1
    row = await session.get(Ticket, "N1")
    assert row is not None
    assert row.resolved_at is None


class _AuthFailingIntercom(FakeIntercom):
    """Raises IntercomAuthError for the ids in `bad`, serves `details` otherwise."""

    def __init__(self, *, bad: set[str], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._bad = bad

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        self.detail_calls.append(conversation_id)
        if conversation_id in self._bad:
            raise IntercomAuthError("401 Unauthorized")
        return self._details[conversation_id]


async def test_auth_error_aborts_cycle_and_retrieves_sibling_results(
    session: AsyncSession, test_config: AppConfig
) -> None:
    # A revoked token must abort the whole cycle (`_hydrate_one` re-raises on
    # purpose) rather than ingest a partial board. Two ids fail so the gather has
    # a sibling exception to settle: with a bare gather that sibling's exception
    # is never retrieved and surfaces as "Task exception was never retrieved" at
    # GC, burying the real failure. T197.
    fake = _AuthFailingIntercom(
        bad={"BAD1", "BAD2"},
        summaries=[
            {"id": "BAD1", "updated_at": _epoch(_DT)},
            {"id": "OK1", "updated_at": _epoch(_DT)},
            {"id": "BAD2", "updated_at": _epoch(_DT)},
        ],
        details={"OK1": _detail("OK1", state="open", updated=_epoch(_DT))},
    )

    with pytest.raises(IntercomAuthError):
        await run_sync_cycle(session=session, openrouter=None, intercom=fake, config=test_config)

    # Every candidate was attempted — the cycle settled all of them instead of
    # bailing at the first failure with siblings still in flight.
    assert set(fake.detail_calls) == {"BAD1", "BAD2", "OK1"}
    # And nothing was written: an aborted cycle ingests nothing, not "whatever
    # happened to succeed before the token died".
    assert await session.get(Ticket, "OK1") is None


# ── T196 — per-cycle fetch cap ────────────────────────────────────────────────


def _capped_config(test_config: AppConfig, cap: int) -> AppConfig:
    return test_config.model_copy(update={"max_tickets_per_fetch": cap})


async def test_fetch_is_capped_at_max_tickets_per_fetch(
    session: AsyncSession, test_config: AppConfig
) -> None:
    # The search sorts updated_at descending, so the cap must keep the NEWEST
    # candidates and drop the tail — not an arbitrary slice. Asserting which two
    # were fetched (not just how many) is what pins that.
    base = _epoch(_DT)
    summaries = [{"id": f"S{i}", "updated_at": base + (10 - i)} for i in range(5)]
    details = {f"S{i}": _detail(f"S{i}", state="open", updated=base + (10 - i)) for i in range(5)}
    fake = FakeIntercom(summaries=summaries, details=details)

    resp = await run_sync_cycle(
        session=session, openrouter=None, intercom=fake, config=_capped_config(test_config, 2)
    )

    assert fake.detail_calls == ["S0", "S1"]
    assert resp.received == 2


async def test_cap_does_not_shorten_the_search_scan(
    session: AsyncSession, test_config: AppConfig
) -> None:
    # The cap slices the fetch list, never the search cursor. Breaking out of the
    # cursor early would leave `seen_ids` short, and the closure pass would then
    # treat every unreached open ticket as a closure candidate — MORE fetches,
    # not fewer. Two stored-and-unchanged tickets must still be counted as
    # skipped-known even though the cap is below the candidate count.
    base = _epoch(_DT)
    await _seed_ticket(session, test_config, _seed("K1"))
    await _seed_ticket(session, test_config, _seed("K2"))
    summaries = [
        {"id": "N1", "updated_at": base + 5},
        {"id": "N2", "updated_at": base + 4},
        {"id": "K1", "updated_at": base},
        {"id": "K2", "updated_at": base},
    ]
    details = {
        "N1": _detail("N1", state="open", updated=base + 5),
        "N2": _detail("N2", state="open", updated=base + 4),
    }
    fake = FakeIntercom(summaries=summaries, details=details)

    resp = await run_sync_cycle(
        session=session, openrouter=None, intercom=fake, config=_capped_config(test_config, 1)
    )

    assert resp.skipped_known == 2
    assert fake.detail_calls == ["N1"]


async def test_cap_above_candidate_count_changes_nothing(
    session: AsyncSession, test_config: AppConfig
) -> None:
    base = _epoch(_DT)
    fake = FakeIntercom(
        summaries=[{"id": "N1", "updated_at": base}],
        details={"N1": _detail("N1", state="open", updated=base)},
    )

    resp = await run_sync_cycle(
        session=session, openrouter=None, intercom=fake, config=_capped_config(test_config, 100)
    )

    assert resp.received == 1

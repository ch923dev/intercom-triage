"""run_sync_cycle tests — skip-known, closure pass, counts.

Drives the orchestration with a FakeIntercom (no HTTP) so the assertions target
the sync logic, not the client. OpenRouter is None → every fresh ticket takes
the fallback path (the AI cache is irrelevant here).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

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

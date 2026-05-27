from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services import resolution as svc
from app.services.settings import get_settings
from app.services.tickets import _upsert_ticket
from app.ai.pipeline import CategorizationResult
from app.schemas import HydratedTicket
from app.util import naive_utcnow


async def test_resync_preserves_parked_state(session: AsyncSession) -> None:
    # Seed a parked, open ticket.
    row = Ticket(
        id="sticky-1", title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(), summary="", ai_confidence=0.0,
    )
    session.add(row)
    await session.commit()
    until = naive_utcnow() + timedelta(hours=4)
    svc.apply_park(row, until, "waiting_on_customer")
    await session.commit()

    # Re-sync the same conversation (still open) via the ingest upsert path.
    hydrated = HydratedTicket.model_validate({
        "id": "sticky-1", "title": "t", "state": "open", "priority": None,
        "created_at": naive_utcnow(), "updated_at": naive_utcnow(),
        "author": {"name": "C", "email": None, "id": None, "type": "user"},
        "url": None, "parts": [], "internal_notes": [],
    })
    # A non-resolving fallback result (mirrors the cold/fallback path).
    result = CategorizationResult(
        category_id=None, proposal_id=None, summary="", confidence=0.0, fallback=True,
    )
    settings = await get_settings(session)
    await _upsert_ticket(session, hydrated, result, settings)
    await session.commit()

    refreshed = await session.get(Ticket, "sticky-1")
    assert refreshed is not None
    assert refreshed.parked_at is not None  # NOT clobbered by re-sync
    assert refreshed.parked_reason == "waiting_on_customer"

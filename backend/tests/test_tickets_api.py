"""T026 — category override endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.util import naive_utcnow


def _seed_open(session: AsyncSession, ticket_id: str, category_id: int = 1) -> None:
    session.add(
        Ticket(
            id=ticket_id,
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
            category_id=category_id,
            summary="",
            ai_confidence=0.0,
        )
    )


@pytest.mark.asyncio
async def test_override_endpoint(client: AsyncClient, session: AsyncSession) -> None:
    _seed_open(session, "INT-9")
    await session.commit()
    resp = await client.patch("/tickets/INT-9/category", json={"category_id": 2})
    assert resp.status_code == 200 and resp.json()["category_id"] == 2


@pytest.mark.asyncio
async def test_override_unknown_category_404(client: AsyncClient, session: AsyncSession) -> None:
    _seed_open(session, "INT-9")
    await session.commit()
    resp = await client.patch("/tickets/INT-9/category", json={"category_id": 9999})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_override_unknown_ticket_404(client: AsyncClient) -> None:
    """set_override must 404 when the ticket id doesn't exist (M3 fix)."""
    resp = await client.patch("/tickets/does-not-exist/category", json={"category_id": 2})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_edit_title_truncated_to_schema_cap(session: AsyncSession) -> None:
    """Service truncates title to 200 chars (matching TicketEdit.title max_length=200).
    Called directly (bypassing HTTP) because the Pydantic schema already blocks
    >200 chars at the router layer — this tests the service-level guard (L3 fix)."""
    from app.services.tickets import edit_ticket

    _seed_open(session, "trunc-1")
    await session.commit()
    long_title = "A" * 250
    await edit_ticket(session, "trunc-1", title=long_title, summary=None)
    row = await session.get(Ticket, "trunc-1")
    await session.refresh(row)  # type: ignore[arg-type]
    assert row is not None
    assert row.title == "A" * 200

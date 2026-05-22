"""Extension ingest + stored board — `POST /tickets/ingest`, `GET /tickets`."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


def _hydrated(ticket_id: str, *, state: str = "open", title: str = "Need help") -> dict:
    """A minimal `HydratedTicket` payload, timestamped now so it clears the
    default 24 h lookback filter."""
    now = datetime.now(UTC).isoformat()
    author = {"id": "u1", "name": "Customer", "email": "c@example.com", "type": "user"}
    return {
        "id": ticket_id,
        "title": title,
        "state": state,
        "priority": None,
        "created_at": now,
        "updated_at": now,
        "author": author,
        "url": f"https://app.intercom.com/x/{ticket_id}",
        "parts": [{"author": author, "body": "please help", "created_at": now}],
    }


@pytest.mark.asyncio
async def test_ingest_then_get_returns_categorized_tickets(client: AsyncClient) -> None:
    resp = await client.post("/tickets/ingest", json=[_hydrated("C1"), _hydrated("C2")])
    assert resp.status_code == 200
    assert resp.json() == {"received": 2, "categorized": 2}

    board = await client.get("/tickets")
    assert board.status_code == 200
    rows = board.json()
    assert {t["id"] for t in rows} == {"C1", "C2"}
    # No OpenRouter client in tests → every ticket degrades to the fallback.
    assert all(t["category_id"] is not None for t in rows)


@pytest.mark.asyncio
async def test_ingest_upserts_by_ticket_id(client: AsyncClient) -> None:
    await client.post("/tickets/ingest", json=[_hydrated("C1", title="first")])
    await client.post("/tickets/ingest", json=[_hydrated("C1", title="second")])

    rows = (await client.get("/tickets")).json()
    assert len(rows) == 1
    assert rows[0]["title"] == "second"


@pytest.mark.asyncio
async def test_get_tickets_empty_before_any_ingest(client: AsyncClient) -> None:
    resp = await client.get("/tickets")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_get_tickets_excludes_states_not_in_filter(client: AsyncClient) -> None:
    await client.post(
        "/tickets/ingest",
        json=[_hydrated("OPEN-1", state="open"), _hydrated("CLOSED-1", state="closed")],
    )
    # Default settings keep only `open`.
    rows = (await client.get("/tickets")).json()
    assert {t["id"] for t in rows} == {"OPEN-1"}


@pytest.mark.asyncio
async def test_get_tickets_applies_manual_override(client: AsyncClient) -> None:
    await client.post("/tickets/ingest", json=[_hydrated("C1")])
    patch = await client.patch("/tickets/C1/category", json={"category_id": 2})
    assert patch.status_code == 200

    rows = (await client.get("/tickets")).json()
    assert rows[0]["category_id"] == 2
    assert rows[0]["user_override"] is True


@pytest.mark.asyncio
async def test_ingest_warm_cache_skips_recategorization(client: AsyncClient) -> None:
    first = await client.post("/tickets/ingest", json=[_hydrated("C1")])
    assert first.json()["categorized"] == 1

    # Same conversation, unchanged `updated_at` would be a cache hit — but
    # `_hydrated` re-stamps now, so this is a fresh timestamp → recategorized.
    # Re-post the very same payload to exercise the warm path instead.
    payload = _hydrated("C2")
    await client.post("/tickets/ingest", json=[payload])
    again = await client.post("/tickets/ingest", json=[payload])
    assert again.json()["categorized"] == 0  # served from the AI cache

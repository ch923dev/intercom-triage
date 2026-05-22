"""T047 — notes endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_put_non_empty_body_stores_row(client: AsyncClient) -> None:
    put = await client.put("/notes/T1", json={"body": "ask for logs\n• escalate"})
    assert put.status_code == 200
    body = put.json()
    assert body["ticket_id"] == "T1"
    assert body["body"] == "ask for logs\n• escalate"

    rows = (await client.get("/notes")).json()
    assert len(rows) == 1 and rows[0]["ticket_id"] == "T1"


@pytest.mark.asyncio
async def test_put_then_update_keeps_one_row(client: AsyncClient) -> None:
    await client.put("/notes/T1", json={"body": "first"})
    await client.put("/notes/T1", json={"body": "second"})

    rows = (await client.get("/notes")).json()
    assert len(rows) == 1 and rows[0]["body"] == "second"


@pytest.mark.asyncio
async def test_put_empty_body_deletes_row(client: AsyncClient) -> None:
    await client.put("/notes/T1", json={"body": "temporary"})

    cleared = await client.put("/notes/T1", json={"body": "   "})
    assert cleared.status_code == 200
    assert cleared.json() == {"ok": True, "deleted": True}

    assert (await client.get("/notes")).json() == []


@pytest.mark.asyncio
async def test_put_empty_body_on_absent_row_is_idempotent(client: AsyncClient) -> None:
    resp = await client.put("/notes/never-existed", json={"body": ""})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True}


@pytest.mark.asyncio
async def test_get_lists_only_non_empty_notes(client: AsyncClient) -> None:
    await client.put("/notes/T1", json={"body": "kept"})
    await client.put("/notes/T2", json={"body": "also kept"})
    await client.put("/notes/T2", json={"body": ""})  # delete T2

    rows = (await client.get("/notes")).json()
    assert {r["ticket_id"] for r in rows} == {"T1"}

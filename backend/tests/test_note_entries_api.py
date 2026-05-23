"""HTTP tests for /notes/entries (time-tabled notes spec)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_entry_minimal_body(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "investigating"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ticket_id"] == "T1"
    assert payload["body"] == "investigating"
    assert payload["timer_min"] is None
    assert payload["reason"] is None
    assert "id" in payload
    assert "created_at" in payload


@pytest.mark.asyncio
async def test_post_entry_with_timer_creates_followup(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={
            "ticket_id": "T1",
            "body": "investigating timeout",
            "timer_min": 15,
            "reason": "check retry policy",
        },
    )
    assert resp.status_code == 200

    fu_resp = await client.get("/followups")
    fus = fu_resp.json()
    assert len(fus) == 1
    assert fus[0]["ticket_id"] == "T1"
    assert fus[0]["reason"] == "check retry policy"
    assert fus[0]["fired"] is False


@pytest.mark.asyncio
async def test_post_entry_with_timer_overrides_prior_followup(client: AsyncClient) -> None:
    await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "first", "timer_min": 5, "reason": "r1"},
    )
    await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "second", "timer_min": 60, "reason": "r2"},
    )

    fus = (await client.get("/followups")).json()
    assert len(fus) == 1
    assert fus[0]["reason"] == "r2"


@pytest.mark.asyncio
async def test_get_entries_filtered_by_ticket(client: AsyncClient) -> None:
    await client.post("/notes/entries", json={"ticket_id": "T1", "body": "a"})
    await client.post("/notes/entries", json={"ticket_id": "T1", "body": "b"})
    await client.post("/notes/entries", json={"ticket_id": "T2", "body": "x"})

    t1 = (await client.get("/notes/entries/T1")).json()
    assert [r["body"] for r in t1] == ["a", "b"]

    t2 = (await client.get("/notes/entries/T2")).json()
    assert [r["body"] for r in t2] == ["x"]


@pytest.mark.asyncio
async def test_get_all_excludes_soft_deleted(client: AsyncClient) -> None:
    e = (await client.post("/notes/entries", json={"ticket_id": "T1", "body": "gone"})).json()
    await client.post("/notes/entries", json={"ticket_id": "T1", "body": "kept"})
    await client.delete(f"/notes/entries/{e['id']}")

    rows = (await client.get("/notes/entries")).json()
    assert [r["body"] for r in rows] == ["kept"]


@pytest.mark.asyncio
async def test_delete_returns_envelope(client: AsyncClient) -> None:
    e = (await client.post("/notes/entries", json={"ticket_id": "T1", "body": "x"})).json()
    resp = await client.delete(f"/notes/entries/{e['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True, "id": e["id"]}


@pytest.mark.asyncio
async def test_delete_missing_returns_404(client: AsyncClient) -> None:
    resp = await client.delete("/notes/entries/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_rejects_empty_body(client: AsyncClient) -> None:
    resp = await client.post("/notes/entries", json={"ticket_id": "T1", "body": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_reason_too_long(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "x", "timer_min": 15, "reason": "a" * 81},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_timer_out_of_range(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "x", "timer_min": 0},
    )
    assert resp.status_code == 422
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "x", "timer_min": 1441},
    )
    assert resp.status_code == 422

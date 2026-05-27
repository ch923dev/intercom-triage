"""Snippets API tests. Roadmap 1.5."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_list_update_archive_flow(client: AsyncClient) -> None:
    created = await client.post(
        "/snippets",
        json={"title": "greeting", "body": "Hi {{customer_name}}"},
    )
    assert created.status_code == 200
    sid = created.json()["id"]
    assert created.json()["created_at"].endswith("Z")
    assert created.json()["body"] == "Hi {{customer_name}}"  # stored verbatim

    listed = await client.get("/snippets")
    assert [s["title"] for s in listed.json()] == ["greeting"]

    patched = await client.patch(f"/snippets/{sid}", json={"title": "greeting v2"})
    assert patched.json()["title"] == "greeting v2"

    archived = await client.post(f"/snippets/{sid}/archive")
    assert archived.json() == {"ok": True}
    assert (await client.get("/snippets")).json() == []

    restored = await client.post(f"/snippets/{sid}/restore")
    assert restored.json() == {"ok": True}
    assert len((await client.get("/snippets")).json()) == 1


@pytest.mark.asyncio
async def test_create_rejects_empty_title(client: AsyncClient) -> None:
    resp = await client.post("/snippets", json={"title": "", "body": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_rejects_empty_body(client: AsyncClient) -> None:
    resp = await client.post("/snippets", json={"title": "x", "body": ""})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_include_archived(client: AsyncClient) -> None:
    a = await client.post("/snippets", json={"title": "a", "body": "1"})
    await client.post("/snippets", json={"title": "b", "body": "2"})
    await client.post(f"/snippets/{a.json()['id']}/archive")

    active = await client.get("/snippets")
    assert {s["title"] for s in active.json()} == {"b"}

    everything = await client.get("/snippets", params={"include_archived": True})
    assert {s["title"] for s in everything.json()} == {"a", "b"}


@pytest.mark.asyncio
async def test_update_404_when_missing(client: AsyncClient) -> None:
    resp = await client.patch("/snippets/999", json={"title": "x"})
    assert resp.status_code == 404

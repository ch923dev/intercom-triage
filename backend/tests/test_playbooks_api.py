"""Playbooks API tests. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_list_update_archive_flow(client: AsyncClient) -> None:
    created = await client.post(
        "/playbooks",
        json={"category_id": 1, "label": "issue A", "body": "steps"},
    )
    assert created.status_code == 200
    pid = created.json()["id"]
    assert created.json()["created_at"].endswith("Z")

    listed = await client.get("/playbooks", params={"category_id": 1})
    assert [p["label"] for p in listed.json()] == ["issue A"]

    patched = await client.patch(f"/playbooks/{pid}", json={"label": "issue A2"})
    assert patched.json()["label"] == "issue A2"

    archived = await client.post(f"/playbooks/{pid}/archive")
    assert archived.json() == {"ok": True}
    assert await (await client.get("/playbooks", params={"category_id": 1})).aread() is not None
    assert (await client.get("/playbooks", params={"category_id": 1})).json() == []

    restored = await client.post(f"/playbooks/{pid}/restore")
    assert restored.json() == {"ok": True}
    assert len((await client.get("/playbooks", params={"category_id": 1})).json()) == 1


@pytest.mark.asyncio
async def test_create_rejects_empty_label(client: AsyncClient) -> None:
    resp = await client.post("/playbooks", json={"category_id": 1, "label": "", "body": "x"})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_all_when_no_filter(client: AsyncClient) -> None:
    await client.post("/playbooks", json={"category_id": 1, "label": "a", "body": "1"})
    await client.post("/playbooks", json={"category_id": 2, "label": "b", "body": "2"})
    resp = await client.get("/playbooks")
    assert {p["label"] for p in resp.json()} == {"a", "b"}

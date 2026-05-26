"""Playbooks API tests. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.util import naive_utcnow


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


class _FakeClient:
    async def complete(self, *, model: str, messages: list[dict[str, str]], ticket_id: str) -> str:
        return "1. Refund. 2. Reply."


@pytest.mark.asyncio
async def test_draft_endpoint_uses_configured_client(client: AsyncClient, app) -> None:
    from app.db import make_session_factory  # noqa: F401  (factory already on state)
    from app.models import Ticket

    factory = app.state.session_factory
    async with factory() as s:
        s.add(
            Ticket(
                id="TCKD",
                title="t",
                state="open",
                author={},
                parts=[],
                internal_notes=[],
                created_at=naive_utcnow(),
                updated_at=naive_utcnow(),
                summary="",
                ai_confidence=0.0,
            )
        )
        await s.commit()

    app.state.openrouter = _FakeClient()
    resp = await client.post("/playbooks/draft", json={"ticket_id": "TCKD"})
    assert resp.status_code == 200
    assert resp.json() == {"body": "1. Refund. 2. Reply."}


@pytest.mark.asyncio
async def test_draft_endpoint_503_without_client(client: AsyncClient, app) -> None:
    from app.models import Ticket

    factory = app.state.session_factory
    async with factory() as s:
        s.add(
            Ticket(
                id="TCKN",
                title="t",
                state="open",
                author={},
                parts=[],
                internal_notes=[],
                created_at=naive_utcnow(),
                updated_at=naive_utcnow(),
                summary="",
                ai_confidence=0.0,
            )
        )
        await s.commit()

    app.state.openrouter = None
    resp = await client.post("/playbooks/draft", json={"ticket_id": "TCKN"})
    assert resp.status_code == 503

"""HTTP tests for /attachments (note attachments spec)."""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import AsyncClient


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (320, 240), color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_post_attachment_for_ticket(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("trace.csv", b"a,b,c\n1,2,3", "text/csv")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["owner_kind"] == "ticket"
    assert payload["owner_id"] == "T1"
    assert payload["ticket_id"] == "T1"
    assert payload["filename"] == "trace.csv"
    assert payload["mime"] == "text/csv"
    assert payload["size_bytes"] == 11
    assert payload["raw_url"].endswith(f"/attachments/{payload['id']}/raw")
    assert payload["thumb_url"] is None


@pytest.mark.asyncio
async def test_post_attachment_for_entry(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "entry", "owner_id": "42", "ticket_id": "T1"},
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["owner_kind"] == "entry"
    assert payload["owner_id"] == "42"


@pytest.mark.asyncio
async def test_post_image_returns_thumb_url(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["thumb_url"] is not None
    assert payload["thumb_url"].endswith(f"/attachments/{payload['id']}/thumb")


@pytest.mark.asyncio
async def test_get_list_filtered_by_ticket(client: AsyncClient) -> None:
    await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("a.txt", b"a", "text/plain")},
    )
    await client.post(
        "/attachments",
        data={"owner_kind": "entry", "owner_id": "42", "ticket_id": "T1"},
        files={"file": ("b.txt", b"b", "text/plain")},
    )
    await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T2", "ticket_id": "T2"},
        files={"file": ("x.txt", b"x", "text/plain")},
    )

    rows = (await client.get("/attachments", params={"ticket_id": "T1"})).json()
    assert sorted(r["filename"] for r in rows) == ["a.txt", "b.txt"]


@pytest.mark.asyncio
async def test_get_raw_streams_bytes(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("hello.txt", b"hello world", "text/plain")},
        )
    ).json()
    resp = await client.get(f"/attachments/{created['id']}/raw")
    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert resp.headers["content-type"].startswith("text/plain")
    assert "hello.txt" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_get_thumb_for_image(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("a.png", _png_bytes(), "image/png")},
        )
    ).json()
    resp = await client.get(f"/attachments/{created['id']}/thumb")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_get_thumb_for_non_image_returns_404(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("a.txt", b"hi", "text/plain")},
        )
    ).json()
    resp = await client.get(f"/attachments/{created['id']}/thumb")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_returns_envelope_and_excludes_from_list(
    client: AsyncClient,
) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("a.txt", b"a", "text/plain")},
        )
    ).json()
    resp = await client.delete(f"/attachments/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True, "id": created["id"]}

    rows = (await client.get("/attachments", params={"ticket_id": "T1"})).json()
    assert rows == []


@pytest.mark.asyncio
async def test_post_missing_field_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "ticket"},
        files={"file": ("a.txt", b"a", "text/plain")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_invalid_owner_kind_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "bogus", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("a.txt", b"a", "text/plain")},
    )
    assert resp.status_code == 422

"""T026 — category override endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_override_endpoint(client: AsyncClient) -> None:
    resp = await client.patch("/tickets/INT-9/category", json={"category_id": 2})
    assert resp.status_code == 200 and resp.json()["category_id"] == 2


@pytest.mark.asyncio
async def test_override_unknown_category_404(client: AsyncClient) -> None:
    resp = await client.patch("/tickets/INT-9/category", json={"category_id": 9999})
    assert resp.status_code == 404

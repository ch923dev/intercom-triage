"""Phase 1 — protected routes 401 without a token; health/login stay public."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_is_public(unauth_client: AsyncClient) -> None:
    assert (await unauth_client.get("/health")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/tickets", "/categories", "/settings", "/users"])
async def test_protected_routes_401_without_token(unauth_client: AsyncClient, path: str) -> None:
    assert (await unauth_client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_authenticated_client_reaches_settings(client: AsyncClient) -> None:
    assert (await client.get("/settings")).status_code == 200

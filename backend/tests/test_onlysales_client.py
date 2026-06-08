"""Phase 1 — OnlySales auth proxy client."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from app.clients.onlysales import OnlySalesAuthError, OnlySalesClient

BASE = "https://pyapi.onlysales.io"


@pytest.mark.asyncio
async def test_login_normalizes_user_id_and_returns_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/auth/login",
        method="POST",
        json={
            "accessToken": "os-access",
            "refreshToken": "os-refresh",
            "user": {
                "id": "oid-9",
                "email": "Op@Example.com",
                "firstName": "Op",
                "lastName": "E",
                "scope": "admin",
            },
        },
    )
    client = OnlySalesClient(base=BASE)
    try:
        result = await client.login(email="op@example.com", password="pw")
    finally:
        await client.aclose()

    assert result.access_token == "os-access"
    assert result.refresh_token == "os-refresh"
    assert result.onlysales_id == "oid-9"
    assert result.email == "op@example.com"
    assert result.name == "Op E"
    assert result.scope == "admin"


@pytest.mark.asyncio
async def test_login_raises_on_bad_credentials(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/auth/login", method="POST", status_code=401, json={"message": "Invalid"}
    )
    client = OnlySalesClient(base=BASE)
    try:
        with pytest.raises(OnlySalesAuthError):
            await client.login(email="op@example.com", password="bad")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_login_raises_on_non_json_upstream_body(httpx_mock: HTTPXMock) -> None:
    """A gateway HTML error page (502/504, Cloudflare interstitial) must surface as
    OnlySalesAuthError — NOT a raw JSONDecodeError that escapes the client and
    becomes an opaque 500 at the login route."""
    httpx_mock.add_response(
        url=f"{BASE}/auth/login",
        method="POST",
        status_code=502,
        text="<html>502 Bad Gateway</html>",
    )
    client = OnlySalesClient(base=BASE)
    try:
        with pytest.raises(OnlySalesAuthError):
            await client.login(email="op@example.com", password="pw")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_login_raises_when_no_access_token(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/auth/login", method="POST", json={"name": "AccountNotVerified"}
    )
    client = OnlySalesClient(base=BASE)
    try:
        with pytest.raises(OnlySalesAuthError):
            await client.login(email="op@example.com", password="pw")
    finally:
        await client.aclose()

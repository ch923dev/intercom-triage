"""IntercomClient tests — headers, pagination, retry, auth, contact cache.

Uses pytest-httpx (`httpx_mock`) so the client builds its own AsyncClient (with
the real Authorization / Intercom-Version headers) and we can assert on the
request it actually emitted.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from app.clients.intercom import IntercomAuthError, IntercomClient, IntercomError


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op asyncio.sleep so retry backoff doesn't slow the suite."""

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr("app.clients.intercom.asyncio.sleep", _noop)


def _client() -> IntercomClient:
    return IntercomClient("tok", version="2.13", contact_cache_ttl_seconds=300)


async def test_auth_and_version_headers(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/abc",
        method="GET",
        json={"id": "abc", "state": "open"},
    )
    client = _client()
    try:
        await client.get_conversation("abc")
    finally:
        await client.aclose()

    req = httpx_mock.get_requests()[0]
    assert req.headers["Authorization"] == "Bearer tok"
    assert req.headers["Intercom-Version"] == "2.13"
    assert req.headers["Accept"] == "application/json"


async def test_search_paginates_via_cursor(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/search",
        method="POST",
        json={
            "conversations": [{"id": "1"}, {"id": "2"}],
            "pages": {"next": {"starting_after": "CURSOR2"}},
        },
    )
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/search",
        method="POST",
        json={"conversations": [{"id": "3"}], "pages": {"next": None}},
    )
    client = _client()
    try:
        ids = [c["id"] async for c in client.search_conversations(states=["open"])]
    finally:
        await client.aclose()

    assert ids == ["1", "2", "3"]
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    # Second page carries the cursor returned by the first.
    import json as _json

    assert _json.loads(requests[1].content)["pagination"]["starting_after"] == "CURSOR2"


async def test_401_raises_auth_error(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/x", method="GET", status_code=401
    )
    client = _client()
    try:
        with pytest.raises(IntercomAuthError):
            await client.get_conversation("x")
    finally:
        await client.aclose()


async def test_retry_on_429_then_success(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/y",
        method="GET",
        status_code=429,
        headers={"X-RateLimit-Reset": "0"},
    )
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/y",
        method="GET",
        json={"id": "y", "state": "open"},
    )
    client = _client()
    try:
        detail = await client.get_conversation("y")
    finally:
        await client.aclose()

    assert detail["id"] == "y"
    assert len(httpx_mock.get_requests()) == 2


async def test_contact_404_returns_none_and_caches(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/contacts/missing", method="GET", status_code=404
    )
    client = _client()
    try:
        first = await client.get_contact("missing")
        second = await client.get_contact("missing")
    finally:
        await client.aclose()

    assert first is None
    assert second is None
    # Negative result is cached — the 404 is fetched once, not per call.
    assert len(httpx_mock.get_requests()) == 1


async def test_contact_positive_result_is_cached(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/contacts/c1",
        method="GET",
        json={"id": "c1", "name": "Ada", "email": "ada@x.com"},
    )
    client = _client()
    try:
        first = await client.get_contact("c1")
        second = await client.get_contact("c1")
    finally:
        await client.aclose()

    assert first is not None and first["name"] == "Ada"
    assert second is not None and second["name"] == "Ada"
    assert len(httpx_mock.get_requests()) == 1


async def test_non_retryable_500_after_retries_raises(httpx_mock: HTTPXMock) -> None:
    for _ in range(3):
        httpx_mock.add_response(
            url="https://api.intercom.io/conversations/z", method="GET", status_code=500
        )
    client = _client()
    try:
        with pytest.raises(IntercomError):
            await client.get_conversation("z")
    finally:
        await client.aclose()
    assert len(httpx_mock.get_requests()) == 3

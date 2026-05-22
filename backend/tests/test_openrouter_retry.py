"""Retry + backoff tests for OpenRouterClient.complete.

Uses httpx.MockTransport so we can exercise the full client code path without
a real network connection and without pytest-httpx (which patches globally).
Each test builds a response queue; the transport pops one entry per request.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from app.clients.openrouter import (
    OpenRouterClient,
    OpenRouterError,
    _parse_retry_after,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GOOD_BODY: dict[str, Any] = {"choices": [{"message": {"content": '{"result": "ok"}'}}]}


def _make_response(
    status: int, json_body: dict[str, Any] | None = None, headers: dict[str, str] | None = None
) -> httpx.Response:
    """Build an httpx.Response with a JSON body."""
    content = httpx.Response(
        status_code=status,
        json=json_body or {},
        headers=headers or {},
    )
    return content


class _QueuedTransport(httpx.AsyncBaseTransport):
    """Serves a fixed sequence of responses (or callables that raise)."""

    def __init__(self, responses: list[httpx.Response | Callable[[], None]]) -> None:
        self._queue = list(responses)
        self.call_count = 0

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.call_count += 1
        item = self._queue.pop(0)
        if callable(item):
            item()  # raises
        assert isinstance(item, httpx.Response)
        # httpx needs the stream attached when using a pre-built Response;
        # rebuild from content so the stream is fresh.
        return item


def _make_client(transport: _QueuedTransport) -> OpenRouterClient:
    http = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=transport,
    )
    return OpenRouterClient("fake-key", http=http)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace asyncio.sleep with a no-op so tests run in <1 ms."""

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr("asyncio.sleep", _noop)
    monkeypatch.setattr("app.clients.openrouter.asyncio.sleep", _noop)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_429_then_success() -> None:
    """First response 429, second 200 → returns content; transport hit twice."""
    transport = _QueuedTransport(
        [
            _make_response(429),
            _make_response(200, _GOOD_BODY),
        ]
    )
    client = _make_client(transport)
    try:
        result = await client.complete(
            model="meta/llama", messages=[{"role": "user", "content": "hi"}]
        )
        assert result == '{"result": "ok"}'
        assert transport.call_count == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_retry_on_500_then_success() -> None:
    """First response 500, second 200 → returns content; transport hit twice."""
    transport = _QueuedTransport(
        [
            _make_response(500),
            _make_response(200, _GOOD_BODY),
        ]
    )
    client = _make_client(transport)
    try:
        result = await client.complete(
            model="meta/llama", messages=[{"role": "user", "content": "hi"}]
        )
        assert result == '{"result": "ok"}'
        assert transport.call_count == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_no_retry_on_400() -> None:
    """400 raises OpenRouterError immediately; transport hit exactly once."""
    transport = _QueuedTransport([_make_response(400)])
    client = _make_client(transport)
    try:
        with pytest.raises(OpenRouterError, match="400"):
            await client.complete(model="meta/llama", messages=[{"role": "user", "content": "hi"}])
        assert transport.call_count == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_no_retry_on_401() -> None:
    """401 raises OpenRouterError immediately; transport hit exactly once."""
    transport = _QueuedTransport([_make_response(401)])
    client = _make_client(transport)
    try:
        with pytest.raises(OpenRouterError, match="401"):
            await client.complete(model="meta/llama", messages=[{"role": "user", "content": "hi"}])
        assert transport.call_count == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_exhausts_retries_then_raises() -> None:
    """Three 500s → raises OpenRouterError; transport hit exactly 3 times."""
    transport = _QueuedTransport(
        [
            _make_response(500),
            _make_response(500),
            _make_response(500),
        ]
    )
    client = _make_client(transport)
    try:
        with pytest.raises(OpenRouterError):
            await client.complete(model="meta/llama", messages=[{"role": "user", "content": "hi"}])
        assert transport.call_count == 3
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_retry_on_network_error_then_success() -> None:
    """First raises ConnectError, second returns 200 → returns content."""
    calls: list[int] = []

    class _ErrorThenSuccess(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            calls.append(1)
            if len(calls) == 1:
                raise httpx.ConnectError("boom")
            return _make_response(200, _GOOD_BODY)

    http = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        transport=_ErrorThenSuccess(),
    )
    client = OpenRouterClient("fake-key", http=http)
    try:
        result = await client.complete(
            model="meta/llama", messages=[{"role": "user", "content": "hi"}]
        )
        assert result == '{"result": "ok"}'
        assert len(calls) == 2
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_honors_retry_after_header(monkeypatch: pytest.MonkeyPatch) -> None:
    """429 with Retry-After: 0.05 then 200 → succeeds; delay >= 0.05 s honoured."""
    sleep_calls: list[float] = []

    async def _capturing_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    # Override the autouse no-op with a capturing version for this test only.
    import app.clients.openrouter as _openrouter_mod

    monkeypatch.setattr(_openrouter_mod.asyncio, "sleep", _capturing_sleep)

    transport = _QueuedTransport(
        [
            _make_response(429, headers={"Retry-After": "0.05"}),
            _make_response(200, _GOOD_BODY),
        ]
    )
    client = _make_client(transport)
    try:
        result = await client.complete(
            model="meta/llama", messages=[{"role": "user", "content": "hi"}]
        )
        assert result == '{"result": "ok"}'
        assert transport.call_count == 2
        # The delay should be at least the Retry-After value.
        assert sleep_calls, "asyncio.sleep was never called"
        assert sleep_calls[0] >= 0.05
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Unit tests for helper functions
# ---------------------------------------------------------------------------


def test_parse_retry_after_numeric() -> None:
    assert _parse_retry_after("30") == 30.0
    assert _parse_retry_after("0") == 0.0
    assert _parse_retry_after("0.5") == 0.5
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") is None
    assert _parse_retry_after("  10  ") == 10.0

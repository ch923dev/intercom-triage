"""POST /tickets/sync — 503 without a token, 200 + counts with the client bound,
409 while a cycle is already running, 502 when Intercom itself refuses."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from httpx import AsyncClient

from app.clients.intercom import IntercomAuthError, IntercomError
from app.services import sync as sync_svc
from tests.helpers import FakeIntercom

_EPOCH = int(datetime(2026, 6, 1, 12, 0, 0, tzinfo=UTC).timestamp())


async def test_sync_503_when_intercom_unconfigured(client: AsyncClient) -> None:
    # The app fixture never binds app.state.intercom → get_intercom returns None.
    resp = await client.post("/tickets/sync")
    assert resp.status_code == 503


async def test_sync_runs_one_cycle(app: FastAPI, client: AsyncClient) -> None:
    app.state.intercom = FakeIntercom(
        summaries=[{"id": "N1", "updated_at": _EPOCH}],
        details={
            "N1": {
                "id": "N1",
                "state": "open",
                "created_at": _EPOCH,
                "updated_at": _EPOCH,
                "source": {"author": {"type": "user", "id": "u1"}, "body": "hello"},
                "conversation_parts": {"conversation_parts": []},
            }
        },
    )
    resp = await client.post("/tickets/sync")
    assert resp.status_code == 200
    data = resp.json()
    assert data["received"] == 1
    assert set(data) == {"received", "categorized", "skipped_known", "closed_detected"}


async def test_sync_409_when_cycle_already_running(app: FastAPI, client: AsyncClient) -> None:
    app.state.intercom = FakeIntercom(summaries=[], details={})
    async with sync_svc.SYNC_LOCK:
        resp = await client.post("/tickets/sync")
    assert resp.status_code == 409
    assert not sync_svc.SYNC_LOCK.locked()


async def test_sync_lookback_hours_bounds_the_search(app: FastAPI, client: AsyncClient) -> None:
    # The ?lookback_hours= query param must reach the Intercom search as a
    # non-None `updated_after` bound (the whole point of the manual Sync bound).
    fake = FakeIntercom(summaries=[], details={})
    app.state.intercom = fake
    resp = await client.post("/tickets/sync?lookback_hours=24")
    assert resp.status_code == 200
    assert fake.search_updated_after and fake.search_updated_after[0] is not None


async def test_sync_without_lookback_is_unbounded(app: FastAPI, client: AsyncClient) -> None:
    fake = FakeIntercom(summaries=[], details={})
    app.state.intercom = fake
    resp = await client.post("/tickets/sync")
    assert resp.status_code == 200
    assert fake.search_updated_after == [None]


async def test_sync_rejects_zero_lookback(app: FastAPI, client: AsyncClient) -> None:
    # Query(ge=1) — 0/negative is a 422, so a regression loosening the bound is caught.
    app.state.intercom = FakeIntercom(summaries=[], details={})
    resp = await client.post("/tickets/sync?lookback_hours=0")
    assert resp.status_code == 422


class _RaisingIntercom(FakeIntercom):
    """Fails the search with a caller-supplied Intercom error."""

    def __init__(self, exc: Exception, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._exc = exc

    async def search_conversations(
        self, *, states: Any, updated_after: int | None = None, per_page: int = 150
    ) -> Any:
        raise self._exc
        yield  # pragma: no cover — makes this an async generator like the real client


async def test_sync_502_when_intercom_rejects_the_token(app: FastAPI, client: AsyncClient) -> None:
    # The poller swallows a dead token by design (broad except, keeps ticking).
    # The operator clicked a button, so they get told — 502, not an opaque 500.
    app.state.intercom = _RaisingIntercom(IntercomAuthError("401 Unauthorized"))
    resp = await client.post("/tickets/sync")
    assert resp.status_code == 502
    assert "token" in resp.json()["detail"]


async def test_sync_502_when_intercom_request_fails(app: FastAPI, client: AsyncClient) -> None:
    # A search that exhausted its retries was previously an unhandled 500.
    app.state.intercom = _RaisingIntercom(IntercomError("503 after 3 attempts"))
    resp = await client.post("/tickets/sync")
    assert resp.status_code == 502
    assert not sync_svc.SYNC_LOCK.locked()

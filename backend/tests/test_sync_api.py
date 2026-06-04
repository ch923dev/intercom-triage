"""POST /tickets/sync — 503 without a token, 200 + counts with the client bound."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import FastAPI
from httpx import AsyncClient

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

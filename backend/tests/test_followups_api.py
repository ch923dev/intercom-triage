"""T046 — follow-up endpoints."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

_DUE = "2030-01-01T12:00:00"


@pytest.mark.asyncio
async def test_put_then_get_returns_the_row(client: AsyncClient) -> None:
    put = await client.put("/followups/T1", json={"due_at": _DUE, "reason": "ping the customer"})
    assert put.status_code == 200
    body = put.json()
    assert body["ticket_id"] == "T1"
    assert body["reason"] == "ping the customer"
    assert body["fired"] is False

    got = await client.get("/followups")
    rows = got.json()
    assert len(rows) == 1 and rows[0]["ticket_id"] == "T1"


@pytest.mark.asyncio
async def test_put_upserts_and_resets_fired(client: AsyncClient) -> None:
    await client.put("/followups/T1", json={"due_at": _DUE, "reason": None})
    await client.post("/followups/T1/mark-fired")

    again = await client.put("/followups/T1", json={"due_at": _DUE, "reason": "redo"})
    assert again.json()["fired"] is False  # a fresh due_at re-arms the alarm

    rows = (await client.get("/followups")).json()
    assert len(rows) == 1  # upsert, not insert


@pytest.mark.asyncio
async def test_snooze_updates_due_at_and_clears_fired(client: AsyncClient) -> None:
    await client.put("/followups/T1", json={"due_at": _DUE, "reason": None})
    await client.post("/followups/T1/mark-fired")

    snoozed = await client.post("/followups/T1/snooze", json={"minutes": 15})
    assert snoozed.status_code == 200
    body = snoozed.json()
    assert body["fired"] is False
    assert body["due_at"] != _DUE  # rescheduled to now + 15m


@pytest.mark.asyncio
async def test_snooze_returns_utc_aware_due_at(client: AsyncClient) -> None:
    """Regression: a tz-naive `due_at` string is parsed by JS `Date` as *local*
    time, so a 15-min snooze fires immediately for any operator east of UTC.
    The API must emit a `Z`-suffixed UTC instant ~15m in the future."""
    await client.put("/followups/T1", json={"due_at": _DUE, "reason": None})
    snoozed = await client.post("/followups/T1/snooze", json={"minutes": 15})

    due_at = snoozed.json()["due_at"]
    assert due_at.endswith("Z"), f"due_at not UTC-aware: {due_at!r}"
    delta = (datetime.fromisoformat(due_at) - datetime.now(UTC)).total_seconds()
    assert 13 * 60 < delta < 16 * 60, f"due_at not ~15m ahead: {delta}s"


@pytest.mark.asyncio
async def test_snooze_missing_followup_404(client: AsyncClient) -> None:
    resp = await client.post("/followups/nope/snooze", json={"minutes": 15})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_mark_fired_sets_flag_without_touching_due_at(client: AsyncClient) -> None:
    await client.put("/followups/T1", json={"due_at": _DUE, "reason": None})

    fired = await client.post("/followups/T1/mark-fired")
    assert fired.status_code == 200 and fired.json()["ok"] is True

    row = (await client.get("/followups")).json()[0]
    assert row["fired"] is True
    assert row["due_at"].startswith("2030-01-01T12:00:00")


@pytest.mark.asyncio
async def test_delete_is_idempotent(client: AsyncClient) -> None:
    await client.put("/followups/T1", json={"due_at": _DUE, "reason": None})

    first = await client.delete("/followups/T1")
    assert first.status_code == 200
    assert (await client.get("/followups")).json() == []

    second = await client.delete("/followups/T1")  # already gone
    assert second.status_code == 200


@pytest.mark.asyncio
async def test_reason_over_80_chars_rejected(client: AsyncClient) -> None:
    resp = await client.put("/followups/T1", json={"due_at": _DUE, "reason": "x" * 100})
    assert resp.status_code == 422

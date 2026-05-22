"""T043 — `GET /metrics`."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.metrics import metrics


@pytest.mark.asyncio
async def test_metrics_reports_counters(client: AsyncClient) -> None:
    metrics.reset()
    metrics.incr("tickets_fetched_total", 3)
    metrics.incr("ai_calls_total.ok")
    metrics.incr("ai_calls_total.ok")
    metrics.incr("proposals_resolved_total.rejected")

    resp = await client.get("/metrics")
    assert resp.status_code == 200

    counters = resp.json()["counters"]
    assert counters["tickets_fetched_total"] == 3
    assert counters["ai_calls_total.ok"] == 2
    assert counters["proposals_resolved_total.rejected"] == 1


@pytest.mark.asyncio
async def test_metrics_empty_after_reset(client: AsyncClient) -> None:
    metrics.reset()
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    assert resp.json()["counters"] == {}

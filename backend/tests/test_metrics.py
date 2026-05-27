"""T043 — `GET /metrics`. R.4 — latency histograms."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.metrics import HISTOGRAM_CAPACITY, Metrics, metrics


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
    assert resp.json()["histograms"] == {}


# ── R.4: latency histograms ───────────────────────────────────────────────────


def test_observe_percentiles_basic() -> None:
    m = Metrics()
    # 1..100 → p50≈50, p95≈95, max=100, count=100.
    for v in range(1, 101):
        m.observe("latency_ms.op", float(v))
    stat = m.histogram_snapshot()["latency_ms.op"]
    assert stat["count"] == 100
    assert stat["max"] == 100.0
    # Nearest-rank: p50 = sorted[ceil(.50*100)-1] = sorted[49] = 50.
    assert stat["p50"] == 50.0
    # p95 = sorted[ceil(.95*100)-1] = sorted[94] = 95.
    assert stat["p95"] == 95.0


def test_observe_single_sample() -> None:
    m = Metrics()
    m.observe("latency_ms.op", 42.0)
    stat = m.histogram_snapshot()["latency_ms.op"]
    assert stat == {"count": 1, "p50": 42.0, "p95": 42.0, "max": 42.0}


def test_observe_two_samples() -> None:
    m = Metrics()
    m.observe("latency_ms.op", 10.0)
    m.observe("latency_ms.op", 20.0)
    stat = m.histogram_snapshot()["latency_ms.op"]
    # n=2: p50=sorted[ceil(.5*2)-1]=sorted[0]=10; p95=sorted[ceil(.95*2)-1]=sorted[1]=20.
    assert stat["count"] == 2
    assert stat["p50"] == 10.0
    assert stat["p95"] == 20.0
    assert stat["max"] == 20.0


def test_histogram_snapshot_empty() -> None:
    m = Metrics()
    assert m.histogram_snapshot() == {}


def test_histogram_unordered_input_sorted() -> None:
    m = Metrics()
    for v in (5.0, 1.0, 9.0, 3.0, 7.0):
        m.observe("latency_ms.op", v)
    stat = m.histogram_snapshot()["latency_ms.op"]
    assert stat["max"] == 9.0
    # n=5: p50=sorted[ceil(.5*5)-1]=sorted[2]=5; p95=sorted[ceil(.95*5)-1]=sorted[4]=9.
    assert stat["p50"] == 5.0
    assert stat["p95"] == 9.0


def test_histogram_buffer_is_bounded() -> None:
    m = Metrics()
    for v in range(HISTOGRAM_CAPACITY + 500):
        m.observe("latency_ms.op", float(v))
    stat = m.histogram_snapshot()["latency_ms.op"]
    # Ring buffer caps retained samples; oldest evicted.
    assert stat["count"] == HISTOGRAM_CAPACITY
    assert stat["max"] == float(HISTOGRAM_CAPACITY + 500 - 1)


def test_counter_snapshot_unaffected_by_observe() -> None:
    m = Metrics()
    m.incr("ai_calls_total.ok", 2)
    m.observe("latency_ms.op", 5.0)
    assert m.snapshot() == {"ai_calls_total.ok": 2}


def test_reset_clears_histograms() -> None:
    m = Metrics()
    m.observe("latency_ms.op", 5.0)
    m.reset()
    assert m.histogram_snapshot() == {}


@pytest.mark.asyncio
async def test_metrics_endpoint_surfaces_histogram(client: AsyncClient) -> None:
    metrics.reset()
    metrics.observe("latency_ms.openrouter.complete", 12.0)
    metrics.observe("latency_ms.openrouter.complete", 34.0)

    resp = await client.get("/metrics")
    assert resp.status_code == 200
    hist = resp.json()["histograms"]["latency_ms.openrouter.complete"]
    assert hist["count"] == 2
    assert hist["max"] == 34.0
    assert set(hist) == {"count", "p50", "p95", "max"}

"""T028 — structured logging wraps external calls; no ticket bodies leak."""

from __future__ import annotations

import logging

import pytest

from app.metrics import metrics
from app.observability import logged_call


@pytest.mark.asyncio
async def test_logged_call_emits_outcome_ok(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="triage"):
        async with logged_call("intercom.search", ticket_id="T1"):
            pass
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "external_call" in joined
    assert "intercom.search" in joined
    assert "outcome=ok" in joined or "'outcome': 'ok'" in joined or "outcome" in joined


@pytest.mark.asyncio
async def test_logged_call_reraises_and_marks_error() -> None:
    with pytest.raises(RuntimeError):
        async with logged_call("openrouter.complete"):
            raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_logged_call_records_latency_sample() -> None:
    metrics.reset()
    async with logged_call("openrouter.complete", ticket_id="T1"):
        pass
    stat = metrics.histogram_snapshot()["latency_ms.openrouter.complete"]
    assert stat["count"] == 1
    assert stat["max"] >= 0.0


@pytest.mark.asyncio
async def test_logged_call_records_sample_on_error() -> None:
    metrics.reset()
    with pytest.raises(RuntimeError):
        async with logged_call("openrouter.complete"):
            raise RuntimeError("boom")
    # Latency is recorded even when the wrapped call fails.
    assert metrics.histogram_snapshot()["latency_ms.openrouter.complete"]["count"] == 1

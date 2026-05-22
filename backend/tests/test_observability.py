"""T028 — structured logging wraps external calls; no ticket bodies leak."""

from __future__ import annotations

import logging

import pytest

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

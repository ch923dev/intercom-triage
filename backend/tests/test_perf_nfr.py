"""Performance NFR guards — NFR-001 (cold fetch) and NFR-002 (warm fetch).

Reference: spec.md NFR-001 / NFR-002.

    NFR-001 | A cold fetch of 50 tickets completes in <= 15 s end-to-end.
    NFR-002 | A warm fetch of 50 tickets (AI cache hot) completes in <= 3 s.

What these tests actually guard
-------------------------------
The OpenRouter network is mocked (``FakeOpenRouter`` returns a canned
per-ticket assignment with no I/O), so the measured wall-clock time is *our*
ingest pipeline overhead — request parsing, per-ticket categorization
bookkeeping, the AI cache read/write path, and the SQLite writes — NOT real
model latency. A green run therefore proves the code path stays well inside
budget; it does not (and cannot) certify OpenRouter's response time.

Their job is to catch a future regression that blows the spec budget (e.g. an
accidental N+1 query, a per-ticket sync flush, or a cache lookup that stops
short-circuiting). Because AI latency is removed, observed times sit far under
the thresholds — that head-room is expected and is exactly what lets the guard
fire loudly on a real regression.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi import FastAPI
from httpx import AsyncClient

from tests.helpers import FakeOpenRouter, existing_assignment

# ── Thresholds (mirror spec.md NFR-001 / NFR-002) ─────────────────────────────
#
# The spec budgets include real model latency, which we mock away. We keep the
# spec values as the ceiling rather than tightening them: the assertion's
# purpose is to fail when a regression pushes our own overhead toward the
# spec budget, while staying generous enough not to flake on a loaded,
# CI-less dev box.
NFR_001_COLD_BUDGET_S = 15.0  # spec.md NFR-001: cold fetch of 50 tickets <= 15 s
NFR_002_WARM_BUDGET_S = 3.0  # spec.md NFR-002: warm fetch of 50 tickets <= 3 s

# spec.md pins both NFRs to a batch of 50 tickets.
NFR_BATCH_SIZE = 50


def _hydrated(ticket_id: str, *, title: str = "Need help") -> dict[str, object]:
    """A minimal ``HydratedTicket`` payload, timestamped now so it clears the
    default 24 h lookback filter. Mirrors ``tests/test_ingest_api.py``."""
    now = datetime.now(UTC).isoformat()
    author = {"id": "u1", "name": "Customer", "email": "c@example.com", "type": "user"}
    return {
        "id": ticket_id,
        "title": title,
        "state": "open",
        "priority": None,
        "created_at": now,
        "updated_at": now,
        "author": author,
        "url": f"https://app.intercom.com/x/{ticket_id}",
        "parts": [{"author": author, "body": "please help", "created_at": now}],
    }


def _batch(n: int) -> list[dict[str, object]]:
    return [_hydrated(f"PERF-{i}") for i in range(n)]


def _canned_for(batch: list[dict[str, object]]) -> dict[str, str]:
    """A genuine (cacheable) AI assignment for every ticket in the batch, so a
    re-ingest of the unchanged conversation is a cache hit (invariant #6/#7:
    only real results are cached — fallbacks never are)."""
    return {str(t["id"]): existing_assignment(1) for t in batch}


@pytest.mark.asyncio
async def test_nfr_001_cold_ingest_within_budget(app: FastAPI, client: AsyncClient) -> None:
    """NFR-001: a cold (uncached) ingest of 50 tickets stays within budget.

    Every ticket is new → every ticket needs a fresh AI call → ``categorized``
    equals the batch size. AI is mocked, so this measures our pipeline+DB
    overhead, not model latency (see module docstring).
    """
    batch = _batch(NFR_BATCH_SIZE)
    fake = FakeOpenRouter(_canned_for(batch))
    app.state.openrouter = fake

    start = time.perf_counter()
    resp = await client.post("/tickets/ingest", json=batch)
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == NFR_BATCH_SIZE
    # Cold path: nothing cached yet → all 50 hit the (mocked) AI.
    assert body["categorized"] == NFR_BATCH_SIZE
    assert fake.calls == NFR_BATCH_SIZE

    print(f"\n[NFR-001] cold ingest of {NFR_BATCH_SIZE} tickets: {elapsed:.4f}s")
    assert elapsed < NFR_001_COLD_BUDGET_S, (
        f"cold ingest of {NFR_BATCH_SIZE} tickets took {elapsed:.3f}s, "
        f"exceeding the NFR-001 budget of {NFR_001_COLD_BUDGET_S}s"
    )


@pytest.mark.asyncio
async def test_nfr_002_warm_ingest_within_budget_and_skips_ai(
    app: FastAPI, client: AsyncClient
) -> None:
    """NFR-002: a warm (AI cache hot) re-ingest of the same 50 tickets stays
    within budget AND issues zero AI calls.

    First ingest populates the AI cache with genuine results. Re-ingesting the
    unchanged conversations must be a pure cache hit: ``categorized`` drops to
    0 and the AI client call counter does not advance — proving the cache
    short-circuit (invariant #6).
    """
    batch = _batch(NFR_BATCH_SIZE)
    fake = FakeOpenRouter(_canned_for(batch))
    app.state.openrouter = fake

    # Warm the cache (cold ingest, not timed here).
    first = await client.post("/tickets/ingest", json=batch)
    assert first.status_code == 200
    assert first.json()["categorized"] == NFR_BATCH_SIZE
    calls_after_cold = fake.calls
    assert calls_after_cold == NFR_BATCH_SIZE

    # Warm path: re-ingest the identical payload (unchanged content signature).
    start = time.perf_counter()
    resp = await client.post("/tickets/ingest", json=batch)
    elapsed = time.perf_counter() - start

    assert resp.status_code == 200
    body = resp.json()
    assert body["received"] == NFR_BATCH_SIZE
    # Warm path: every ticket served from the AI cache → no fresh categorization.
    assert body["categorized"] == 0
    # Prove the cache short-circuited: the AI client was NOT called again.
    assert fake.calls == calls_after_cold, (
        f"warm re-ingest issued {fake.calls - calls_after_cold} unexpected AI "
        "call(s); the cache did not short-circuit"
    )

    print(f"\n[NFR-002] warm ingest of {NFR_BATCH_SIZE} tickets: {elapsed:.4f}s")
    assert elapsed < NFR_002_WARM_BUDGET_S, (
        f"warm ingest of {NFR_BATCH_SIZE} tickets took {elapsed:.3f}s, "
        f"exceeding the NFR-002 budget of {NFR_002_WARM_BUDGET_S}s"
    )

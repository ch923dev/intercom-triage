"""Embedding and clustering work stays off the event loop (T207).

Encoding is synchronous CPU work (and the first call loads the model). Run on
the event loop it stalled every request in flight — token refresh, board loads —
for its duration. Async callers go through `aembed_text` / `aembed_stable_text`,
and the clustering fit runs on a worker thread.
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import clustering, embeddings


class _RecordingEncoder:
    def __init__(self, *, delay: float = 0.0) -> None:
        self.delay = delay
        self.encoded: list[str] = []
        self.threads: list[int] = []

    def encode_one(self, text: str) -> list[float]:
        self.threads.append(threading.get_ident())
        self.encoded.append(text)
        if self.delay:
            time.sleep(self.delay)
        return [float(len(text))] * embeddings.EMBEDDING_DIM


@pytest.mark.asyncio
async def test_aembed_text_encodes_on_a_worker_thread() -> None:
    encoder = _RecordingEncoder()
    embeddings.set_encoder(encoder)

    await embeddings.aembed_text("hello")

    assert encoder.threads and encoder.threads[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_event_loop_keeps_serving_while_a_slow_encode_runs() -> None:
    embeddings.set_encoder(_RecordingEncoder(delay=0.3))
    ticks = 0

    async def heartbeat() -> None:
        nonlocal ticks
        while True:
            await asyncio.sleep(0.01)
            ticks += 1

    beat = asyncio.create_task(heartbeat())
    try:
        await embeddings.aembed_text("slow")
    finally:
        beat.cancel()

    # A blocking encode would starve the heartbeat to ~0 ticks for 300 ms.
    assert ticks >= 10


@pytest.mark.asyncio
async def test_stable_text_is_encoded_once_and_keyed_by_content() -> None:
    encoder = _RecordingEncoder()
    embeddings.set_encoder(encoder)

    first = await embeddings.aembed_stable_text("playbook: reset password")
    second = await embeddings.aembed_stable_text("playbook: reset password")
    edited = await embeddings.aembed_stable_text("playbook: reset password v2")

    assert first == second
    assert edited != first
    assert encoder.encoded == ["playbook: reset password", "playbook: reset password v2"]


@pytest.mark.asyncio
async def test_swapping_the_encoder_clears_the_stable_cache() -> None:
    old = _RecordingEncoder()
    embeddings.set_encoder(old)
    await embeddings.aembed_stable_text("same text")

    new = _RecordingEncoder()
    embeddings.set_encoder(new)
    await embeddings.aembed_stable_text("same text")

    assert new.encoded == ["same text"]


@pytest.mark.asyncio
async def test_clustering_fit_and_labelling_run_on_worker_threads(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    loop_thread = threading.get_ident()
    seen: dict[str, int] = {}
    docs = [
        clustering._TicketDoc(ticket_id=f"t{i}", vector=[0.0] * 384, label_text="x")
        for i in range(3)
    ]

    async def fake_load(_session: AsyncSession) -> list[Any]:
        return docs

    def fake_fit(_docs: list[Any]) -> list[int]:
        seen["fit"] = threading.get_ident()
        return [-1] * len(_docs)

    def fake_label(_docs: list[Any], _labels: list[int]) -> list[Any]:
        seen["label"] = threading.get_ident()
        return []

    monkeypatch.setattr(clustering, "_load_resolved_docs", fake_load)
    monkeypatch.setattr(clustering, "_run_hdbscan", fake_fit)
    monkeypatch.setattr(clustering, "_label_clusters", fake_label)

    outcome = await clustering.recompute_clusters(session, min_tickets=1)

    assert outcome.outliers == 3
    assert seen["fit"] != loop_thread
    assert seen["label"] != loop_thread


@pytest.mark.asyncio
async def test_boot_warmup_loads_the_model_on_a_worker_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    loaded_on: list[int] = []
    monkeypatch.setattr(embeddings, "preload", lambda: loaded_on.append(threading.get_ident()))

    await main._warm_embedding_model()

    assert loaded_on and loaded_on[0] != threading.get_ident()


@pytest.mark.asyncio
async def test_boot_warmup_failure_is_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    """Best-effort: a missing model must not take the boot down with it."""
    from app import main

    def broken() -> None:
        raise OSError("model cache unreadable")

    monkeypatch.setattr(embeddings, "preload", broken)

    await main._warm_embedding_model()

"""T005 — `GET /health` returns 200 with the documented shape."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


async def test_health_ok_when_creds_present(client: AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["openrouter_configured"] is True
    assert data["missing_secrets"] == []
    assert data["model"] == "anthropic/claude-sonnet-4.5"
    assert "version" in data
    # Roadmap 2.3 — the needs-review threshold is surfaced for the webapp.
    assert data["review_confidence_threshold"] == 0.65


async def test_health_reports_semantic_layer(client: AsyncClient) -> None:
    # The fake encoder is injected for tests and sqlite-vec is installed, so the
    # semantic layer reports available. Clustering can never be available without
    # embeddings (it rides on them).
    resp = await client.get("/health")
    data = resp.json()
    assert data["embeddings_available"] is True
    assert data["clustering_available"] is True
    assert not (data["clustering_available"] and not data["embeddings_available"])


async def test_health_degraded_when_embeddings_enabled_but_unavailable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Operator wants embeddings (enabled by default) but the layer failed to come
    # up — the actionable degraded case the silent best-effort load used to hide.
    from app.ai import embeddings

    monkeypatch.setattr(embeddings, "encoder_available", lambda: False)
    resp = await client.get("/health")
    data = resp.json()
    assert data["embeddings_available"] is False
    assert data["clustering_available"] is False
    assert data["status"] == "degraded"

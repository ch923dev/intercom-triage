"""T005 — `GET /health` returns 200 with the documented shape."""

from __future__ import annotations

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

"""T007 — `GET /categories` returns seeded categories on a fresh DB."""

from __future__ import annotations

from httpx import AsyncClient


async def test_categories_returns_seven_seeded(client: AsyncClient) -> None:
    resp = await client.get("/categories")
    assert resp.status_code == 200
    data = resp.json()

    assert "categories" in data and "pending_proposals" in data
    assert data["pending_proposals"] == []

    cats = data["categories"]
    assert len(cats) == 7

    names_in_order = [c["name"] for c in cats]
    assert names_in_order == [
        "Urgent",
        "Bug",
        "Feature Request",
        "Question",
        "Billing",
        "Complaint",
        "Other",
    ]

    fallbacks = [c for c in cats if c["is_fallback"]]
    assert len(fallbacks) == 1 and fallbacks[0]["name"] == "Other"

    for c in cats:
        assert c["source"] == "seed"
        assert c["is_active"] is True
        assert c["color"] is not None

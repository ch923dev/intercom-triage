"""T027 — settings get / put."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_returns_seeded_defaults(client: AsyncClient) -> None:
    resp = await client.get("/settings")
    assert resp.status_code == 200
    body = resp.json()
    assert body["lookback_unit"] == "hours"
    assert body["lookback_value"] == 24
    assert body["states"] == ["open"]
    assert body["include_category_ids"] is None
    assert body["mute_alarms"] is False


@pytest.mark.asyncio
async def test_put_then_get_roundtrips(client: AsyncClient) -> None:
    new_settings = {
        "lookback_unit": "days",
        "lookback_value": 7,
        "states": ["open", "snoozed"],
        "include_category_ids": [1, 2, 3],
        "mute_alarms": True,
    }
    put = await client.put("/settings", json=new_settings)
    assert put.status_code == 200

    got = await client.get("/settings")
    assert got.json() == new_settings


@pytest.mark.asyncio
async def test_mute_alarms_defaults_false_when_omitted(client: AsyncClient) -> None:
    put = await client.put(
        "/settings",
        json={
            "lookback_unit": "hours",
            "lookback_value": 12,
            "states": ["open"],
            "include_category_ids": None,
        },
    )
    assert put.status_code == 200
    assert put.json()["mute_alarms"] is False


@pytest.mark.asyncio
async def test_put_rejects_out_of_range_lookback(client: AsyncClient) -> None:
    resp = await client.put(
        "/settings",
        json={
            "lookback_unit": "hours",
            "lookback_value": 9999,
            "states": ["open"],
            "include_category_ids": None,
        },
    )
    assert resp.status_code == 422

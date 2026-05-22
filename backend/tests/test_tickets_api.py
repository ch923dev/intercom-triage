"""T025 / T026 — ticket fetch orchestration + category override."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from httpx import AsyncClient
from pytest_httpx import HTTPXMock
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.intercom import IntercomClient
from app.config import AppConfig
from app.schemas import FilterSettings
from app.services.tickets import fetch_tickets, set_override
from tests.helpers import FakeOpenRouter, existing_assignment, intercom_conv

_SEARCH_URL = "https://api.intercom.io/conversations/search"


def _hydrate_url(conv_id: str) -> str:
    return f"https://api.intercom.io/conversations/{conv_id}?display_as=plaintext"


@pytest.mark.asyncio
async def test_fetch_without_intercom_returns_503(
    session: AsyncSession,
    test_config: AppConfig,
) -> None:
    with pytest.raises(HTTPException) as exc:
        await fetch_tickets(
            session=session,
            intercom=None,
            openrouter=None,
            config=test_config,
            filter_settings=FilterSettings(),
        )
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_fetch_orders_desc_and_assigns_fallback(
    session: AsyncSession,
    test_config: AppConfig,
    httpx_mock: HTTPXMock,
) -> None:
    httpx_mock.add_response(
        url=_SEARCH_URL,
        method="POST",
        json={"conversations": [{"id": "C1"}, {"id": "C2"}], "pages": {}},
    )
    httpx_mock.add_response(url=_hydrate_url("C1"), json=intercom_conv("C1", updated=2000))
    httpx_mock.add_response(url=_hydrate_url("C2"), json=intercom_conv("C2", updated=3000))

    intercom = IntercomClient("token")
    try:
        out = await fetch_tickets(
            session=session,
            intercom=intercom,
            openrouter=None,  # no AI → every ticket degrades to fallback
            config=test_config,
            filter_settings=FilterSettings(),
        )
    finally:
        await intercom.aclose()

    assert [t.id for t in out] == ["C2", "C1"]  # updated_at descending
    assert all(t.category_id is not None for t in out)
    assert all(t.ai_confidence == 0.0 for t in out)


@pytest.mark.asyncio
async def test_warm_cache_skips_repeat_ai_calls(
    session: AsyncSession,
    test_config: AppConfig,
    httpx_mock: HTTPXMock,
) -> None:
    fake = FakeOpenRouter({"C1": existing_assignment(1)})
    for _ in range(2):
        httpx_mock.add_response(
            url=_SEARCH_URL,
            method="POST",
            json={"conversations": [{"id": "C1"}], "pages": {}},
        )
        httpx_mock.add_response(
            url=_hydrate_url("C1"),
            json=intercom_conv("C1", updated=2000),
        )

    intercom = IntercomClient("token")
    filter_settings = FilterSettings()
    try:
        first = await fetch_tickets(
            session=session,
            intercom=intercom,
            openrouter=fake,  # type: ignore[arg-type]
            config=test_config,
            filter_settings=filter_settings,
        )
        assert fake.calls == 1
        second = await fetch_tickets(
            session=session,
            intercom=intercom,
            openrouter=fake,  # type: ignore[arg-type]
            config=test_config,
            filter_settings=filter_settings,
        )
    finally:
        await intercom.aclose()

    assert fake.calls == 1  # warm cache — no new OpenRouter call
    assert first[0].category_id == 1
    assert second[0].category_id == 1


@pytest.mark.asyncio
async def test_override_endpoint(client: AsyncClient) -> None:
    resp = await client.patch("/tickets/INT-9/category", json={"category_id": 2})
    assert resp.status_code == 200 and resp.json()["category_id"] == 2


@pytest.mark.asyncio
async def test_override_unknown_category_404(client: AsyncClient) -> None:
    resp = await client.patch("/tickets/INT-9/category", json={"category_id": 9999})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_override_applied_in_fetch(
    session: AsyncSession,
    test_config: AppConfig,
    httpx_mock: HTTPXMock,
) -> None:
    await set_override(session, "C1", 5)  # Billing

    httpx_mock.add_response(
        url=_SEARCH_URL,
        method="POST",
        json={"conversations": [{"id": "C1"}], "pages": {}},
    )
    # updated_at well in the past → before the override's set_at → override holds.
    httpx_mock.add_response(url=_hydrate_url("C1"), json=intercom_conv("C1", updated=1000))

    intercom = IntercomClient("token")
    try:
        out = await fetch_tickets(
            session=session,
            intercom=intercom,
            openrouter=None,
            config=test_config,
            filter_settings=FilterSettings(),
        )
    finally:
        await intercom.aclose()

    assert out[0].category_id == 5 and out[0].user_override is True


@pytest.mark.asyncio
async def test_override_invalidated_when_ticket_advances(
    session: AsyncSession,
    test_config: AppConfig,
    httpx_mock: HTTPXMock,
) -> None:
    await set_override(session, "C1", 5)

    httpx_mock.add_response(
        url=_SEARCH_URL,
        method="POST",
        json={"conversations": [{"id": "C1"}], "pages": {}},
    )
    # updated_at far in the future → past the override's set_at → override dropped.
    httpx_mock.add_response(
        url=_hydrate_url("C1"),
        json=intercom_conv("C1", updated=4_000_000_000),
    )

    intercom = IntercomClient("token")
    try:
        out = await fetch_tickets(
            session=session,
            intercom=intercom,
            openrouter=None,
            config=test_config,
            filter_settings=FilterSettings(),
        )
    finally:
        await intercom.aclose()

    assert out[0].user_override is False


@pytest.mark.asyncio
async def test_fetch_embeds_followup_and_note(
    session: AsyncSession,
    test_config: AppConfig,
    httpx_mock: HTTPXMock,
) -> None:
    """T048 — `/tickets/fetch` joins the follow-up + note rows by ticket id."""
    from datetime import datetime

    from app.services.followups import set_followup
    from app.services.notes import set_note

    await set_followup(session, "C1", datetime(2030, 1, 1, 12, 0, 0), "call back")
    await set_note(session, "C1", "escalate to tier 2")

    httpx_mock.add_response(
        url=_SEARCH_URL,
        method="POST",
        json={"conversations": [{"id": "C1"}], "pages": {}},
    )
    httpx_mock.add_response(url=_hydrate_url("C1"), json=intercom_conv("C1", updated=1000))

    intercom = IntercomClient("token")
    try:
        out = await fetch_tickets(
            session=session,
            intercom=intercom,
            openrouter=None,
            config=test_config,
            filter_settings=FilterSettings(),
        )
    finally:
        await intercom.aclose()

    assert out[0].followup is not None and out[0].followup.reason == "call back"
    assert out[0].note is not None and out[0].note.body == "escalate to tier 2"

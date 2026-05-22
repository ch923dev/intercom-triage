"""T008–T011 — Intercom client: HTML stripping, deep links, search, hydration."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from app.clients.intercom import IntercomClient, strip_html
from tests.helpers import intercom_conv


def test_strip_html_newlines_and_entities() -> None:
    assert strip_html("<p>Hello</p><br>World") == "Hello\n\nWorld"
    assert strip_html("a &amp; b") == "a & b"
    assert strip_html(None) == ""
    assert "<" not in strip_html("<div><span>x</span></div>")


@pytest.mark.asyncio
async def test_deep_link_needs_workspace_id() -> None:
    client = IntercomClient("token")
    try:
        assert client.deep_link("123") is None
        client.workspace_id = "wkspc"
        assert client.deep_link("123") == "https://app.intercom.com/a/apps/wkspc/conversations/123"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_resolve_workspace_id(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/me",
        json={"type": "admin", "id": "1", "app": {"id_code": "abc123"}},
    )
    client = IntercomClient("token")
    try:
        wid = await client.resolve_workspace_id()
        assert wid == "abc123"
        assert client.workspace_id == "abc123"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_search_paginates_and_caps(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/search",
        method="POST",
        json={
            "conversations": [{"id": "1"}, {"id": "2"}],
            "pages": {"next": {"starting_after": "tok2"}},
        },
    )
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/search",
        method="POST",
        json={"conversations": [{"id": "3"}, {"id": "4"}], "pages": {}},
    )
    client = IntercomClient("token")
    try:
        ids = await client.search_conversation_ids(
            threshold_unix=0,
            states=["open"],
            max_tickets=100,
        )
        assert ids == ["1", "2", "3", "4"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_search_respects_max_tickets(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/search",
        method="POST",
        json={
            "conversations": [{"id": str(i)} for i in range(5)],
            "pages": {},
        },
    )
    client = IntercomClient("token")
    try:
        ids = await client.search_conversation_ids(
            threshold_unix=0,
            states=["open"],
            max_tickets=3,
        )
        assert ids == ["0", "1", "2"]
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_hydration_isolates_failures(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/A?display_as=plaintext",
        json=intercom_conv("A"),
    )
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/B?display_as=plaintext",
        status_code=500,
    )
    httpx_mock.add_response(
        url="https://api.intercom.io/conversations/C?display_as=plaintext",
        json=intercom_conv("C"),
    )
    client = IntercomClient("token")
    try:
        out = await client.hydrate_many(["A", "B", "C"])
        assert {t.id for t in out} == {"A", "C"}
        for ticket in out:
            assert "<" not in ticket.parts[0].body
    finally:
        await client.aclose()

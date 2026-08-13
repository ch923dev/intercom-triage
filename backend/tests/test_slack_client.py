"""SlackClient tests — the HTTP-200-means-nothing contract, retries, redaction.

Uses pytest-httpx so the client builds its own AsyncClient (real Authorization
header) and we can assert on the request it actually emitted.
"""

from __future__ import annotations

import json
import logging

import pytest
from pytest_httpx import HTTPXMock

from app.clients.slack import SlackAuthError, SlackClient, SlackError

_URL = "https://slack.com/api/chat.postMessage"


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op asyncio.sleep so retry backoff doesn't slow the suite."""

    async def _noop(_: float) -> None:
        return None

    monkeypatch.setattr("app.clients.slack.asyncio.sleep", _noop)


async def _post(client: SlackClient, **kwargs: object) -> str:
    try:
        return await client.post_message(channel="C123", text="Bug detected", **kwargs)  # type: ignore[arg-type]
    finally:
        await client.aclose()


async def test_ok_returns_the_message_ts(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=_URL,
        method="POST",
        json={"ok": True, "ts": "1723456789.000100", "channel": "C123"},
    )
    assert await _post(SlackClient("xoxb-test")) == "1723456789.000100"

    req = httpx_mock.get_requests()[0]
    assert req.headers["Authorization"] == "Bearer xoxb-test"
    assert json.loads(req.content)["channel"] == "C123"


async def test_http_200_with_ok_false_raises_and_does_not_retry(httpx_mock: HTTPXMock) -> None:
    """Slack reports application errors with a 200. Treating the status code as
    the verdict would mark the alert delivered and lose it permanently."""
    httpx_mock.add_response(
        url=_URL, method="POST", json={"ok": False, "error": "channel_not_found"}
    )
    with pytest.raises(SlackError) as exc:
        await _post(SlackClient("xoxb-test"))
    assert exc.value.error == "channel_not_found"
    assert len(httpx_mock.get_requests()) == 1


async def test_invalid_auth_raises_slack_auth_error_without_retrying(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": False, "error": "invalid_auth"})
    with pytest.raises(SlackAuthError):
        await _post(SlackClient("xoxb-bad"))
    assert len(httpx_mock.get_requests()) == 1


async def test_ok_without_a_ts_is_a_failure(httpx_mock: HTTPXMock) -> None:
    """No ts means no way to thread a later escalation, and no proof of what
    was posted — so it is not a success."""
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": True})
    with pytest.raises(SlackError):
        await _post(SlackClient("xoxb-test"))


async def test_ratelimited_is_retried_then_succeeds(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": False, "error": "ratelimited"})
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": True, "ts": "1.1"})
    assert await _post(SlackClient("xoxb-test")) == "1.1"
    assert len(httpx_mock.get_requests()) == 2


async def test_http_429_with_retry_after_is_honored(httpx_mock: HTTPXMock) -> None:
    slept: list[float] = []

    httpx_mock.add_response(url=_URL, method="POST", status_code=429, headers={"Retry-After": "7"})
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": True, "ts": "2.2"})

    client = SlackClient("xoxb-test")

    async def _record(delay: float) -> None:
        slept.append(delay)

    import app.clients.slack as slack_mod

    original = slack_mod.asyncio.sleep
    slack_mod.asyncio.sleep = _record  # type: ignore[assignment]
    try:
        assert await _post(client) == "2.2"
    finally:
        slack_mod.asyncio.sleep = original  # type: ignore[assignment]

    assert slept and slept[0] >= 7.0


async def test_5xx_is_retried_and_gives_up_after_max_attempts(httpx_mock: HTTPXMock) -> None:
    for _ in range(3):
        httpx_mock.add_response(url=_URL, method="POST", status_code=503)
    with pytest.raises(SlackError):
        await _post(SlackClient("xoxb-test"))
    assert len(httpx_mock.get_requests()) == 3


async def test_thread_ts_is_sent_when_given(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": True, "ts": "3.3"})
    await _post(SlackClient("xoxb-test"), thread_ts="1723456789.000100")
    body = json.loads(httpx_mock.get_requests()[0].content)
    assert body["thread_ts"] == "1723456789.000100"


async def test_thread_ts_is_absent_when_not_given(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": True, "ts": "4.4"})
    await _post(SlackClient("xoxb-test"))
    assert "thread_ts" not in json.loads(httpx_mock.get_requests()[0].content)


async def test_message_text_never_reaches_the_logs(
    httpx_mock: HTTPXMock, caplog: pytest.LogCaptureFixture
) -> None:
    """NFR-016 — the evidence quote is customer conversation text. It rides in
    `text`/`blocks` and must never appear in a log record, on success or on
    failure."""
    secret = "our entire customer database vanished"
    httpx_mock.add_response(url=_URL, method="POST", json={"ok": False, "error": "invalid_auth"})

    client = SlackClient("xoxb-test")
    with caplog.at_level(logging.DEBUG), pytest.raises(SlackAuthError):
        try:
            await client.post_message(
                channel="C123",
                text=secret,
                blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": secret}}],
                ticket_id="T1",
            )
        finally:
            await client.aclose()

    rendered = "\n".join(record.getMessage() for record in caplog.records)
    assert secret not in rendered
    # The identifier is fine — that is the whole point of logging by id.
    assert "T1" in rendered

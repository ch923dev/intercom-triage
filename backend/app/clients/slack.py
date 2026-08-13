"""Slack Web API client (post-only). Reference: US-044, FR-078, NFR-015/016.

Bot token + `chat.postMessage`, deliberately NOT an incoming webhook: a webhook
returns the literal string `ok` with no message `ts`, which makes threaded
follow-ups (`thread_ts`) structurally impossible. The `ts` returned here is what
lets a severity escalation land as a reply under the original alert instead of
as a second top-level message.

Required bot scopes: `chat:write`, plus `chat:write.public` to post into a
public channel the bot has not been invited to.

Two things differ from the other clients in this package and are easy to get
wrong:

1. **Slack signals application errors with HTTP 200.** A bad channel or a
   revoked token comes back as `200 {"ok": false, "error": "..."}`. A
   status-code check would read that as success and mark the alert delivered,
   losing it forever. The BODY is the source of truth.
2. **Nothing that could contain conversation text is ever logged** — not the
   message, not the blocks, not the attachments, not the evidence quote.
   `logged_call` receives identifiers only (NFR-006, extended to `bug_evidence`
   by NFR-016).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from app.observability import logged_call

SLACK_API_BASE = "https://slack.com/api"

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)
# Slack error codes worth another attempt. Everything else — a bad channel, a
# revoked token, a malformed payload — is permanent: retrying burns the cycle's
# budget and lands in exactly the same place.
_RETRYABLE_SLACK_ERRORS = frozenset(
    ("ratelimited", "rate_limited", "service_unavailable", "internal_error", "fatal_error")
)
# A revoked/invalid token is not a per-message problem; surface it distinctly so
# the caller can stop hammering and the operator sees a real cause.
_AUTH_SLACK_ERRORS = frozenset(
    ("invalid_auth", "not_authed", "account_inactive", "token_revoked", "token_expired")
)
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 0.5

logger = logging.getLogger(__name__)


class SlackError(Exception):
    """Raised on any Slack failure. `error` is Slack's own code when it gave one."""

    def __init__(self, message: str, *, error: str | None = None) -> None:
        super().__init__(message)
        self.error = error


class SlackAuthError(SlackError):
    """The bot token is missing, invalid, or revoked."""


def _backoff_with_jitter(attempt: int) -> float:
    """Backoff seconds for a 0-based attempt: BASE * 2**attempt * jitter[0.8,1.2]."""
    base: float = _BASE_BACKOFF_SECONDS * (2**attempt)
    jitter: float = random.uniform(0.8, 1.2)  # noqa: S311 — non-crypto jitter
    return base * jitter


def _parse_retry_after(header: str | None) -> float | None:
    """Numeric-seconds `Retry-After` only; the HTTP-date form falls back to backoff."""
    if header is None:
        return None
    try:
        return max(0.0, float(header.strip()))
    except ValueError:
        return None


class SlackClient:
    def __init__(
        self,
        bot_token: str,
        *,
        base: str = SLACK_API_BASE,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=base,
            headers={
                "Authorization": f"Bearer {bot_token}",
                "Content-Type": "application/json; charset=utf-8",
            },
            timeout=httpx.Timeout(30.0),
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def post_message(
        self,
        *,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        ticket_id: str | None = None,
    ) -> str:
        """Post to `channel` and return the message `ts`.

        `text` doubles as the notification/fallback line for clients that cannot
        render `blocks`. `thread_ts` turns the post into a reply under an
        existing message — that is how an escalation avoids becoming a second
        top-level alert.

        `attachments` exists for one reason: the coloured left rail that encodes
        severity at a glance is only reachable through an attachment's `color`,
        which Block Kit has no equivalent for. Blocks nested inside the
        attachment render identically otherwise.

        Raises `SlackAuthError` on a token problem and `SlackError` on anything
        else. Both leave the caller's row in the outbox, which is the intended
        failure mode: an alert that posts twice is recoverable, one that is
        marked delivered without being delivered is not.
        """
        body: dict[str, Any] = {"channel": channel, "text": text}
        if blocks is not None:
            body["blocks"] = blocks
        if attachments is not None:
            body["attachments"] = attachments
        if thread_ts is not None:
            body["thread_ts"] = thread_ts

        last_error: Exception | None = None

        for attempt in range(_MAX_ATTEMPTS):
            try:
                # Identifiers only — never `text`, `blocks`, `attachments`, or
                # the evidence quote.
                async with logged_call("slack.post_message", ticket_id=ticket_id):
                    resp = await self._http.post("/chat.postMessage", json=body)

                if resp.status_code in _RETRY_STATUSES:
                    if attempt >= _MAX_ATTEMPTS - 1:
                        raise SlackError(f"POST /chat.postMessage → {resp.status_code}")
                    delay = _backoff_with_jitter(attempt)
                    if resp.status_code == 429:
                        retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                        if retry_after is not None:
                            delay = max(delay, retry_after)
                    logger.warning(
                        "slack.post_message retrying attempt=%d/%d status=%d delay_s=%.2f",
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        resp.status_code,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code != 200:
                    raise SlackError(f"POST /chat.postMessage → {resp.status_code}")

                # HTTP 200 does NOT mean success. Slack reports application
                # errors in the body, so the body is what decides.
                data = resp.json()
                if not isinstance(data, dict):
                    raise SlackError("unexpected response shape")

                if data.get("ok") is True:
                    ts = data.get("ts")
                    if not isinstance(ts, str) or not ts:
                        # Without a ts we cannot thread an escalation later, and
                        # we cannot prove which message we posted.
                        raise SlackError("response was ok but carried no message ts")
                    return ts

                slack_error = data.get("error")
                code = slack_error if isinstance(slack_error, str) else "unknown_error"
                if code in _AUTH_SLACK_ERRORS:
                    raise SlackAuthError(
                        f"chat.postMessage rejected: {code} (check SLACK_BOT_TOKEN)",
                        error=code,
                    )
                if code in _RETRYABLE_SLACK_ERRORS and attempt < _MAX_ATTEMPTS - 1:
                    delay = _backoff_with_jitter(attempt)
                    retry_after = _parse_retry_after(resp.headers.get("Retry-After"))
                    if retry_after is not None:
                        delay = max(delay, retry_after)
                    logger.warning(
                        "slack.post_message retrying attempt=%d/%d error=%s delay_s=%.2f",
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        code,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise SlackError(f"chat.postMessage rejected: {code}", error=code)

            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt >= _MAX_ATTEMPTS - 1:
                    break
                delay = _backoff_with_jitter(attempt)
                logger.warning(
                    "slack.post_message retrying attempt=%d/%d error=%r delay_s=%.2f",
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    str(exc),
                    delay,
                )
                await asyncio.sleep(delay)

        raise SlackError(f"exhausted retries: {last_error}")

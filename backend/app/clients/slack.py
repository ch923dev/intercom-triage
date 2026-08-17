"""Slack Web API client (outbound writes only). Reference: US-044, FR-078,
FR-086, NFR-015/016.

Bot token + `chat.postMessage` / `chat.update`, deliberately NOT an incoming
webhook: a webhook returns the literal string `ok` with no message `ts`, which
makes threaded follow-ups (`thread_ts`) structurally impossible. The `ts`
returned here is what lets a severity escalation land as a reply under the
original alert instead of as a second top-level message — and what lets an
acknowledgement rewrite that original message in place (§22).

Outbound only, and that is a design constraint rather than an omission: nothing
here accepts a request FROM Slack, so the product needs no publicly reachable
address, no signing secret, and no addition to the auth allowlist (FR-088,
invariant #15).

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

Consequence of (1) that is easy to reintroduce: the verdict is read INSIDE the
`logged_call` block. Read after it, a rejected message logs
`external_call op=slack.post_message outcome=ok` — because the HTTP request did
succeed — and an operator debugging "why did nothing post?" sees a log line
saying Slack accepted it. Observed live during the broken-token test.

Both verbs share ONE retry/verdict loop (`_call`) for that reason: a second
hand-written loop would be where the body-not-status check, the per-attempt
`outcome=error` logging, or the auth-error classification quietly fails to get
copied.
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


class _Retry(Exception):
    """Internal: this attempt failed but is worth repeating.

    Raised from inside the `logged_call` block so a failed attempt is logged as
    `outcome=error` rather than `outcome=ok`. Never escapes this module.
    """

    def __init__(self, reason: str, *, retry_after: float | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


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


def _ts_or_raise(resp: httpx.Response, *, last_attempt: bool, endpoint: str) -> str:
    """The message `ts`, or an exception. There is no third outcome.

    Called from inside `logged_call` so that every way of failing — including
    Slack's HTTP-200-with-`ok:false` — is logged as `outcome=error`. `_Retry`
    means "try again"; anything else is permanent. `endpoint` only names the call
    in the error text, so a failure says which verb failed.
    """
    if resp.status_code in _RETRY_STATUSES:
        if last_attempt:
            raise SlackError(f"POST {endpoint} → {resp.status_code}")
        raise _Retry(
            f"status={resp.status_code}",
            retry_after=(
                _parse_retry_after(resp.headers.get("Retry-After"))
                if resp.status_code == 429
                else None
            ),
        )

    if resp.status_code != 200:
        raise SlackError(f"POST {endpoint} → {resp.status_code}")

    # HTTP 200 does NOT mean success. Slack reports application errors in the
    # body, so the body is what decides.
    data = resp.json()
    if not isinstance(data, dict):
        raise SlackError("unexpected response shape")

    if data.get("ok") is True:
        ts = data.get("ts")
        if not isinstance(ts, str) or not ts:
            # Without a ts we cannot thread an escalation later, and we cannot
            # prove which message we posted.
            raise SlackError("response was ok but carried no message ts")
        return ts

    slack_error = data.get("error")
    code = slack_error if isinstance(slack_error, str) else "unknown_error"
    if code in _AUTH_SLACK_ERRORS:
        raise SlackAuthError(
            f"{endpoint} rejected: {code} (check SLACK_BOT_TOKEN)",
            error=code,
        )
    if code in _RETRYABLE_SLACK_ERRORS and not last_attempt:
        raise _Retry(
            f"error={code}",
            retry_after=_parse_retry_after(resp.headers.get("Retry-After")),
        )
    raise SlackError(f"{endpoint} rejected: {code}", error=code)


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

    async def _call(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        op: str,
        ticket_id: str | None,
    ) -> str:
        """POST `body` to `endpoint`, retrying, and return the message `ts`.

        The single retry/verdict loop behind every verb. `op` names the call in
        the log; `ticket_id` is the only payload-derived value that may appear
        there — never `text`, `blocks`, `attachments`, or the evidence quote
        (NFR-016).
        """
        last_error: Exception | None = None

        for attempt in range(_MAX_ATTEMPTS):
            try:
                # The verdict is read INSIDE the block so Slack's
                # HTTP-200-with-`ok:false` is timed and logged as the failure it
                # is, rather than as `outcome=ok`.
                async with logged_call(op, ticket_id=ticket_id):
                    resp = await self._http.post(endpoint, json=body)
                    return _ts_or_raise(
                        resp,
                        last_attempt=attempt >= _MAX_ATTEMPTS - 1,
                        endpoint=endpoint,
                    )

            except _Retry as retry:
                delay = _backoff_with_jitter(attempt)
                if retry.retry_after is not None:
                    delay = max(delay, retry.retry_after)
                logger.warning(
                    "%s retrying attempt=%d/%d %s delay_s=%.2f",
                    op,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    retry.reason,
                    delay,
                )
                await asyncio.sleep(delay)

            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt >= _MAX_ATTEMPTS - 1:
                    break
                delay = _backoff_with_jitter(attempt)
                logger.warning(
                    "%s retrying attempt=%d/%d error=%r delay_s=%.2f",
                    op,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    str(exc),
                    delay,
                )
                await asyncio.sleep(delay)

        raise SlackError(f"exhausted retries: {last_error}")

    async def update_message(
        self,
        *,
        channel: str,
        ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        ticket_id: str | None = None,
    ) -> str:
        """Rewrite an existing message in place and return its `ts`.

        `channel` + `ts` identify the message, and both come from the row we
        stored when we posted it — so this can only ever edit our own alert.
        There is no `thread_ts`: an edit is not a reply.

        Used to fold an acknowledgement into the original alert card (FR-086)
        instead of posting a second message. The caller rebuilds the card with
        the same builder as the original post, which is what keeps the evidence
        quote out of `text` on this path too.
        """
        body: dict[str, Any] = {"channel": channel, "ts": ts, "text": text}
        if blocks is not None:
            body["blocks"] = blocks
        if attachments is not None:
            body["attachments"] = attachments
        return await self._call(
            "/chat.update", body, op="slack.update_message", ticket_id=ticket_id
        )

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
        return await self._call(
            "/chat.postMessage", body, op="slack.post_message", ticket_id=ticket_id
        )

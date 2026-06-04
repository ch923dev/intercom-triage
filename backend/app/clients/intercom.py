"""Intercom REST API client. Reference: plan.md §6 (Intercom integration).

The backend polls Intercom's *official, documented* API directly with a
workspace Access Token (cross-package invariant #1).

Returns raw JSON dicts — normalization to `HydratedTicket` happens downstream in
`app.services.intercom_normalizer`, keeping this client thin (mirrors how
`OpenRouterClient` returns the raw model string and parsing lives in the
pipeline).

Two calls per changed conversation: `GET /conversations/{id}` for the thread,
plus a TTL-cached `GET /contacts/{id}` for the customer "User data" panel fields
(location / timezone / phone / company) that the lightweight conversation
payload omits.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.observability import logged_call

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 0.5

logger = logging.getLogger(__name__)


class IntercomError(Exception):
    """Raised on any Intercom upstream failure. `status` is the HTTP code when
    the failure was an HTTP response (None for transport-level errors)."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class IntercomAuthError(IntercomError):
    """401/403 — the Access Token is missing, invalid, or revoked. Distinct so
    the caller can surface 'bad/expired token' rather than a generic failure."""


def _backoff_with_jitter(attempt: int) -> float:
    """Backoff seconds for a 0-based attempt: BASE * 2**attempt * jitter[0.8,1.2]."""
    base: float = _BASE_BACKOFF_SECONDS * (2**attempt)
    jitter: float = random.uniform(0.8, 1.2)  # noqa: S311 — non-crypto jitter
    return base * jitter


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    """Computed backoff, raised to honor Intercom's rate-limit headers on a 429.

    Intercom returns `X-RateLimit-Reset` (a UNIX epoch-seconds timestamp for when
    the current 10-second window resets) and sometimes `Retry-After` (seconds).
    Wait at least until the window resets so the retry isn't an instant re-429.
    """
    delay = _backoff_with_jitter(attempt)
    if resp.status_code != 429:
        return delay
    retry_after = resp.headers.get("Retry-After")
    if retry_after:
        try:
            delay = max(delay, float(retry_after.strip()))
        except ValueError:
            pass
    reset = resp.headers.get("X-RateLimit-Reset")
    if reset:
        try:
            delay = max(delay, float(reset.strip()) - time.time())
        except ValueError:
            pass
    return max(0.0, delay)


class IntercomClient:
    def __init__(
        self,
        access_token: str,
        *,
        base: str = "https://api.intercom.io",
        version: str = "2.13",
        contact_cache_ttl_seconds: int = 300,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=base,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Intercom-Version": version,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0),
        )
        self._contact_cache_ttl = contact_cache_ttl_seconds
        # contact_id → (monotonic_expiry, raw_contact_or_None). Negative hits
        # (None) are cached too so a missing contact isn't re-fetched per convo.
        self._contact_cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        op: str,
        json: dict[str, Any] | None = None,
        ticket_id: str | None = None,
    ) -> httpx.Response:
        """Shared request with retry/backoff. Returns the raw 2xx response.

        Retries 429 + 5xx + transient network errors (up to `_MAX_ATTEMPTS`),
        honoring rate-limit headers on 429. 401/403 → `IntercomAuthError`
        immediately; other non-2xx → `IntercomError`. A 404 raises `IntercomError`
        with `status=404` so callers (e.g. `get_contact`) can treat it as absence.
        """
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                async with logged_call(op, ticket_id=ticket_id):
                    resp = await self._http.request(method, path, json=json)

                if resp.is_success:
                    return resp

                if resp.status_code in (401, 403):
                    raise IntercomAuthError(
                        f"{method} {path} → {resp.status_code} (check INTERCOM_ACCESS_TOKEN)",
                        status=resp.status_code,
                    )

                if resp.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                    delay = _retry_delay(resp, attempt)
                    logger.warning(
                        "intercom %s retrying attempt=%d/%d status=%d delay_s=%.2f",
                        op,
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        resp.status_code,
                        delay,
                    )
                    await asyncio.sleep(delay)
                    continue

                raise IntercomError(
                    f"{method} {path} → {resp.status_code}", status=resp.status_code
                )

            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt >= _MAX_ATTEMPTS - 1:
                    break
                delay = _backoff_with_jitter(attempt)
                logger.warning(
                    "intercom %s retrying attempt=%d/%d error=%r delay_s=%.2f",
                    op,
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    str(exc),
                    delay,
                )
                await asyncio.sleep(delay)

        raise IntercomError(f"exhausted retries: {last_error}") from last_error

    async def search_conversations(
        self,
        *,
        states: Sequence[str],
        updated_after: int | None = None,
        per_page: int = 150,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield conversation *summaries* (no `conversation_parts`) via
        `POST /conversations/search`, cursor-paginated and newest-first.

        Filters `state` (single or OR-grouped) AND `updated_at > updated_after`
        (epoch seconds) when given. The caller fetches full detail per id for the
        new/changed ones (skip-known happens in the sync service).
        """
        clauses: list[dict[str, Any]] = []
        if len(states) == 1:
            clauses.append({"field": "state", "operator": "=", "value": states[0]})
        elif states:
            clauses.append(
                {
                    "operator": "OR",
                    "value": [{"field": "state", "operator": "=", "value": s} for s in states],
                }
            )
        if updated_after is not None:
            clauses.append({"field": "updated_at", "operator": ">", "value": updated_after})

        query: dict[str, Any] = {"operator": "AND", "value": clauses}
        starting_after: str | None = None
        while True:
            pagination: dict[str, Any] = {"per_page": per_page}
            if starting_after:
                pagination["starting_after"] = starting_after
            body = {
                "query": query,
                "pagination": pagination,
                "sort": {"field": "updated_at", "order": "descending"},
            }
            resp = await self._request(
                "POST", "/conversations/search", op="intercom.search", json=body
            )
            data = resp.json()
            conversations = data.get("conversations")
            if isinstance(conversations, list):
                for convo in conversations:
                    if isinstance(convo, dict):
                        yield convo
            next_page = (data.get("pages") or {}).get("next")
            # Search pagination: `pages.next` is an object carrying the cursor.
            starting_after = (
                next_page.get("starting_after") if isinstance(next_page, dict) else None
            )
            if not starting_after:
                break

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        """`GET /conversations/{id}` — full thread with `conversation_parts`."""
        resp = await self._request(
            "GET",
            f"/conversations/{conversation_id}",
            op="intercom.detail",
            ticket_id=conversation_id,
        )
        result: dict[str, Any] = resp.json()
        return result

    async def get_contact(self, contact_id: str) -> dict[str, Any] | None:
        """`GET /contacts/{id}` for the customer panel fields. TTL-cached;
        returns None on 404 (caller degrades to the conversation-level author).
        """
        now = time.monotonic()
        cached = self._contact_cache.get(contact_id)
        if cached is not None and cached[0] > now:
            return cached[1]
        try:
            resp = await self._request("GET", f"/contacts/{contact_id}", op="intercom.contact")
        except IntercomError as exc:
            if exc.status == 404:
                self._contact_cache[contact_id] = (now + self._contact_cache_ttl, None)
                return None
            raise
        contact: dict[str, Any] = resp.json()
        self._contact_cache[contact_id] = (now + self._contact_cache_ttl, contact)
        return contact

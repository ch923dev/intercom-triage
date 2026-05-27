"""OpenRouter HTTP client. Reference: plan.md §7, tasks.md T012.

OpenAI-compatible `/chat/completions`. Returns the raw model output string;
parsing + resolution happen downstream (`app.ai.pipeline`).
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

import httpx

from app.metrics import metrics
from app.observability import logged_call

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

_RETRY_STATUSES = {429, 500, 502, 503, 504}
_RETRYABLE_EXCEPTIONS = (
    httpx.TimeoutException,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)
_MAX_ATTEMPTS = 3
_BASE_BACKOFF_SECONDS = 0.5

logger = logging.getLogger(__name__)


class OpenRouterError(Exception):
    """Raised on any OpenRouter upstream failure. Categorization degrades to fallback."""


def _backoff_with_jitter(attempt: int) -> float:
    """Return backoff seconds for the given attempt index (0-based).

    Formula: ``BASE * 2**attempt * jitter``, where jitter is a uniform
    multiplier in [0.8, 1.2] to avoid thundering-herd effects.
    """
    base: float = _BASE_BACKOFF_SECONDS * (2**attempt)
    jitter: float = random.uniform(0.8, 1.2)  # noqa: S311 — non-crypto jitter
    return base * jitter


def _record_usage(model: str, data: dict[str, Any]) -> None:
    """Record token usage from an OpenRouter response into the cost meter.

    Defensive by design: ``usage`` is absent on some responses/endpoints, and
    individual token fields may be missing or non-int. Any such case is a no-op
    (or skips the bad field) — capturing the meter must never break the call.
    """
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return

    def _as_int(value: object) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) else 0

    prompt_tokens = _as_int(usage.get("prompt_tokens"))
    completion_tokens = _as_int(usage.get("completion_tokens"))
    if prompt_tokens == 0 and completion_tokens == 0:
        # Nothing meaningful to record (e.g. usage present but empty).
        return
    metrics.record_usage(model, prompt_tokens, completion_tokens)


def _parse_retry_after(header: str | None) -> float | None:
    """Parse the ``Retry-After`` header value.

    Supports the numeric-seconds form (``Retry-After: 30``).  The HTTP-date
    form is not handled — we return ``None`` and fall back to computed backoff.
    """
    if header is None:
        return None
    stripped = header.strip()
    try:
        value = float(stripped)
        return max(0.0, value)
    except ValueError:
        return None


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        referer: str = "http://localhost:4000",
        title: str = "Intercom Triage",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=OPENROUTER_BASE,
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": referer,
                "X-Title": title,
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(60.0),
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        ticket_id: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        """Call `/chat/completions` and return the assistant message content.

        Request shape per plan §7: `temperature=0.1`, `max_tokens=400`,
        `response_format={type:"json_object"}`.

        ``response_format`` defaults to ``{"type": "json_object"}`` so existing
        callers (e.g. the playbook drafter) are unaffected.  The categorization
        pipeline passes a strict ``{"type": "json_schema", ...}`` value to enforce
        the response shape natively (roadmap 2.1).  An endpoint that rejects the
        schema returns a non-retryable 4xx, which surfaces as ``OpenRouterError``
        and degrades to the caller's per-ticket fallback — ingest never aborts.

        Retries up to ``_MAX_ATTEMPTS`` times on 429/5xx and transient network
        errors, with exponential backoff plus jitter.  Non-retryable statuses
        (400, 401, 403, 404 …) and malformed responses raise ``OpenRouterError``
        immediately.  On exhaustion the final error is re-raised as
        ``OpenRouterError`` so the caller's fallback logic is unaffected.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 400,
            "response_format": response_format or {"type": "json_object"},
        }

        last_error: Exception | None = None

        for attempt in range(_MAX_ATTEMPTS):
            try:
                async with logged_call("openrouter.complete", ticket_id=ticket_id):
                    resp = await self._http.post("/chat/completions", json=body)

                if resp.status_code == 200:
                    data = resp.json()
                    try:
                        content = data["choices"][0]["message"]["content"]
                    except (KeyError, IndexError, TypeError) as exc:
                        raise OpenRouterError(f"unexpected response shape: {exc}") from exc
                    if not isinstance(content, str):
                        raise OpenRouterError("response content was not a string")
                    # Cost meter (roadmap 1.4). Best-effort: a usage-capture
                    # failure must never break a successful completion.
                    try:
                        if isinstance(data, dict):
                            _record_usage(model, data)
                    except Exception:
                        logger.debug("openrouter usage capture failed", exc_info=True)
                    return content

                if resp.status_code in _RETRY_STATUSES and attempt < _MAX_ATTEMPTS - 1:
                    delay = _backoff_with_jitter(attempt)
                    if resp.status_code == 429:
                        ra = _parse_retry_after(resp.headers.get("Retry-After"))
                        if ra is not None:
                            delay = max(delay, ra)
                    logger.warning(
                        "openrouter.complete retrying attempt=%d/%d status=%d delay_s=%.2f ticket_id=%s",
                        attempt + 1,
                        _MAX_ATTEMPTS,
                        resp.status_code,
                        delay,
                        ticket_id,
                    )
                    await asyncio.sleep(delay)
                    continue

                # Non-retryable status (or final attempt with a retryable status).
                raise OpenRouterError(f"POST /chat/completions → {resp.status_code}")

            except _RETRYABLE_EXCEPTIONS as exc:
                last_error = exc
                if attempt >= _MAX_ATTEMPTS - 1:
                    break
                delay = _backoff_with_jitter(attempt)
                logger.warning(
                    "openrouter.complete retrying attempt=%d/%d error=%r delay_s=%.2f ticket_id=%s",
                    attempt + 1,
                    _MAX_ATTEMPTS,
                    str(exc),
                    delay,
                    ticket_id,
                )
                await asyncio.sleep(delay)

        raise OpenRouterError(f"exhausted retries: {last_error}") from last_error

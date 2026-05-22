"""OpenRouter HTTP client. Reference: plan.md §7, tasks.md T012.

OpenAI-compatible `/chat/completions`. Returns the raw model output string;
parsing + resolution happen downstream (`app.ai.pipeline`).
"""

from __future__ import annotations

from typing import Any

import httpx

from app.observability import logged_call

OPENROUTER_BASE = "https://openrouter.ai/api/v1"


class OpenRouterError(Exception):
    """Raised on any OpenRouter upstream failure. Categorization degrades to fallback."""


class OpenRouterClient:
    def __init__(
        self,
        api_key: str,
        *,
        referer: str = "http://localhost:8000",
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
    ) -> str:
        """Call `/chat/completions` and return the assistant message content.

        Request shape per plan §7: `temperature=0.1`, `max_tokens=400`,
        `response_format={type:"json_object"}`.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
        }
        async with logged_call("openrouter.complete", ticket_id=ticket_id):
            resp = await self._http.post("/chat/completions", json=body)
        if resp.status_code != 200:
            raise OpenRouterError(f"POST /chat/completions → {resp.status_code}")

        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise OpenRouterError(f"unexpected response shape: {exc}") from exc
        if not isinstance(content, str):
            raise OpenRouterError("response content was not a string")
        return content

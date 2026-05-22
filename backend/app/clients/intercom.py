"""Intercom HTTP client. Reference: plan.md §6, tasks.md T008–T011.

Owns: workspace-id resolution (deep links, FR-010), time-bounded conversation
search (FR-001/FR-002), parallel hydration with isolated per-ticket failures
(FR-003/NFR-003), and HTML stripping before AI input.
"""

from __future__ import annotations

import asyncio
import html
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from app.observability import logged_call
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema

INTERCOM_BASE = "https://api.intercom.io"
INTERCOM_VERSION = "2.11"
_SEARCH_PAGE_SIZE = 50

_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_P_CLOSE_RE = re.compile(r"</p\s*>", re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


class IntercomError(Exception):
    """Raised on any Intercom upstream failure (maps to HTTP 502 at the route)."""


def strip_html(raw: str | None) -> str:
    """`<br>`/`</p>` → newline, drop remaining tags, unescape entities."""
    if not raw:
        return ""
    text = _BR_RE.sub("\n", raw)
    text = _P_CLOSE_RE.sub("\n", text)
    text = _TAG_RE.sub("", text)
    return html.unescape(text).strip()


def _unix_to_dt(ts: Any) -> datetime:
    """Intercom timestamps are unix seconds. Store naive UTC for consistent compares."""
    return datetime.fromtimestamp(int(ts), tz=UTC).replace(tzinfo=None)


def _author(raw: dict[str, Any] | None) -> TicketAuthorSchema:
    raw = raw or {}
    raw_id = raw.get("id")
    return TicketAuthorSchema(
        id=str(raw_id) if raw_id is not None else None,
        name=raw.get("name"),
        email=raw.get("email"),
        type=raw.get("type"),
    )


class IntercomClient:
    """Thin async wrapper. Construct with a token; close with `aclose()`."""

    def __init__(self, token: str, *, http: httpx.AsyncClient | None = None) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=INTERCOM_BASE,
            headers={
                "Authorization": f"Bearer {token}",
                "Intercom-Version": INTERCOM_VERSION,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(30.0),
        )
        self.workspace_id: str | None = None

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ── T008 — workspace id ───────────────────────────────────────────────────

    async def resolve_workspace_id(self) -> str:
        """`GET /me` once at startup; cache `app.id_code` for deep-link composition."""
        async with logged_call("intercom.me"):
            resp = await self._http.get("/me")
        if resp.status_code != 200:
            raise IntercomError(f"GET /me → {resp.status_code}")
        app = resp.json().get("app") or {}
        workspace_id = app.get("id_code")
        if not workspace_id:
            raise IntercomError("GET /me returned no app.id_code")
        self.workspace_id = str(workspace_id)
        return self.workspace_id

    # ── T011 — deep link ──────────────────────────────────────────────────────

    def deep_link(self, conversation_id: str) -> str | None:
        if not self.workspace_id:
            return None
        return (
            f"https://app.intercom.com/a/apps/{self.workspace_id}/conversations/{conversation_id}"
        )

    # ── T009 — search ─────────────────────────────────────────────────────────

    async def search_conversation_ids(
        self,
        *,
        threshold_unix: int,
        states: list[str],
        max_tickets: int,
    ) -> list[str]:
        """`POST /conversations/search` — `updated_at > threshold` AND state filter.

        Paginates via `starting_after` until the chain ends or `max_tickets` is hit.
        """
        clauses: list[dict[str, Any]] = [
            {"field": "updated_at", "operator": ">", "value": threshold_unix},
        ]
        if states:
            clauses.append({"field": "state", "operator": "IN", "value": states})

        query: dict[str, Any] = (
            clauses[0] if len(clauses) == 1 else {"operator": "AND", "value": clauses}
        )

        ids: list[str] = []
        starting_after: str | None = None
        while len(ids) < max_tickets:
            pagination: dict[str, Any] = {"per_page": _SEARCH_PAGE_SIZE}
            if starting_after:
                pagination["starting_after"] = starting_after
            body = {"query": query, "pagination": pagination}

            async with logged_call("intercom.search"):
                resp = await self._http.post("/conversations/search", json=body)
            if resp.status_code != 200:
                raise IntercomError(f"POST /conversations/search → {resp.status_code}")

            data = resp.json()
            for conv in data.get("conversations", []):
                cid = conv.get("id")
                if cid is not None:
                    ids.append(str(cid))

            nxt = (data.get("pages") or {}).get("next")
            starting_after = nxt.get("starting_after") if isinstance(nxt, dict) else None
            if not starting_after:
                break

        return ids[:max_tickets]

    # ── T010 — hydration + HTML stripping ─────────────────────────────────────

    async def hydrate_one(self, conversation_id: str) -> HydratedTicket:
        """`GET /conversations/{id}?display_as=plaintext` → a fully parsed ticket."""
        async with logged_call("intercom.hydrate", ticket_id=conversation_id):
            resp = await self._http.get(
                f"/conversations/{conversation_id}",
                params={"display_as": "plaintext"},
            )
        if resp.status_code != 200:
            raise IntercomError(
                f"GET /conversations/{conversation_id} → {resp.status_code}",
            )
        return self._parse_conversation(resp.json())

    async def hydrate_many(self, conversation_ids: list[str]) -> list[HydratedTicket]:
        """Hydrate in parallel. One failure does not fail the batch (NFR-003)."""
        results = await asyncio.gather(
            *(self.hydrate_one(cid) for cid in conversation_ids),
            return_exceptions=True,
        )
        return [t for t in results if isinstance(t, HydratedTicket)]

    def _parse_conversation(self, conv: dict[str, Any]) -> HydratedTicket:
        cid = str(conv["id"])
        created = _unix_to_dt(conv.get("created_at", 0))
        updated = _unix_to_dt(conv.get("updated_at", conv.get("created_at", 0)))

        source = conv.get("source") or {}
        ticket_author = _author(source.get("author"))

        parts: list[ConversationPartSchema] = []
        source_body = strip_html(source.get("body"))
        if source_body:
            parts.append(
                ConversationPartSchema(
                    author=ticket_author,
                    body=source_body,
                    created_at=created,
                ),
            )

        nested = (conv.get("conversation_parts") or {}).get("conversation_parts", [])
        for part in nested:
            body = strip_html(part.get("body"))
            if not body:
                continue
            parts.append(
                ConversationPartSchema(
                    author=_author(part.get("author")),
                    body=body,
                    created_at=_unix_to_dt(part.get("created_at", conv.get("updated_at", 0))),
                ),
            )

        return HydratedTicket(
            id=cid,
            title=conv.get("title"),
            state=conv.get("state"),
            priority=conv.get("priority"),
            created_at=created,
            updated_at=updated,
            author=ticket_author,
            url=self.deep_link(cid),
            parts=parts,
        )

"""Shared test builders."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.clients.openrouter import OpenRouterError
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema

_DEFAULT_DT = datetime(2026, 1, 1, 12, 0, 0)


def make_hydrated(
    ticket_id: str,
    *,
    title: str = "Sample ticket",
    updated: datetime | None = None,
    body: str = "hello there",
) -> HydratedTicket:
    dt = updated or _DEFAULT_DT
    author = TicketAuthorSchema(id="u1", name="Customer", email=None, type="user")
    return HydratedTicket(
        id=ticket_id,
        title=title,
        state="open",
        priority=None,
        created_at=dt,
        updated_at=dt,
        author=author,
        url=None,
        parts=[ConversationPartSchema(author=author, body=body, created_at=dt)],
    )


def intercom_conv(
    conv_id: str,
    *,
    updated: int = 2000,
    created: int = 1000,
    title: str = "Sample",
    body: str = "<p>hi</p>",
) -> dict[str, Any]:
    """A minimal Intercom conversation payload for hydration mocks."""
    return {
        "id": conv_id,
        "created_at": created,
        "updated_at": updated,
        "state": "open",
        "priority": None,
        "title": title,
        "source": {
            "author": {"type": "user", "name": "Customer", "id": "u1"},
            "body": body,
        },
        "conversation_parts": {"conversation_parts": []},
    }


def existing_assignment(category_id: int) -> str:
    return (
        f'{{"assignment":"existing","category_id":{category_id},'
        f'"summary":"a summary","confidence":0.82}}'
    )


def new_proposal_assignment(name: str) -> str:
    return (
        f'{{"assignment":"new_proposal","proposed_name":"{name}",'
        f'"proposed_description":"things like {name}",'
        f'"summary":"a summary","confidence":0.6}}'
    )


class FakeOpenRouter:
    """Stand-in for OpenRouterClient — returns canned per-ticket responses."""

    def __init__(self, by_ticket: dict[str, str]) -> None:
        self.by_ticket = by_ticket
        self.calls = 0

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        ticket_id: str | None = None,
    ) -> str:
        self.calls += 1
        if ticket_id is None or ticket_id not in self.by_ticket:
            raise OpenRouterError("no canned response")
        return self.by_ticket[ticket_id]

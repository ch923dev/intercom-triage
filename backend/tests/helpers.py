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


def existing_assignment(category_id: int, *, confidence: float = 0.82) -> str:
    return (
        f'{{"assignment":"existing","category_id":{category_id},'
        f'"summary":"a summary","confidence":{confidence}}}'
    )


def new_proposal_assignment(name: str) -> str:
    return (
        f'{{"assignment":"new_proposal","proposed_name":"{name}",'
        f'"proposed_description":"things like {name}",'
        f'"summary":"a summary","confidence":0.6}}'
    )


class FakeIntercom:
    """Stand-in for IntercomClient — serves canned search summaries + details +
    contacts and records which conversations were detail-fetched (so a test can
    assert skip-known avoided a fetch)."""

    def __init__(
        self,
        *,
        summaries: list[dict[str, Any]] | None = None,
        details: dict[str, dict[str, Any]] | None = None,
        contacts: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._summaries = summaries or []
        self._details = details or {}
        self._contacts = contacts or {}
        self.detail_calls: list[str] = []

    async def search_conversations(
        self, *, states: Any, updated_after: int | None = None, per_page: int = 150
    ) -> Any:
        for summary in self._summaries:
            yield summary

    async def get_conversation(self, conversation_id: str) -> dict[str, Any]:
        self.detail_calls.append(conversation_id)
        return self._details[conversation_id]

    async def get_contact(self, contact_id: str) -> dict[str, Any] | None:
        return self._contacts.get(contact_id)


class FakeOpenRouter:
    """Stand-in for OpenRouterClient — returns canned per-ticket responses."""

    def __init__(self, by_ticket: dict[str, str]) -> None:
        self.by_ticket = by_ticket
        self.calls = 0
        self.last_response_format: dict[str, Any] | None = None

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        ticket_id: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls += 1
        self.last_response_format = response_format
        if ticket_id is None or ticket_id not in self.by_ticket:
            raise OpenRouterError("no canned response")
        return self.by_ticket[ticket_id]


class FakeCascadeOpenRouter:
    """Stand-in for OpenRouterClient that routes on (model, ticket_id).

    Roadmap 2.2 cascade tests: lets a single ticket return one canned answer
    from the cheap model and a different one from the strong model, and records
    how many times each model was called so the test can assert routing +
    escalation accounting. A missing (model, ticket_id) entry raises
    OpenRouterError, exercising the failed-cheap-call → escalate path.
    """

    def __init__(self, by_model_ticket: dict[tuple[str, str], str]) -> None:
        self.by_model_ticket = by_model_ticket
        self.calls_by_model: dict[str, int] = {}

    async def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        ticket_id: str | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> str:
        self.calls_by_model[model] = self.calls_by_model.get(model, 0) + 1
        if ticket_id is None or (model, ticket_id) not in self.by_model_ticket:
            raise OpenRouterError("no canned response")
        return self.by_model_ticket[(model, ticket_id)]

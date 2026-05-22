"""Pydantic request/response schemas for the API.

Reference: plan.md §3 (data contracts), §4 (API contract).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TicketState = Literal["open", "snoozed", "closed"]
LookbackUnit = Literal["hours", "days"]
CategorySource = Literal["seed", "ai_proposed", "user_created"]
ProposalStatus = Literal["pending", "approved", "merged", "rejected"]


# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    model: str
    intercom_configured: bool
    openrouter_configured: bool
    workspace_id: str | None = None
    missing_secrets: list[str]


# ── Category ──────────────────────────────────────────────────────────────────


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    color: str | None
    sort_order: int
    is_active: bool
    is_fallback: bool
    source: CategorySource
    created_at: datetime
    archived_at: datetime | None


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=600)
    color: str | None = None
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, min_length=1, max_length=600)
    color: str | None = None
    sort_order: int | None = None


class CategoryProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    example_ticket_ids: list[str] = Field(default_factory=list)
    status: ProposalStatus
    resolved_category_id: int | None
    created_at: datetime
    resolved_at: datetime | None


class CategoriesResponse(BaseModel):
    categories: list[CategoryRead]
    pending_proposals: list[CategoryProposalRead]


class ProposalsResponse(BaseModel):
    proposals: list[CategoryProposalRead]


class ProposalApprove(BaseModel):
    color: str | None = None
    sort_order: int | None = None


class OkResponse(BaseModel):
    ok: Literal[True] = True


class MergeResponse(BaseModel):
    ok: Literal[True] = True
    moved_count: int


# ── Tickets ───────────────────────────────────────────────────────────────────


class TicketAuthorSchema(BaseModel):
    id: str | None = None
    name: str | None = None
    email: str | None = None
    type: str | None = None


class ConversationPartSchema(BaseModel):
    author: TicketAuthorSchema
    body: str
    created_at: datetime


class HydratedTicket(BaseModel):
    """A conversation fetched + hydrated from Intercom, before AI categorization."""

    id: str
    title: str | None
    state: TicketState | None
    priority: str | None
    created_at: datetime
    updated_at: datetime
    author: TicketAuthorSchema
    url: str | None
    parts: list[ConversationPartSchema]


class TicketSchema(HydratedTicket):
    """A ticket returned to a client — hydrated + categorized (plan §3)."""

    category_id: int | None
    proposal_id: int | None
    summary: str
    ai_confidence: float
    user_override: bool


class CategoryUpdate(BaseModel):
    """PATCH /tickets/{id}/category body."""

    category_id: int


class OverrideResponse(BaseModel):
    ok: Literal[True] = True
    category_id: int


# ── Filter + settings ─────────────────────────────────────────────────────────


def _default_states() -> list[TicketState]:
    return ["open"]


class FilterSettings(BaseModel):
    lookback_unit: LookbackUnit = "hours"
    lookback_value: int = Field(default=24, ge=1, le=720)
    states: list[TicketState] = Field(default_factory=_default_states)
    include_category_ids: list[int] | None = None

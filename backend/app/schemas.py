"""Pydantic response/request schemas for the API.

Reference: plan.md §3 (data contracts), §4 (API contract).

Only the Phase 1 shapes are defined here. Later phases append `Ticket`,
`TicketAuthor`, `ConversationPart`, `FilterSettings`, `CategoryUpdate`, etc.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    model: str
    intercom_configured: bool
    openrouter_configured: bool
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
    source: Literal["seed", "ai_proposed", "user_created"]
    created_at: datetime
    archived_at: datetime | None


class CategoryProposalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    example_ticket_ids: list[str] = Field(default_factory=list)
    status: Literal["pending", "approved", "merged", "rejected"]
    resolved_category_id: int | None
    created_at: datetime
    resolved_at: datetime | None


class CategoriesResponse(BaseModel):
    """`GET /categories` — active categories + pending proposals in display order."""

    categories: list[CategoryRead]
    pending_proposals: list[CategoryProposalRead]

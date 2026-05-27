"""Pydantic request/response schemas for the API.

Reference: plan.md §3 (data contracts), §4 (API contract).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer

from app.config import MAX_BULK_IDS


def _naive_utc(value: datetime) -> datetime:
    """Coerce a datetime to naive UTC — the schema used by every DB column.

    Extension-supplied conversations may carry tz-aware ISO timestamps; the
    legacy Intercom path produces naive ones. Normalize both to naive UTC.
    """
    if value.tzinfo is not None:
        return value.astimezone(UTC).replace(tzinfo=None)
    return value


def _isoformat_utc(value: datetime) -> str:
    """Serialize a datetime as a `Z`-suffixed UTC ISO string.

    DB columns store *naive* UTC. A naive datetime emitted with no tz marker is
    parsed by JS `Date`/`Date.parse` as the operator's *local* time, shifting
    every timestamp by their UTC offset — which fires snoozed follow-ups
    immediately for anyone east of UTC. Stamping the marker keeps the client's
    `Date` parse anchored to true UTC.
    """
    aware = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return aware.isoformat().replace("+00:00", "Z")


# Emits a `Z`-suffixed UTC ISO string on output. Use for every datetime that
# leaves the API in a response model.
UTCDatetime = Annotated[datetime, PlainSerializer(_isoformat_utc, return_type=str)]

# A datetime field that always stores naive UTC, whatever tz the input carried,
# and serializes back out as `Z`-suffixed UTC.
NaiveUTCDatetime = Annotated[
    datetime,
    AfterValidator(_naive_utc),
    PlainSerializer(_isoformat_utc, return_type=str),
]

TicketState = Literal["open", "snoozed", "closed"]
LookbackUnit = Literal["hours", "days"]
CategorySource = Literal["seed", "ai_proposed", "user_created"]
ProposalStatus = Literal["pending", "approved", "merged", "rejected"]
ResolvedSource = Literal["manual", "intercom_closed", "non_actionable", "ai_resolved"]
ResolutionVerdict = Literal["resolved", "non_actionable", "not_resolved"]
ResolutionChipState = Literal["ai_resolved", "ai_reopened", "new_reply"]
# Roadmap 0.2 — triage facets emitted by the categorization call.
AIPriority = Literal["low", "normal", "high", "urgent"]
AISentiment = Literal["negative", "neutral", "positive"]


# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    model: str
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
    source: CategorySource
    created_at: UTCDatetime
    archived_at: UTCDatetime | None


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
    created_at: UTCDatetime
    resolved_at: UTCDatetime | None


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


# ── Follow-ups + notes ────────────────────────────────────────────────────────


class FollowupRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str
    due_at: UTCDatetime
    reason: str | None
    fired: bool
    created_at: UTCDatetime
    updated_at: UTCDatetime


class FollowupSet(BaseModel):
    """PUT /followups/{ticket_id} body. `due_at` is absolute — the client
    computes it from a preset offset so server and client clocks agree."""

    due_at: datetime
    reason: str | None = Field(default=None, max_length=80)


class SnoozeRequest(BaseModel):
    minutes: int = Field(ge=1, le=10_080)  # up to 7 days


class TicketNoteRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_id: str
    body: str
    updated_at: UTCDatetime


class TicketNoteSet(BaseModel):
    body: str  # empty / whitespace-only deletes the row


class NoteDeletedResponse(BaseModel):
    ok: Literal[True] = True
    deleted: Literal[True] = True


# ── Note entries (time-tabled notes) ─────────────────────────────────────────


class NoteEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: str
    body: str
    timer_min: int | None
    reason: str | None
    created_at: UTCDatetime


class NoteEntryCreate(BaseModel):
    """POST /notes/entries body. `body` required, timer + reason optional.

    `timer_min` set → service upserts the ticket's `followups` row in the
    same transaction. `reason` mirrors to `followups.reason` when timer set.
    """

    ticket_id: str = Field(min_length=1)
    body: str = Field(min_length=1)
    timer_min: int | None = Field(default=None, ge=1, le=1440)
    reason: str | None = Field(default=None, max_length=80)


class NoteEntryDeleted(BaseModel):
    ok: Literal[True] = True
    deleted: Literal[True] = True
    id: int


# ── Note attachments ─────────────────────────────────────────────────────────


class NoteAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_kind: Literal["entry", "ticket"]
    owner_id: str
    ticket_id: str
    filename: str
    mime: str
    size_bytes: int
    created_at: UTCDatetime
    raw_url: str
    thumb_url: str | None


class NoteAttachmentDeleted(BaseModel):
    ok: Literal[True] = True
    deleted: Literal[True] = True
    id: int


# ── Playbooks ─────────────────────────────────────────────────────────────────


class PlaybookRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    category_id: int
    label: str
    body: str
    source_ticket_id: str | None
    created_at: UTCDatetime
    updated_at: UTCDatetime
    archived_at: UTCDatetime | None


class PlaybookCreate(BaseModel):
    category_id: int
    label: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)
    source_ticket_id: str | None = None


class PlaybookUpdate(BaseModel):
    """PATCH body. Omit a field to leave it unchanged."""

    label: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=4000)


class PlaybookDraftRequest(BaseModel):
    ticket_id: str = Field(min_length=1)


class PlaybookDraftResponse(BaseModel):
    body: str


# ── Tickets ───────────────────────────────────────────────────────────────────


class TicketAuthorSchema(BaseModel):
    id: str | None = None
    name: str | None = None
    email: str | None = None
    type: str | None = None
    # Intercom "User data" panel fields (customer author only; admin/part
    # authors leave these null). Stored in the ticket's `author` JSON blob.
    location: str | None = None
    timezone: str | None = None
    phone: str | None = None
    company: str | None = None


class ConversationPartSchema(BaseModel):
    author: TicketAuthorSchema
    body: str
    created_at: NaiveUTCDatetime
    # True for admin replies visible to the customer (Intercom
    # `renderable_type` 2 or 24). Inbound customer messages → False.
    is_admin: bool = False


class HydratedTicket(BaseModel):
    """A conversation fetched + hydrated from Intercom, before AI categorization.

    `parts` is what the AI sees: the customer-visible thread (inbound messages
    + admin replies). `internal_notes` is the team-only side-channel (Intercom
    `renderable_type` 3 — distinct from the operator's local `TicketNote` jot)
    and is NOT fed to the AI prompt; only the UI surfaces it.
    """

    id: str
    title: str | None
    state: TicketState | None
    priority: str | None
    created_at: NaiveUTCDatetime
    updated_at: NaiveUTCDatetime
    author: TicketAuthorSchema
    url: str | None
    parts: list[ConversationPartSchema]
    internal_notes: list[ConversationPartSchema] = Field(default_factory=list)


class TicketSchema(HydratedTicket):
    """A ticket returned to a client — hydrated + categorized (plan §3).

    Inherits `parts` + `internal_notes` from `HydratedTicket`. `note` is the
    operator's local next-step jot (FR-023), independent of any Intercom team
    notes carried in `internal_notes`.

    `title_user_edited` / `summary_user_edited` flag fields edited via
    `PATCH /tickets/{id}`; the UI shows a small indicator next to the edited
    field, and re-syncs from Intercom preserve the operator's value.
    """

    category_id: int | None
    proposal_id: int | None
    summary: str
    ai_confidence: float
    user_override: bool
    title_user_edited: bool = False
    summary_user_edited: bool = False
    followup: FollowupRead | None = None
    note: TicketNoteRead | None = None
    resolved_at: UTCDatetime | None = None
    resolved_source: ResolvedSource | None = None
    ai_resolve_enabled: bool = False  # effective value after merging with settings default
    ai_resolve_override: bool | None = None  # raw per-ticket override (None = inherit)
    ai_resolution_verdict: ResolutionVerdict | None = None
    ai_resolution_confidence: float | None = None
    ai_resolution_reason: str | None = None
    resolution_chip_state: ResolutionChipState | None = None
    # Roadmap 0.2 — triage facets surfaced on the board. `ai_priority` /
    # `ai_sentiment` are null on pre-0.2 rows; `ai_labels` defaults to [].
    ai_priority: AIPriority | None = None
    ai_sentiment: AISentiment | None = None
    ai_labels: list[str] = Field(default_factory=list)


class CategoryUpdate(BaseModel):
    """PATCH /tickets/{id}/category body."""

    category_id: int


class AIResolveSet(BaseModel):
    """PATCH /tickets/{id}/ai-resolve body. `null` clears the per-ticket
    override and lets the ticket inherit settings.ai_resolve_default."""

    enabled: bool | None = None


class ResolveResponse(BaseModel):
    ok: Literal[True] = True
    resolved_at: UTCDatetime
    resolved_source: ResolvedSource


class ReopenResponse(BaseModel):
    ok: Literal[True] = True


class TicketEdit(BaseModel):
    """PATCH /tickets/{id} body — operator edits the AI/Intercom-supplied
    headline + description. Omit a field to leave it unchanged. Empty string
    on either clears the operator override (next sync restores AI values)."""

    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=600)


class OverrideResponse(BaseModel):
    ok: Literal[True] = True
    category_id: int


class IngestResponse(BaseModel):
    """`POST /tickets/ingest` result — counts for the extension's sync UI."""

    received: int
    categorized: int  # how many needed a fresh AI call (the rest were cache hits)


# ── Filter + settings ─────────────────────────────────────────────────────────


def _default_states() -> list[TicketState]:
    return ["open"]


class FilterSettings(BaseModel):
    lookback_unit: LookbackUnit = "hours"
    lookback_value: int = Field(default=24, ge=1, le=720)
    states: list[TicketState] = Field(default_factory=_default_states)
    include_category_ids: list[int] | None = None
    mute_alarms: bool = False
    # When False, ingest skips AI categorization — tickets land in the fallback
    # category and the operator writes subject/summary by hand.
    use_ai: bool = True
    ai_resolve_default: bool = False
    ai_resolve_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
    # When True (default), the Board hides category columns with zero open
    # tickets. Resolved column always shows regardless.
    hide_empty_categories: bool = True


# ── Metrics ───────────────────────────────────────────────────────────────────


class MetricsResponse(BaseModel):
    """Process-lifetime counters (plan §11). Keys with a `.` carry a label,
    e.g. `ai_calls_total.ok`, `proposals_resolved_total.rejected`."""

    counters: dict[str, int]


# ── Bulk actions ──────────────────────────────────────────────────────────────
#
# Plan §8d. Each bulk endpoint accepts an envelope of ticket ids and returns a
# per-id result. Cap (`MAX_BULK_IDS`) lives in `config.py`.


class BulkTicketIds(BaseModel):
    """Universal bulk request body — ids of tickets to operate on."""

    ticket_ids: list[str] = Field(min_length=1, max_length=MAX_BULK_IDS)


class BulkCategoryUpdate(BulkTicketIds):
    """`PATCH /tickets/bulk/category` body — assigns one category to N tickets."""

    category_id: int


class BulkFollowupSet(BulkTicketIds):
    """`PUT /followups/bulk` body — applies one `due_at` + reason to N tickets."""

    due_at: datetime
    reason: str | None = Field(default=None, max_length=80)


class BulkFailure(BaseModel):
    """One per-id failure in a bulk response. `reason` is human-readable."""

    id: str
    reason: str


class BulkResult(BaseModel):
    """Universal bulk response. A bulk request returns 200 with mixed
    `ok_ids` / `failed[]` even when every per-id call failed — the response
    code reflects request validity, not per-id outcomes."""

    ok_ids: list[str] = Field(default_factory=list)
    failed: list[BulkFailure] = Field(default_factory=list)

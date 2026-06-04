"""Pydantic request/response schemas for the API.

Reference: plan.md §3 (data contracts), §4 (API contract).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.config import MAX_BULK_IDS
from app.util import naive_utcnow


def _naive_utc(value: datetime) -> datetime:
    """Coerce a datetime to naive UTC — the schema used by every DB column.

    Incoming conversations may carry tz-aware ISO timestamps; the
    Intercom API path produces naive ones. Normalize both to naive UTC.
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


def _require_future_until(until_at: datetime) -> None:
    # `until_at` is already coerced to naive UTC by NaiveUTCDatetime.
    if until_at <= naive_utcnow():
        raise ValueError("until_at must be in the future")


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
ParkedReason = Literal["waiting_on_customer", "waiting_on_third_party", "waiting_internal", "other"]
ResolutionVerdict = Literal["resolved", "non_actionable", "not_resolved"]
ResolutionChipState = Literal["ai_resolved", "ai_reopened", "new_reply"]
NonActionableKind = Literal["auto_reply", "thanks", "spam", "out_of_office", "other"]
# Roadmap 0.2 — triage facets emitted by the categorization call.
AIPriority = Literal["low", "normal", "high", "urgent"]
AISentiment = Literal["negative", "neutral", "positive"]


# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    version: str
    model: str
    openrouter_configured: bool
    # Whether a workspace Access Token is set so the backend can poll Intercom
    # (cross-package invariant #1). False → no poller, `/tickets/sync` → 503.
    intercom_configured: bool
    missing_secrets: list[str]
    # Roadmap 2.3 — the AppConfig needs-review threshold, surfaced so the webapp
    # can read the calibrated default instead of hardcoding it blind. An open,
    # non-overridden ticket with ai_confidence < this surfaces in the review lane.
    review_confidence_threshold: float
    # Whether the local semantic layer is operational. The embedding model +
    # sqlite-vec load best-effort and otherwise fail silently; surfacing this
    # tells the operator when few-shot / RAG / clustering are quietly off.
    embeddings_available: bool
    clustering_available: bool


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

    due_at: NaiveUTCDatetime
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


class SuggestedPlaybook(BaseModel):
    """A semantically-ranked playbook suggestion for a ticket (roadmap 3.3).

    `score` is the cosine similarity in [-1, 1] between the ticket's
    customer-visible text and the playbook's (label + body); higher is closer.
    Ephemeral — computed on ticket open, never persisted as ticket state."""

    model_config = ConfigDict(from_attributes=True)

    playbook: PlaybookRead
    score: float


# ── RAG draft reply (roadmap 2.6) ─────────────────────────────────────────────
# Kept in its own region (separate from the Tickets block below) so it does not
# collide with concurrent edits to the HydratedTicket / TicketSchema shapes.


class DraftReplyResponse(BaseModel):
    """An ephemeral RAG-grounded draft reply to send to the customer.

    `grounding_ticket_ids` / `playbook_ids` expose what the draft was grounded in
    for operator transparency. Only customer-visible content reaches `body`
    (invariant #4 — internal notes never leak into a draft)."""

    body: str
    grounding_ticket_ids: list[str] = Field(default_factory=list)
    playbook_ids: list[int] = Field(default_factory=list)


# ── Snippets (roadmap 1.5) ────────────────────────────────────────────────────
# Short canned replies with `{{variable}}` placeholders. Lighter than playbooks:
# global (not category-scoped), no AI draft. Variable substitution is performed
# client-side from the ticket the operator is viewing — the body is stored
# verbatim with placeholders intact. Durable operator knowledge (invariant #13).


class SnippetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    body: str
    created_at: UTCDatetime
    updated_at: UTCDatetime
    archived_at: UTCDatetime | None


class SnippetCreate(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field(min_length=1, max_length=4000)


class SnippetUpdate(BaseModel):
    """PATCH body. Omit a field to leave it unchanged."""

    title: str | None = Field(default=None, min_length=1, max_length=120)
    body: str | None = Field(default=None, min_length=1, max_length=4000)


# ── Recurring-issue clusters (roadmap 3.1) ────────────────────────────────────


class ClusterRead(BaseModel):
    """One recurring-issue cluster from the offline clustering job.

    Read-only — clusters are recomputed periodically by the background job, not
    mutated through the API. `top_terms` / `label` are c-TF-IDF over the
    customer-visible `parts[]` + title only (invariant #4).
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    top_terms: list[str]
    size: int
    ticket_ids: list[str]
    computed_at: UTCDatetime


class ClusterGapRead(BaseModel):
    """A recurring-issue cluster whose dominant effective category has no
    playbook yet — roadmap 3.2 ("what should I build a playbook for").

    Read-only ranking surface. `size` is the cluster's full size (the primary
    rank key — most-recurring first); `member_count` is how many of its tickets
    resolved to `category_id` (the support behind the suggestion). The operator
    acts on `category_id` by writing a playbook for that category.
    """

    model_config = ConfigDict(from_attributes=True)

    cluster_id: int
    label: str
    top_terms: list[str]
    size: int
    category_id: int
    category_name: str
    member_count: int


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
    # True for admin/bot replies visible to the customer (Intercom `part_type`
    # `comment` with an admin/bot/team author). Inbound customer messages → False.
    is_admin: bool = False


class HydratedTicket(BaseModel):
    """A conversation fetched + hydrated from Intercom, before AI categorization.

    `parts` is what the AI sees: the customer-visible thread (inbound messages
    + admin replies). `internal_notes` is the team-only side-channel (Intercom
    `part_type` `note` — distinct from the operator's local `TicketNote` jot)
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
    non_actionable_kind: NonActionableKind | None = None
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
    # Roadmap 4.1 (T106) — parked / snoozed state. Board-state, like resolved_*
    # (NOT on HydratedTicket). `ready` is derived client-side from parked_until.
    parked_at: UTCDatetime | None = None
    parked_until: UTCDatetime | None = None
    parked_reason: ParkedReason | None = None
    parked_note: str | None = None


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


class ParkRequest(BaseModel):
    """POST /tickets/{id}/park body. `until_at` is the wake time (must be future)."""

    until_at: NaiveUTCDatetime
    reason: ParkedReason
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_future(self) -> ParkRequest:
        _require_future_until(self.until_at)
        return self


class ParkResponse(BaseModel):
    ok: Literal[True] = True
    parked_at: UTCDatetime
    parked_until: UTCDatetime
    parked_reason: ParkedReason
    parked_note: str | None = None


class UnparkResponse(BaseModel):
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
    """`POST /tickets/ingest` result — received + categorized counts."""

    received: int
    categorized: int  # how many needed a fresh AI call (the rest were cache hits)


class SyncResponse(BaseModel):
    """`POST /tickets/sync` result — counts for one backend-driven poll cycle.

    Superset of `IngestResponse`: `received` / `categorized` come straight from
    the ingest the cycle performed; `skipped_known` is how many conversations
    were skipped without a detail fetch (unchanged since last sync), and
    `closed_detected` is how many tracked-open tickets were stamped
    `intercom_closed` this cycle (the closure pass)."""

    received: int
    categorized: int
    skipped_known: int
    closed_detected: int


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


class LatencyHistogram(BaseModel):
    """Per-key latency distribution (milliseconds) over the retained sample
    window. Fed by `observability.logged_call` for external HTTP calls."""

    count: int
    p50: float
    p95: float
    max: float


class UsageBucket(BaseModel):
    """OpenRouter token usage + estimated USD cost for one (day, model) bucket
    (roadmap 1.4). In-process only — resets when the backend restarts."""

    date: str  # UTC calendar day, ISO `YYYY-MM-DD`.
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    estimated_cost_usd: float


class MetricsResponse(BaseModel):
    """Process-lifetime counters + latency histograms (plan §11). Counter keys
    with a `.` carry a label, e.g. `ai_calls_total.ok`,
    `proposals_resolved_total.rejected`. Histogram keys are namespaced per op,
    e.g. `latency_ms.openrouter.complete`.

    `usage` carries per-day OpenRouter token spend (roadmap 1.4), newest day
    first; `today_cost_usd` is the summed estimate for the current UTC day."""

    counters: dict[str, int]
    histograms: dict[str, LatencyHistogram] = Field(default_factory=dict)
    usage: list[UsageBucket] = Field(default_factory=list)
    today_cost_usd: float = 0.0


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

    due_at: NaiveUTCDatetime
    reason: str | None = Field(default=None, max_length=80)


class BulkParkRequest(BulkTicketIds):
    """POST /tickets/bulk/park body — one wake time + reason applied to N tickets."""

    until_at: NaiveUTCDatetime
    reason: ParkedReason
    note: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _check_future(self) -> BulkParkRequest:
        _require_future_until(self.until_at)
        return self


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


# ── Stats dashboard (roadmap 1.3) ─────────────────────────────────────────────
#
# Read-only rollups over the existing `tickets` table — no migration, no new
# columns. Four success metrics (spec §8) aggregated server-side and rendered
# as a dependency-free dashboard. Resolution mix ties to `resolved_source`
# (cross-package invariant #10: manual | intercom_closed | non_actionable |
# ai_resolved, null = open).


class CategoryCount(BaseModel):
    """Ticket count for one category. `category_id` is null for tickets with no
    effective category (rare — fallback usually catches these)."""

    category_id: int | None
    category_name: str
    count: int


class VolumePoint(BaseModel):
    """Tickets created on one UTC calendar day. `date` is ISO `YYYY-MM-DD`.
    Days with zero tickets in the window are emitted with `count: 0` so the
    client can draw a continuous trend without gap-filling."""

    date: str
    count: int


class ResolutionMix(BaseModel):
    """Resolution-source breakdown over the window. Keyed by `resolved_source`
    plus an `open` bucket for tickets with no `resolved_at`."""

    open: int = 0
    manual: int = 0
    intercom_closed: int = 0
    non_actionable: int = 0
    ai_resolved: int = 0


class ResolveTimeBucket(BaseModel):
    """One bucket of the time-to-resolve histogram. `count` resolved tickets
    fell in `[lower_hours, upper_hours)`; `upper_hours` is null for the final
    open-ended bucket."""

    label: str
    lower_hours: float
    upper_hours: float | None
    count: int


class StatsResponse(BaseModel):
    """The four success metrics (spec §8), computed server-side.

    `window_days` is the trailing window (by ticket `created_at`) the volume
    trend + resolution mix + resolve-time distribution are computed over.
    `category_breakdown` and `total_tickets` count every ticket in the window.
    """

    window_days: int
    total_tickets: int
    category_breakdown: list[CategoryCount]
    volume_trend: list[VolumePoint]
    resolution_mix: ResolutionMix
    resolve_time_buckets: list[ResolveTimeBucket]
    median_resolve_hours: float | None

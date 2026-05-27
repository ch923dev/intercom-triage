// Server-side data contracts. Mirror of plan.md §3.

export type CategorySource = 'seed' | 'ai_proposed' | 'user_created';

export interface Category {
  id: number;
  name: string;
  description: string;
  color: string | null; // oklch(...) string per plan §8b
  sort_order: number;
  is_active: boolean;
  is_fallback: boolean;
  source: CategorySource;
  created_at: string;
  archived_at: string | null;
}

export type ProposalStatus = 'pending' | 'approved' | 'merged' | 'rejected';

export type ResolvedSource = 'manual' | 'intercom_closed' | 'non_actionable' | 'ai_resolved';
export type ResolutionVerdict = 'resolved' | 'not_resolved' | 'non_actionable';
export type ResolutionChipState = 'ai_resolved' | 'ai_reopened' | 'new_reply';
// Roadmap 0.2 — triage facets from the categorization call.
export type AIPriority = 'low' | 'normal' | 'high' | 'urgent';
export type AISentiment = 'negative' | 'neutral' | 'positive';

export interface CategoryProposal {
  id: number;
  name: string;
  description: string;
  example_ticket_ids: string[];
  status: ProposalStatus;
  resolved_category_id: number | null;
  created_at: string;
  resolved_at: string | null;
}

export interface CategoriesResponse {
  categories: Category[];
  pending_proposals: CategoryProposal[];
}

export interface ProposalsResponse {
  proposals: CategoryProposal[];
}

// ── Tickets ──────────────────────────────────────────────────────────────────

export type TicketState = 'open' | 'snoozed' | 'closed';

export interface TicketAuthor {
  id: string | null;
  name: string | null;
  email: string | null;
  type: string | null;
  /** Intercom "User data" panel fields. Populated for the ticket's customer
   *  author; null on admin/part authors. */
  location: string | null;
  timezone: string | null;
  phone: string | null;
  company: string | null;
}

export interface ConversationPart {
  author: TicketAuthor;
  body: string;
  created_at: string;
  /** True for an admin reply visible to the customer (Intercom renderable_type
   *  24). Inbound customer messages → false. Internal team notes live in
   *  `Ticket.internal_notes`, not here. */
  is_admin: boolean;
}

export interface Followup {
  ticket_id: string;
  due_at: string;
  reason: string | null;
  fired: boolean;
  created_at: string;
  updated_at: string;
}

export interface TicketNote {
  ticket_id: string;
  body: string;
  updated_at: string;
}

export interface NoteEntry {
  id: number;
  ticket_id: string;
  body: string;
  timer_min: number | null;
  reason: string | null;
  created_at: string;
}

export interface Playbook {
  id: number;
  category_id: number;
  label: string;
  body: string;
  source_ticket_id: string | null;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

// Recurring-issue cluster content gap (roadmap 3.2). A cluster of resolved
// tickets describing the same recurring issue whose dominant EFFECTIVE category
// (override beats AI) has no active playbook yet — i.e. a playbook the operator
// should write next. `size` is the cluster size (ranking key, most-recurring
// first); `member_count` is how many of its tickets resolved to `category_id`.
export interface ClusterGap {
  cluster_id: number;
  label: string;
  top_terms: string[];
  size: number;
  category_id: number;
  category_name: string;
  member_count: number;
}

// A semantically-ranked playbook suggestion for a ticket (roadmap 3.3). `score`
// is the cosine similarity in [-1, 1] between the ticket's customer-visible text
// and the playbook's (label + body); higher is closer. Ephemeral — computed on
// ticket open, never persisted.
export interface SuggestedPlaybook {
  playbook: Playbook;
  score: number;
}

// Snippet (roadmap 1.5). A short canned reply with `{{variable}}` placeholders.
// Lighter than a Playbook: global (not category-scoped), no AI draft. The body
// is stored verbatim with placeholders intact; substitution is done client-side
// from the open ticket (see utils/snippets.ts).
export interface Snippet {
  id: number;
  title: string;
  body: string;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
}

// RAG draft reply (roadmap 2.6). An ephemeral, customer-visible draft reply
// grounded in similar resolved tickets + effective-category playbooks. The
// grounding ids are surfaced for operator transparency; no internal-note
// content is ever exposed (backend invariant #4).
export interface DraftReply {
  body: string;
  grounding_ticket_ids: string[];
  playbook_ids: number[];
}

export interface NoteAttachment {
  id: number;
  owner_kind: 'entry' | 'ticket';
  owner_id: string;
  ticket_id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  created_at: string;
  raw_url: string;
  thumb_url: string | null;
}

export interface Ticket {
  id: string;
  title: string | null;
  state: TicketState | null;
  priority: string | null;
  created_at: string;
  updated_at: string;
  author: TicketAuthor;
  url: string | null;
  parts: ConversationPart[];
  /** Intercom team notes — internal-only side channel, distinct from `note`
   *  (the operator's local next-step jot). Never fed to the AI prompt. */
  internal_notes: ConversationPart[];
  category_id: number | null;
  proposal_id: number | null;
  summary: string;
  ai_confidence: number;
  user_override: boolean;
  /** True when the operator has manually edited the title via PATCH
   *  `/tickets/{id}`. The edited value is preserved across re-syncs; clear it
   *  by PATCHing `title: ""` to revert to the AI/Intercom-derived title. */
  title_user_edited: boolean;
  /** Same semantics as `title_user_edited`, but for `summary`. */
  summary_user_edited: boolean;
  followup: Followup | null;
  note: TicketNote | null;
  resolved_at: string | null;
  resolved_source: ResolvedSource | null;
  /** Effective value — backend merges per-ticket override with settings default. */
  ai_resolve_enabled: boolean;
  /** Raw per-ticket override. null = inherit from settings.ai_resolve_default. */
  ai_resolve_override: boolean | null;
  ai_resolution_verdict: ResolutionVerdict | null;
  ai_resolution_confidence: number | null;
  ai_resolution_reason: string | null;
  resolution_chip_state: ResolutionChipState | null;
  /** Roadmap 0.2 — AI-assessed urgency. null on pre-0.2 rows. */
  ai_priority: AIPriority | null;
  /** Roadmap 0.2 — AI-assessed customer sentiment. null on pre-0.2 rows. */
  ai_sentiment: AISentiment | null;
  /** Roadmap 0.2 — secondary multi-label tags beyond the single category. */
  ai_labels: string[];
}

// ── Bulk actions (plan §8d) ──────────────────────────────────────────────────

export interface BulkFailure {
  id: string;
  reason: string;
}

export interface BulkResult {
  ok_ids: string[];
  failed: BulkFailure[];
}

// ── Filter + settings ────────────────────────────────────────────────────────

export type LookbackUnit = 'hours' | 'days';
export type Density = 'compact' | 'balanced' | 'comfy';

export interface FilterSettings {
  lookback_unit: LookbackUnit;
  lookback_value: number; // 1..720
  states: TicketState[];
  include_category_ids: number[] | null;
  mute_alarms: boolean; // FR-024 — shared by webapp + popup
  /** When false, ingest skips AI categorization — tickets land in the fallback
   *  category and the operator writes subject/summary by hand. */
  use_ai: boolean;
  /** Global default for AI-powered auto-resolve. Per-ticket override takes precedence. */
  ai_resolve_default: boolean;
  /** Confidence threshold (0..1) the AI verdict must meet before auto-resolving. */
  ai_resolve_confidence_threshold: number;
  /** When true (default), Board hides category columns with zero open tickets.
   *  Resolved column always shows regardless. */
  hide_empty_categories: boolean;
}

// ── Metrics (roadmap 1.4 — token / cost meter) ───────────────────────────────

/** OpenRouter token usage + estimated USD cost for one (day, model) bucket.
 *  In-process on the backend — resets when the backend restarts. */
export interface UsageBucket {
  date: string; // UTC calendar day, ISO `YYYY-MM-DD`.
  model: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  calls: number;
  estimated_cost_usd: number;
}

/** `GET /metrics` — process-lifetime counters, latency histograms, and the
 *  per-day OpenRouter spend meter. Only the cost-meter fields are typed here;
 *  counters/histograms are open-ended maps the webapp does not yet consume. */
export interface MetricsResponse {
  counters: Record<string, number>;
  usage: UsageBucket[];
  today_cost_usd: number;
}

// ── Stats dashboard (roadmap 1.3) ─────────────────────────────────────────────
//
// Read-only rollups over the tickets table (no migration). Mirrors
// backend/app/schemas.py StatsResponse. Resolution mix keys on `resolved_source`
// (manual | intercom_closed | non_actionable | ai_resolved, null = open).

/** Ticket count for one effective category. `category_id` is null for
 *  uncategorized tickets. */
export interface CategoryCount {
  category_id: number | null;
  category_name: string;
  count: number;
}

/** Tickets created on one UTC calendar day. `date` is ISO `YYYY-MM-DD`. Gap-
 *  filled by the backend so the trend has a point per day. */
export interface VolumePoint {
  date: string;
  count: number;
}

/** Resolution-source breakdown over the window. `open` counts tickets with no
 *  `resolved_at`. */
export interface ResolutionMix {
  open: number;
  manual: number;
  intercom_closed: number;
  non_actionable: number;
  ai_resolved: number;
}

/** One bucket of the time-to-resolve histogram. `upper_hours` is null for the
 *  final open-ended band. */
export interface ResolveTimeBucket {
  label: string;
  lower_hours: number;
  upper_hours: number | null;
  count: number;
}

/** `GET /stats` — the four success metrics, computed server-side over a
 *  trailing window of `window_days` (by ticket `created_at`). */
export interface StatsResponse {
  window_days: number;
  total_tickets: number;
  category_breakdown: CategoryCount[];
  volume_trend: VolumePoint[];
  resolution_mix: ResolutionMix;
  resolve_time_buckets: ResolveTimeBucket[];
  median_resolve_hours: number | null;
}

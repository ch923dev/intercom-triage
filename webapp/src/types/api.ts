// Server-side data contracts. Mirror of plan.md §3.

export interface HealthResponse {
  status: 'ok' | 'degraded';
  version: string;
  model: string;
  intercom_configured: boolean;
  openrouter_configured: boolean;
  missing_secrets: string[];
}

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

// ── Tickets (Phase 5 — wire when T025 lands) ─────────────────────────────────

export type TicketState = 'open' | 'snoozed' | 'closed';

export interface TicketAuthor {
  id: string | null;
  name: string | null;
  email: string | null;
  type: string | null;
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
}

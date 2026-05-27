// Saved views / smart filters (roadmap 1.1).
//
// A client-side facet filter the operator layers on top of the server-side
// lookback/state/category filter. It narrows the board to a focused queue —
// e.g. "urgent + unresolved + aged" — and can be saved as a named preset.
//
// All facet logic lives here as pure functions so it is unit-testable in
// isolation from Pinia / the DOM. The tickets store holds the *active* filter
// (the ad-hoc selection the board reacts to); the savedViews store owns the
// persisted named presets. Both drive these predicates.

import type { AIPriority, ResolvedSource, Ticket } from '@/types/api';

/** Resolution facet. `'open'` matches a ticket with no `resolved_source`
 *  (still on the board); the rest mirror `ResolvedSource` (invariant #10). */
export type ResolutionFacet = 'open' | ResolvedSource;

export const RESOLUTION_FACETS: ResolutionFacet[] = [
  'open',
  'manual',
  'intercom_closed',
  'non_actionable',
  'ai_resolved',
];

export const URGENCIES: AIPriority[] = ['urgent', 'high', 'normal', 'low'];

/**
 * A reusable filter spanning the four facets. Each facet is independent and
 * combines with AND; within a facet's set membership is OR.
 *
 * - `categoryIds: null` → any category (facet inactive). A non-null array
 *   matches the ticket's *effective* category (override beats AI).
 * - `urgencies: []` → any urgency (facet inactive). Otherwise the ticket's
 *   `ai_priority` must be in the set. A null `ai_priority` is treated as
 *   `'normal'` (mirrors utils/priority.ts).
 * - `resolution: []` → any resolution state (facet inactive). Otherwise the
 *   ticket's state (`'open'` or its `resolved_source`) must be in the set.
 * - `ageMinHours: null` → any age (facet inactive). Otherwise the ticket's
 *   last customer-visible message must be at least this many hours old.
 */
export interface SavedFilter {
  categoryIds: number[] | null;
  urgencies: AIPriority[];
  resolution: ResolutionFacet[];
  ageMinHours: number | null;
}

/** A named, persisted preset wrapping a filter. */
export interface SavedView {
  id: string;
  name: string;
  filter: SavedFilter;
}

/** The neutral filter — every facet inactive, so it matches every ticket. */
export const EMPTY_FILTER: SavedFilter = {
  categoryIds: null,
  urgencies: [],
  resolution: [],
  ageMinHours: null,
};

/** True when no facet is active — the filter is a pass-through. */
export function isEmptyFilter(f: SavedFilter): boolean {
  return (
    f.categoryIds === null &&
    f.urgencies.length === 0 &&
    f.resolution.length === 0 &&
    f.ageMinHours === null
  );
}

/** Defensive deep copy — callers persist/mutate filters independently. */
export function cloneFilter(f: SavedFilter): SavedFilter {
  return {
    categoryIds: f.categoryIds === null ? null : [...f.categoryIds],
    urgencies: [...f.urgencies],
    resolution: [...f.resolution],
    ageMinHours: f.ageMinHours,
  };
}

/**
 * Timestamp (ms) of the most recent customer-visible message on a ticket.
 *
 * Age is measured from the customer's last word, not Intercom's `updated_at`
 * (which an internal teammate note advances — invariant #4/#6). `parts[]` is
 * the customer-visible stream; we take its newest entry. Falls back to
 * `created_at` when a ticket has no parts yet. Returns NaN for an unparseable
 * timestamp so callers can decide (we treat NaN age as "unknown → no match").
 */
export function lastCustomerMessageAt(ticket: Ticket): number {
  let newest = Date.parse(ticket.created_at);
  for (const part of ticket.parts) {
    const t = Date.parse(part.created_at);
    if (!Number.isNaN(t) && (Number.isNaN(newest) || t > newest)) newest = t;
  }
  return newest;
}

/** The resolution facet a ticket currently sits in. */
export function resolutionFacet(ticket: Ticket): ResolutionFacet {
  return ticket.resolved_source ?? 'open';
}

/** Normalize a (possibly null) priority to a concrete urgency for matching.
 *  Null reads as `'normal'`, consistent with utils/priority.ts. */
function urgencyOf(ticket: Ticket): AIPriority {
  return ticket.ai_priority ?? 'normal';
}

/**
 * Pure predicate: does `ticket` satisfy `filter`?
 *
 * @param effectiveCategoryId the category to test against the `categoryIds`
 *   facet — the caller resolves "override beats AI" (e.g. pendingOverride ??
 *   category_id) so this stays pure and override-source-agnostic.
 * @param nowMs current time in ms (injectable for deterministic tests).
 */
export function ticketMatchesFilter(
  ticket: Ticket,
  filter: SavedFilter,
  effectiveCategoryId: number | null,
  nowMs: number = Date.now(),
): boolean {
  // Category facet.
  if (filter.categoryIds !== null) {
    if (effectiveCategoryId === null) return false;
    if (!filter.categoryIds.includes(effectiveCategoryId)) return false;
  }

  // Urgency facet.
  if (filter.urgencies.length > 0 && !filter.urgencies.includes(urgencyOf(ticket))) {
    return false;
  }

  // Resolution facet.
  if (filter.resolution.length > 0 && !filter.resolution.includes(resolutionFacet(ticket))) {
    return false;
  }

  // Age facet — at least `ageMinHours` since the last customer-visible message.
  if (filter.ageMinHours !== null) {
    const last = lastCustomerMessageAt(ticket);
    if (Number.isNaN(last)) return false;
    const ageHours = (nowMs - last) / 3_600_000;
    if (ageHours < filter.ageMinHours) return false;
  }

  return true;
}

// Bulk pre-flight diff (roadmap 1.6).
//
// Before the operator applies a bulk action we show "N will <action>, M
// skipped" so a mixed selection (e.g. some already-resolved tickets in the
// batch, or tickets already in the target category) is legible up front.
//
// The counts are computed CLIENT-SIDE from the already-loaded selected ticket
// rows — every field these rules read (`resolved_at`, `category_id`,
// `resolution_chip_state`, `followup`) is already on the `Ticket` shape the
// store holds, so no extra backend round-trip is needed for a single-operator
// local tool. The rules mirror the backend skip/409 semantics in
// `backend/app/services/bulk.py` + `services/resolution.py`:
//
//   - resolve / non-actionable : already-resolved rows 409 → skipped.
//   - reopen                   : not-resolved rows 409 → skipped.
//   - recategorize             : rows already in the target category are a
//                                no-op → counted as skipped (backend never
//                                409s, but the operator wants the real delta).
//   - dismiss-chip             : rows without a chip are a no-op → skipped.
//   - clear-followup           : rows without a follow-up are a no-op → skipped.
//
// The cap (cross-package invariant #9, `MAX_BULK_IDS = 200`) is mirrored here
// so the preview can warn when a selection exceeds what one request accepts.
// This is the webapp half of the cap; the backend half is the source of truth
// (`backend/app/config.py`). Bump both together.

import type { Ticket } from '@/types/api';

/** Per-request cap on bulk ticket ids. Mirrors `backend/app/config.py`
 *  `MAX_BULK_IDS`. Invariant #9 — keep in sync with the backend constant. */
export const MAX_BULK_IDS = 200;

/** Bulk actions that have a meaningful affect/skip preview. */
export type BulkAction =
  | 'resolve'
  | 'non_actionable'
  | 'reopen'
  | 'recategorize'
  | 'dismiss_chip'
  | 'clear_followup';

export interface BulkPreview {
  /** How many of the selected tickets the action will actually affect. */
  willAffect: number;
  /** How many are a no-op / would be skipped by the backend. */
  willSkip: number;
  /** True when the selection exceeds `MAX_BULK_IDS` and a single request would
   *  be rejected by the backend (invariant #9). */
  overCap: boolean;
}

/** Does `action` affect a single ticket, given its client-side state?
 *  `targetCategoryId` is only consulted for `recategorize`. */
function affectsTicket(
  action: BulkAction,
  ticket: Ticket,
  targetCategoryId: number | null,
): boolean {
  switch (action) {
    case 'resolve':
    case 'non_actionable':
      // 409 "already resolved" if resolved_at is set.
      return ticket.resolved_at === null;
    case 'reopen':
      // 409 "not resolved" if resolved_at is null.
      return ticket.resolved_at !== null;
    case 'recategorize':
      // No-op when already in the target category.
      return targetCategoryId !== null && ticket.category_id !== targetCategoryId;
    case 'dismiss_chip':
      // No-op when there is no chip to dismiss.
      return ticket.resolution_chip_state !== null;
    case 'clear_followup':
      // No-op when there is no follow-up to clear.
      return ticket.followup !== null;
  }
}

/**
 * Compute the affect/skip preview for `action` over the selected tickets.
 *
 * Pure — derives counts from the rows alone. `targetCategoryId` is required for
 * a meaningful `recategorize` preview (the category the operator is moving to);
 * pass `null` for the other actions.
 */
export function bulkPreview(
  action: BulkAction,
  selected: readonly Ticket[],
  targetCategoryId: number | null = null,
): BulkPreview {
  let willAffect = 0;
  for (const t of selected) {
    if (affectsTicket(action, t, targetCategoryId)) willAffect += 1;
  }
  return {
    willAffect,
    willSkip: selected.length - willAffect,
    overCap: selected.length > MAX_BULK_IDS,
  };
}

const ACTION_VERB: Record<BulkAction, string> = {
  resolve: 'resolve',
  non_actionable: 'mark non-actionable',
  reopen: 'reopen',
  recategorize: 'change category',
  dismiss_chip: 'dismiss chip',
  clear_followup: 'clear follow-up',
};

const SKIP_REASON: Record<BulkAction, string> = {
  resolve: 'already resolved',
  non_actionable: 'already resolved',
  reopen: 'not resolved',
  recategorize: 'already in target',
  dismiss_chip: 'no chip',
  clear_followup: 'no follow-up',
};

/** Human-readable one-liner, e.g. "12 will resolve, 3 skipped (already
 *  resolved)". Appends an over-cap note when the selection exceeds the cap. */
export function bulkPreviewLabel(action: BulkAction, preview: BulkPreview): string {
  const verb = ACTION_VERB[action];
  let label = `${preview.willAffect} will ${verb}`;
  if (preview.willSkip > 0) {
    label += `, ${preview.willSkip} skipped (${SKIP_REASON[action]})`;
  }
  if (preview.overCap) {
    label += ` — over ${MAX_BULK_IDS} cap, trim selection`;
  }
  return label;
}

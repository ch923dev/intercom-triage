// Needs-review lane predicate + threshold (roadmap 2.3).
//
// A view-layer split over the existing `ai_confidence` — NOT a stored ticket
// state (mirrors invariant #10 / the non-actionable column). An OPEN,
// non-overridden ticket whose categorization self-confidence is below the
// threshold surfaces in the "needs review" lane; the operator reviews it and
// confirming (writing a category override) clears it from the lane.
//
// Pure functions live here so the predicate is unit-testable in isolation from
// Pinia / the DOM (same pattern as utils/savedViews.ts).

import type { Ticket } from '@/types/api';

/**
 * Mirror of the backend `AppConfig.review_confidence_threshold` calibrated
 * default (backend/app/config.py; see backend/tests/test_review_calibration.py
 * for the basis). The backend is the source of truth and surfaces the live
 * value on `GET /health`; this constant is the fallback the board uses when the
 * health value hasn't been fetched. Keep the two in sync.
 */
export const REVIEW_CONFIDENCE_THRESHOLD = 0.65;

/**
 * Pure predicate: should `ticket` surface in the needs-review lane?
 *
 * True when the ticket is OPEN (not resolved/non-actionable — invariant #10),
 * has NOT been operator-overridden (an override is the operator confirming the
 * category, i.e. ground-truth that the AI was reviewed), and its categorization
 * self-confidence is strictly below `threshold`.
 *
 * @param overridden the *effective* override state — the caller folds in any
 *   optimistic pending override so a just-confirmed ticket drops out of the lane
 *   immediately, before the server round-trips (mirrors effectiveCategoryId).
 */
export function needsReview(
  ticket: Ticket,
  overridden: boolean,
  threshold: number = REVIEW_CONFIDENCE_THRESHOLD,
): boolean {
  if (ticket.resolved_at !== null) return false;
  if (overridden) return false;
  return ticket.ai_confidence < threshold;
}

// Priority ordering helpers (roadmap 1.2 — priority-sorted queue).
//
// The AI categorization call stamps each ticket with an `ai_priority`
// (roadmap 0.2). This module turns that enum into a sort rank so the operator
// can work a column top-down by urgency.
//
// NULL handling: pre-0.2 rows have `ai_priority === null`. We rank them the
// same as `'normal'` — `normal` is the unremarkable baseline (TicketCard hides
// the chip for it), so an un-scored ticket reads as "no special urgency" and
// stays interleaved with the other normal-priority cards in its existing
// recency order, rather than being dumped at the bottom of the column.

import type { AIPriority } from '@/types/api';

/** Sort rank — lower sorts first (urgent at the top of the queue). */
const PRIORITY_RANK: Record<AIPriority, number> = {
  urgent: 0,
  high: 1,
  normal: 2,
  low: 3,
};

/** Rank a (possibly null) priority. NULL ranks as `normal` (see module note). */
export function priorityRank(p: AIPriority | null | undefined): number {
  return p == null ? PRIORITY_RANK.normal : PRIORITY_RANK[p];
}

/**
 * Comparator ordering tickets urgent → high → normal → low.
 *
 * Returns the rank difference, so equal-priority tickets compare as `0` and
 * `Array.prototype.sort` (stable since ES2019) preserves their incoming order.
 * Feed it a list that is already in the desired tiebreak order (recency /
 * follow-up-due first) and that order survives untouched within each tier.
 */
export function byPriorityDesc(
  a: { ai_priority: AIPriority | null },
  b: { ai_priority: AIPriority | null },
): number {
  return priorityRank(a.ai_priority) - priorityRank(b.ai_priority);
}

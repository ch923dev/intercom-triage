// Card aging / personal-SLA tiers (roadmap 0.3).
//
// A single-operator tool has no contractual SLA, so these are *personal*
// aging targets: how long an open ticket may sit since the customer last
// spoke before it should nag the operator. We tier the card by the time
// since the LAST CUSTOMER-VISIBLE message — not Intercom `updated_at`, which
// advances on internal team notes (cross-package invariant #4/#6). A ticket
// where the ball is in our court must keep aging even while we add notes.
//
// Only OPEN tickets age. A resolved / non-actionable ticket (`resolved_at`
// set — invariant #10) is done; it shows no aging tier. A ticket with no
// customer-visible message at all (empty `parts`, or all-admin) also gets no
// tier — there is no customer clock to start.

import type { ConversationPart } from '@/types/api';

/** Aging tiers, least → most urgent. `null` = no tier (resolved / no clock). */
export type AgingTier = 'fresh' | 'aging' | 'stale' | 'critical';

/**
 * Personal aging thresholds, in milliseconds. A ticket whose last
 * customer-visible message is at least this old enters the named tier.
 *
 * Single source of truth — change a number here and every card retiers.
 * Tiers (by age since last customer message):
 *   - fresh    : < 4h        — recently active, no nag.
 *   - aging    : >= 4h       — worth a glance today.
 *   - stale    : >= 24h      — a day cold; should be actioned.
 *   - critical : >= 72h (3d) — rotting; surface loudly.
 */
export const AGING_THRESHOLDS = {
  aging: 4 * 60 * 60 * 1000, // 4 hours
  stale: 24 * 60 * 60 * 1000, // 1 day
  critical: 72 * 60 * 60 * 1000, // 3 days
} as const;

/**
 * Epoch-ms timestamp of the last customer-visible message in a thread, or
 * `null` if the thread has no customer message (empty, or all-admin).
 *
 * `parts[]` is the customer-visible thread; `is_admin === false` marks an
 * inbound customer message. Internal team notes live in `Ticket.internal_notes`
 * and are intentionally excluded.
 */
export function lastCustomerMessageMs(parts: ConversationPart[]): number | null {
  for (let i = parts.length - 1; i >= 0; i--) {
    const p = parts[i];
    if (!p.is_admin) {
      const t = Date.parse(p.created_at);
      return Number.isNaN(t) ? null : t;
    }
  }
  return null;
}

/**
 * The aging tier for an open ticket given its customer-visible thread and the
 * current instant. Returns `null` when no tier applies:
 *   - `resolved` is true (resolved / non-actionable — invariant #10), or
 *   - the thread has no datable customer-visible message.
 *
 * Pure: `nowMs` is injected so callers control the clock and tests can pin it.
 */
export function agingTier(
  parts: ConversationPart[],
  resolved: boolean,
  nowMs: number,
): AgingTier | null {
  if (resolved) return null;
  const last = lastCustomerMessageMs(parts);
  if (last === null) return null;
  const age = nowMs - last;
  if (age >= AGING_THRESHOLDS.critical) return 'critical';
  if (age >= AGING_THRESHOLDS.stale) return 'stale';
  if (age >= AGING_THRESHOLDS.aging) return 'aging';
  return 'fresh';
}

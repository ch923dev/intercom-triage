// Aging-tier unit tests (roadmap 0.3 — aging / personal-SLA indicators).

import { describe, expect, it } from 'vitest';
import { AGING_THRESHOLDS, agingTier, lastCustomerMessageMs } from './aging';
import type { ConversationPart } from '@/types/api';

const NOW = Date.parse('2026-05-27T12:00:00Z');

/** Build a conversation part at `ms` ago from NOW. */
function part(agoMs: number, is_admin: boolean): ConversationPart {
  return {
    author: {
      id: null,
      name: null,
      email: null,
      type: null,
      location: null,
      timezone: null,
      phone: null,
      company: null,
    },
    body: '',
    created_at: new Date(NOW - agoMs).toISOString(),
    is_admin,
    images: [],
  };
}

const H = 60 * 60 * 1000;

describe('lastCustomerMessageMs', () => {
  it('returns the most recent non-admin part timestamp', () => {
    const parts = [part(10 * H, false), part(5 * H, true), part(2 * H, false)];
    expect(lastCustomerMessageMs(parts)).toBe(NOW - 2 * H);
  });

  it('skips trailing admin replies to find the last customer message', () => {
    const parts = [part(10 * H, false), part(1 * H, true)];
    expect(lastCustomerMessageMs(parts)).toBe(NOW - 10 * H);
  });

  it('returns null for an empty thread', () => {
    expect(lastCustomerMessageMs([])).toBeNull();
  });

  it('returns null when every part is an admin message', () => {
    expect(lastCustomerMessageMs([part(3 * H, true), part(1 * H, true)])).toBeNull();
  });
});

describe('agingTier', () => {
  it('is fresh just under the aging threshold', () => {
    const parts = [part(AGING_THRESHOLDS.aging - 1, false)];
    expect(agingTier(parts, false, NOW)).toBe('fresh');
  });

  it('is aging exactly at the aging threshold (boundary inclusive)', () => {
    const parts = [part(AGING_THRESHOLDS.aging, false)];
    expect(agingTier(parts, false, NOW)).toBe('aging');
  });

  it('is stale exactly at the stale threshold', () => {
    const parts = [part(AGING_THRESHOLDS.stale, false)];
    expect(agingTier(parts, false, NOW)).toBe('stale');
  });

  it('is critical exactly at the critical threshold', () => {
    const parts = [part(AGING_THRESHOLDS.critical, false)];
    expect(agingTier(parts, false, NOW)).toBe('critical');
  });

  it('is critical well past the critical threshold', () => {
    const parts = [part(AGING_THRESHOLDS.critical + 100 * H, false)];
    expect(agingTier(parts, false, NOW)).toBe('critical');
  });

  it('returns null when resolved, regardless of age', () => {
    const parts = [part(AGING_THRESHOLDS.critical + 100 * H, false)];
    expect(agingTier(parts, true, NOW)).toBeNull();
  });

  it('returns null when there is no customer-visible message', () => {
    expect(agingTier([], false, NOW)).toBeNull();
    expect(agingTier([part(2 * H, true)], false, NOW)).toBeNull();
  });

  it('ages off the last CUSTOMER message, ignoring a fresh admin reply', () => {
    // Customer last spoke 30h ago (stale); we replied 1h ago. The admin reply
    // must not reset the clock — the ball is in the customer's court but the
    // ticket is still cold from the operator's follow-up perspective.
    const parts = [part(30 * H, false), part(1 * H, true)];
    expect(agingTier(parts, false, NOW)).toBe('stale');
  });
});

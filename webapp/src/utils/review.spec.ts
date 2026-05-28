// Needs-review predicate spec (roadmap 2.3). Pure function — no Pinia / DOM.
// Covers the threshold boundary (below / at / above), the overridden exclusion
// (operator confirmed → not in lane), and the resolved exclusion (invariant #10).

import { describe, expect, it } from 'vitest';
import { REVIEW_CONFIDENCE_THRESHOLD, needsReview } from './review';
import type { Ticket } from '@/types/api';

function fakeTicket(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 't1',
    title: 'title',
    state: 'open',
    priority: null,
    created_at: '2026-05-27T11:00:00.000Z',
    updated_at: '2026-05-27T11:00:00.000Z',
    author: {
      id: null,
      name: null,
      email: null,
      type: 'user',
      location: null,
      timezone: null,
      phone: null,
      company: null,
    },
    url: null,
    parts: [],
    internal_notes: [],
    category_id: 1,
    proposal_id: null,
    summary: '',
    ai_confidence: 0,
    user_override: false,
    title_user_edited: false,
    summary_user_edited: false,
    followup: null,
    note: null,
    resolved_at: null,
    resolved_source: null,
    ai_resolve_enabled: false,
    ai_resolve_override: null,
    ai_resolution_verdict: null,
    ai_resolution_confidence: null,
    ai_resolution_reason: null,
    resolution_chip_state: null,
    ai_priority: null,
    ai_sentiment: null,
    ai_labels: [],
    parked_at: null,
    parked_until: null,
    parked_reason: null,
    parked_note: null,
    non_actionable_kind: null,
    ...overrides,
  };
}

const T = REVIEW_CONFIDENCE_THRESHOLD;

describe('needsReview — threshold boundary', () => {
  it('flags an open, non-overridden ticket BELOW the threshold', () => {
    const t = fakeTicket({ ai_confidence: T - 0.01 });
    expect(needsReview(t, false)).toBe(true);
  });

  it('does NOT flag a ticket exactly AT the threshold (strict <)', () => {
    const t = fakeTicket({ ai_confidence: T });
    expect(needsReview(t, false)).toBe(false);
  });

  it('does NOT flag a ticket ABOVE the threshold', () => {
    const t = fakeTicket({ ai_confidence: T + 0.01 });
    expect(needsReview(t, false)).toBe(false);
  });

  it('always flags a zero-confidence fallback', () => {
    const t = fakeTicket({ ai_confidence: 0 });
    expect(needsReview(t, false)).toBe(true);
  });
});

describe('needsReview — exclusions', () => {
  it('excludes an overridden (operator-confirmed) low-confidence ticket', () => {
    const t = fakeTicket({ ai_confidence: 0.1, user_override: true });
    // Caller folds the override state into the `overridden` arg.
    expect(needsReview(t, true)).toBe(false);
  });

  it('excludes a resolved low-confidence ticket (invariant #10)', () => {
    const t = fakeTicket({
      ai_confidence: 0.1,
      resolved_at: '2026-05-27T12:00:00.000Z',
      resolved_source: 'manual',
    });
    expect(needsReview(t, false)).toBe(false);
  });

  it('excludes a non-actionable low-confidence ticket', () => {
    const t = fakeTicket({
      ai_confidence: 0.1,
      resolved_at: '2026-05-27T12:00:00.000Z',
      resolved_source: 'non_actionable',
    });
    expect(needsReview(t, false)).toBe(false);
  });
});

describe('needsReview — custom threshold', () => {
  it('respects an explicit threshold argument', () => {
    const t = fakeTicket({ ai_confidence: 0.8 });
    expect(needsReview(t, false, 0.9)).toBe(true);
    expect(needsReview(t, false, 0.7)).toBe(false);
  });
});

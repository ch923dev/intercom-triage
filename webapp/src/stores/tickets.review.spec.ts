// Tickets-store needs-review lane spec (roadmap 2.3). Covers the
// `needsReviewTickets` getter (open + non-overridden + low-confidence), the
// resolved exclusion, the optimistic-override-clears-lane behavior (the
// acceptance: confirming/overriding removes a ticket from the lane), and the
// `reviewOnly` board narrowing via byCategory.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useTicketsStore } from './tickets';
import { REVIEW_CONFIDENCE_THRESHOLD } from '@/utils/review';
import type { Ticket } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    overrideCategory: vi.fn(),
    listTickets: vi.fn(),
  },
}));

const NOW = '2026-05-25T00:00:00.000Z';
const T = REVIEW_CONFIDENCE_THRESHOLD;

function fakeTicket(id: string, overrides: Partial<Ticket> = {}): Ticket {
  return {
    id,
    title: `t-${id}`,
    state: 'open',
    priority: null,
    created_at: NOW,
    updated_at: NOW,
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
    ai_resolution_reason: null,
    ai_resolution_confidence: null,
    resolution_chip_state: null,
    ai_priority: null,
    ai_sentiment: null,
    ai_labels: [],
    parked_at: null,
    parked_until: null,
    parked_reason: null,
    ...overrides,
  };
}

describe('ticketsStore.needsReviewTickets', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('includes open, non-overridden, below-threshold tickets only', () => {
    const s = useTicketsStore();
    s.tickets.push(
      fakeTicket('low', { ai_confidence: T - 0.1 }),
      fakeTicket('at', { ai_confidence: T }),
      fakeTicket('high', { ai_confidence: T + 0.1 }),
      fakeTicket('overridden', { ai_confidence: T - 0.1, user_override: true }),
    );
    const ids = s.needsReviewTickets.map((t) => t.id);
    expect(ids).toEqual(['low']);
  });

  it('excludes resolved low-confidence tickets (invariant #10)', () => {
    const s = useTicketsStore();
    // Resolved rows live in resolvedTickets, not state.tickets — assert the
    // getter only walks the open list even if a stray resolved row appeared.
    s.tickets.push(
      fakeTicket('open-low', { ai_confidence: 0.1 }),
      fakeTicket('res-low', {
        ai_confidence: 0.1,
        resolved_at: NOW,
        resolved_source: 'manual',
      }),
    );
    const ids = s.needsReviewTickets.map((t) => t.id);
    expect(ids).toEqual(['open-low']);
  });

  it('drops a ticket from the lane when an override is applied (optimistic)', async () => {
    const { api } = await import('@/api/client');
    (api.overrideCategory as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('x', { ai_confidence: 0.1 }));
    expect(s.needsReviewTickets.map((t) => t.id)).toEqual(['x']);

    await s.applyOverride('x', 2);

    // The optimistic pendingOverride flips effectiveOverridden → out of lane.
    expect(s.needsReviewTickets).toEqual([]);
  });
});

describe('ticketsStore.reviewOnly narrowing', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('narrows byCategory to needs-review tickets when reviewOnly is on', () => {
    const s = useTicketsStore();
    s.tickets.push(
      fakeTicket('low', { ai_confidence: 0.1, category_id: 1 }),
      fakeTicket('high', { ai_confidence: 0.95, category_id: 1 }),
    );

    // Off — both tickets show in category 1.
    expect(s.byCategory.get(1)?.map((t) => t.id)).toEqual(['low', 'high']);

    s.setReviewOnly(true);
    expect(s.reviewOnly).toBe(true);
    // On — only the low-confidence ticket remains.
    expect(s.byCategory.get(1)?.map((t) => t.id)).toEqual(['low']);

    s.toggleReviewOnly();
    expect(s.reviewOnly).toBe(false);
    expect(s.byCategory.get(1)?.map((t) => t.id)).toEqual(['low', 'high']);
  });
});

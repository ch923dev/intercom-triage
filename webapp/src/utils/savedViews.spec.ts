// Saved-views predicate spec (roadmap 1.1). Covers each facet in isolation,
// facet combinations (AND across facets), and the age derivation from the last
// customer-visible message timestamp. Pure functions — no Pinia / DOM.

import { describe, expect, it } from 'vitest';
import {
  EMPTY_FILTER,
  cloneFilter,
  isEmptyFilter,
  lastCustomerMessageAt,
  resolutionFacet,
  ticketMatchesFilter,
  type SavedFilter,
} from './savedViews';
import type { ConversationPart, Ticket } from '@/types/api';

const NOW = Date.parse('2026-05-27T12:00:00.000Z');

function part(created_at: string, is_admin = false): ConversationPart {
  return {
    author: {
      id: null,
      name: null,
      email: null,
      type: is_admin ? 'admin' : 'user',
      location: null,
      timezone: null,
      phone: null,
      company: null,
    },
    body: 'x',
    created_at,
    is_admin,
    images: [],
  };
}

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
    resolved_by: null,
    acted_by: null,
    assigned_to: null,
    assigned_at: null,
    ...overrides,
  };
}

function filter(over: Partial<SavedFilter> = {}): SavedFilter {
  return { ...cloneFilter(EMPTY_FILTER), ...over };
}

describe('isEmptyFilter', () => {
  it('is true for the neutral filter', () => {
    expect(isEmptyFilter(EMPTY_FILTER)).toBe(true);
  });
  it('is false when any facet is set', () => {
    expect(isEmptyFilter(filter({ urgencies: ['high'] }))).toBe(false);
    expect(isEmptyFilter(filter({ categoryIds: [1] }))).toBe(false);
    expect(isEmptyFilter(filter({ resolution: ['open'] }))).toBe(false);
    expect(isEmptyFilter(filter({ ageMinHours: 1 }))).toBe(false);
  });
});

describe('cloneFilter', () => {
  it('deep-copies arrays so mutation does not leak', () => {
    const src = filter({ categoryIds: [1, 2], urgencies: ['high'], resolution: ['open'] });
    const copy = cloneFilter(src);
    copy.categoryIds!.push(3);
    copy.urgencies.push('low');
    expect(src.categoryIds).toEqual([1, 2]);
    expect(src.urgencies).toEqual(['high']);
  });
  it('preserves null categoryIds', () => {
    expect(cloneFilter(filter({ categoryIds: null })).categoryIds).toBeNull();
  });
});

describe('lastCustomerMessageAt', () => {
  it('falls back to created_at when there are no parts', () => {
    const t = fakeTicket({ created_at: '2026-05-27T10:00:00.000Z', parts: [] });
    expect(lastCustomerMessageAt(t)).toBe(Date.parse('2026-05-27T10:00:00.000Z'));
  });
  it('returns the newest part timestamp', () => {
    const t = fakeTicket({
      created_at: '2026-05-27T08:00:00.000Z',
      parts: [part('2026-05-27T09:00:00.000Z'), part('2026-05-27T10:30:00.000Z', true)],
    });
    expect(lastCustomerMessageAt(t)).toBe(Date.parse('2026-05-27T10:30:00.000Z'));
  });
  it('uses created_at when it is newer than all parts (out-of-order safety)', () => {
    const t = fakeTicket({
      created_at: '2026-05-27T11:00:00.000Z',
      parts: [part('2026-05-27T09:00:00.000Z')],
    });
    expect(lastCustomerMessageAt(t)).toBe(Date.parse('2026-05-27T11:00:00.000Z'));
  });
});

describe('resolutionFacet', () => {
  it('maps a null resolved_source to "open"', () => {
    expect(resolutionFacet(fakeTicket({ resolved_source: null }))).toBe('open');
  });
  it('passes through the resolved_source', () => {
    expect(resolutionFacet(fakeTicket({ resolved_source: 'non_actionable' }))).toBe(
      'non_actionable',
    );
  });
});

describe('ticketMatchesFilter — pass-through', () => {
  it('matches any ticket under the empty filter', () => {
    expect(ticketMatchesFilter(fakeTicket(), EMPTY_FILTER, 1, NOW)).toBe(true);
  });
});

describe('ticketMatchesFilter — category facet', () => {
  it('matches when the effective category is in the set', () => {
    expect(ticketMatchesFilter(fakeTicket(), filter({ categoryIds: [1, 2] }), 2, NOW)).toBe(true);
  });
  it('rejects when the effective category is not in the set', () => {
    expect(ticketMatchesFilter(fakeTicket(), filter({ categoryIds: [1, 2] }), 9, NOW)).toBe(false);
  });
  it('rejects a null effective category against a concrete set', () => {
    expect(ticketMatchesFilter(fakeTicket(), filter({ categoryIds: [1] }), null, NOW)).toBe(false);
  });
  it('uses the passed effective id, not ticket.category_id (override beats AI)', () => {
    const t = fakeTicket({ category_id: 5 });
    expect(ticketMatchesFilter(t, filter({ categoryIds: [7] }), 7, NOW)).toBe(true);
  });
});

describe('ticketMatchesFilter — urgency facet', () => {
  it('matches when ai_priority is in the set', () => {
    const t = fakeTicket({ ai_priority: 'urgent' });
    expect(ticketMatchesFilter(t, filter({ urgencies: ['urgent', 'high'] }), 1, NOW)).toBe(true);
  });
  it('rejects when ai_priority is not in the set', () => {
    const t = fakeTicket({ ai_priority: 'low' });
    expect(ticketMatchesFilter(t, filter({ urgencies: ['urgent', 'high'] }), 1, NOW)).toBe(false);
  });
  it('treats a null ai_priority as "normal"', () => {
    const t = fakeTicket({ ai_priority: null });
    expect(ticketMatchesFilter(t, filter({ urgencies: ['normal'] }), 1, NOW)).toBe(true);
    expect(ticketMatchesFilter(t, filter({ urgencies: ['urgent'] }), 1, NOW)).toBe(false);
  });
});

describe('ticketMatchesFilter — resolution facet', () => {
  it('matches an open ticket against "open"', () => {
    const t = fakeTicket({ resolved_source: null });
    expect(ticketMatchesFilter(t, filter({ resolution: ['open'] }), 1, NOW)).toBe(true);
  });
  it('rejects a resolved ticket against "open"', () => {
    const t = fakeTicket({ resolved_source: 'manual' });
    expect(ticketMatchesFilter(t, filter({ resolution: ['open'] }), 1, NOW)).toBe(false);
  });
  it('matches a non-actionable ticket against its source', () => {
    const t = fakeTicket({ resolved_source: 'non_actionable' });
    expect(ticketMatchesFilter(t, filter({ resolution: ['non_actionable'] }), 1, NOW)).toBe(true);
  });
  it('matches against a multi-source set (OR within facet)', () => {
    const t = fakeTicket({ resolved_source: 'intercom_closed' });
    expect(
      ticketMatchesFilter(t, filter({ resolution: ['manual', 'intercom_closed'] }), 1, NOW),
    ).toBe(true);
  });
});

/** Build a ticket whose last customer-visible message is at `iso`. Sets both
 *  created_at and a single part to that time so `lastCustomerMessageAt` (which
 *  takes the newest of the two) resolves to it deterministically. */
function ticketLastMessageAt(iso: string, over: Partial<Ticket> = {}): Ticket {
  return fakeTicket({ created_at: iso, parts: [part(iso)], ...over });
}

describe('ticketMatchesFilter — age facet', () => {
  it('matches a ticket older than the threshold', () => {
    // last message 5h before NOW; threshold 4h → match.
    const t = ticketLastMessageAt('2026-05-27T07:00:00.000Z');
    expect(ticketMatchesFilter(t, filter({ ageMinHours: 4 }), 1, NOW)).toBe(true);
  });
  it('rejects a ticket younger than the threshold', () => {
    // last message 1h before NOW; threshold 4h → reject.
    const t = ticketLastMessageAt('2026-05-27T11:00:00.000Z');
    expect(ticketMatchesFilter(t, filter({ ageMinHours: 4 }), 1, NOW)).toBe(false);
  });
  it('matches exactly at the threshold boundary', () => {
    const t = ticketLastMessageAt('2026-05-27T08:00:00.000Z'); // exactly 4h
    expect(ticketMatchesFilter(t, filter({ ageMinHours: 4 }), 1, NOW)).toBe(true);
  });
  it('measures age from the newest part, not Intercom updated_at', () => {
    // A teammate-note-driven updated_at must not freshen the age. We only read
    // parts + created_at, so a stale updated_at is irrelevant.
    const t = ticketLastMessageAt('2026-05-27T06:00:00.000Z', {
      updated_at: '2026-05-27T11:59:00.000Z',
    });
    expect(ticketMatchesFilter(t, filter({ ageMinHours: 4 }), 1, NOW)).toBe(true);
  });
});

describe('ticketMatchesFilter — combinations (AND across facets)', () => {
  const morningQueue: SavedFilter = filter({
    urgencies: ['urgent', 'high'],
    resolution: ['open'],
    ageMinHours: 4,
  });

  // 6h old (created_at + part both at 06:00 so the newest is 06:00).
  const sixHoursOld = {
    created_at: '2026-05-27T06:00:00.000Z',
    parts: [part('2026-05-27T06:00:00.000Z')],
  };

  it('matches a ticket satisfying every facet', () => {
    const t = fakeTicket({ ai_priority: 'urgent', resolved_source: null, ...sixHoursOld });
    expect(ticketMatchesFilter(t, morningQueue, 1, NOW)).toBe(true);
  });

  it('rejects when one facet fails (resolved)', () => {
    const t = fakeTicket({ ai_priority: 'urgent', resolved_source: 'manual', ...sixHoursOld });
    expect(ticketMatchesFilter(t, morningQueue, 1, NOW)).toBe(false);
  });

  it('rejects when one facet fails (too fresh)', () => {
    // last message 30m old (created_at + part both at 11:30) → fails age 4h.
    const t = fakeTicket({
      ai_priority: 'high',
      resolved_source: null,
      created_at: '2026-05-27T11:30:00.000Z',
      parts: [part('2026-05-27T11:30:00.000Z')],
    });
    expect(ticketMatchesFilter(t, morningQueue, 1, NOW)).toBe(false);
  });

  it('rejects when one facet fails (low urgency)', () => {
    const t = fakeTicket({ ai_priority: 'low', resolved_source: null, ...sixHoursOld });
    expect(ticketMatchesFilter(t, morningQueue, 1, NOW)).toBe(false);
  });

  it('combines category + urgency', () => {
    const f = filter({ categoryIds: [3], urgencies: ['high'] });
    const t = fakeTicket({ ai_priority: 'high' });
    expect(ticketMatchesFilter(t, f, 3, NOW)).toBe(true);
    expect(ticketMatchesFilter(t, f, 4, NOW)).toBe(false);
  });
});

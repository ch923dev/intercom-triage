// Tickets-store spec — covers markNonActionable + bulkMarkNonActionable
// optimistic + rollback. Reference:
// docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md §10.2.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useTicketsStore } from './tickets';
import type { Ticket } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    markNonActionable: vi.fn(),
    bulkMarkNonActionable: vi.fn(),
    resolveTicket: vi.fn(),
    reopenTicket: vi.fn(),
    bulkResolve: vi.fn(),
    bulkReopen: vi.fn(),
    bulkRecategorize: vi.fn(),
    bulkDismissChip: vi.fn(),
    setAiResolve: vi.fn(),
    dismissChip: vi.fn(),
    overrideCategory: vi.fn(),
    editTicket: vi.fn(),
    listTickets: vi.fn(),
  },
}));

const NOW = '2026-05-25T00:00:00.000Z';

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

describe('ticketsStore.markNonActionable', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('moves the ticket to resolvedTickets with non_actionable source', async () => {
    const { api } = await import('@/api/client');
    (api.markNonActionable as ReturnType<typeof vi.fn>).mockResolvedValue({
      resolved_at: NOW,
      resolved_source: 'non_actionable',
    });
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    await s.markNonActionable('a');

    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    const moved = s.resolvedTickets.find((t) => t.id === 'a');
    expect(moved).toBeDefined();
    expect(moved!.resolved_source).toBe('non_actionable');
  });

  it('rolls back on API failure', async () => {
    const { api } = await import('@/api/client');
    (api.markNonActionable as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('b'));

    await expect(s.markNonActionable('b')).rejects.toThrow('boom');
    expect(s.tickets.find((t) => t.id === 'b')).toBeDefined();
    expect(s.resolvedTickets.find((t) => t.id === 'b')).toBeUndefined();
  });
});

describe('ticketsStore.resolved getters', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('splits resolvedTickets by source into pureResolvedTickets + nonActionableTickets', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('m', { resolved_at: NOW, resolved_source: 'manual' }),
      fakeTicket('n', { resolved_at: NOW, resolved_source: 'non_actionable' }),
      fakeTicket('i', { resolved_at: NOW, resolved_source: 'intercom_closed' }),
    );

    expect(s.pureResolvedTickets.map((t) => t.id).sort()).toEqual(['i', 'm']);
    expect(s.nonActionableTickets.map((t) => t.id)).toEqual(['n']);
  });
});

describe('ticketsStore bulk cap pre-flight (invariant #9)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  const overCapIds = Array.from({ length: 201 }, (_, i) => `t-${i}`);

  it('bulkResolve blocks an over-cap selection without calling the API', async () => {
    const { api } = await import('@/api/client');
    const s = useTicketsStore();

    const result = await s.bulkResolve(overCapIds);

    expect(api.bulkResolve).not.toHaveBeenCalled();
    expect(result.ok_ids).toEqual([]);
    expect(result.failed.length).toBe(201);
    expect(result.failed[0]!.reason).toContain('200');
  });

  it('bulkRecategorize blocks an over-cap selection without mutating state', async () => {
    const { api } = await import('@/api/client');
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('keep', { category_id: 1 }));

    const result = await s.bulkRecategorize(overCapIds, 2);

    expect(api.bulkRecategorize).not.toHaveBeenCalled();
    expect(result.ok_ids).toEqual([]);
    expect(result.failed.length).toBe(201);
    expect(s.pendingOverrides).toEqual({});
    expect(s.tickets.find((t) => t.id === 'keep')!.category_id).toBe(1);
  });

  it('still calls the API for a selection exactly at the cap', async () => {
    const { api } = await import('@/api/client');
    (api.bulkResolve as ReturnType<typeof vi.fn>).mockResolvedValue({ ok_ids: [], failed: [] });
    const s = useTicketsStore();
    const atCap = Array.from({ length: 200 }, (_, i) => `t-${i}`);

    await s.bulkResolve(atCap);

    expect(api.bulkResolve).toHaveBeenCalledOnce();
  });
});

describe('ticketsStore.bulkRecategorize partial-failure rollback ordering', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('restores multiple failed resolved rows to their original positions', async () => {
    const { api } = await import('@/api/client');
    const s = useTicketsStore();
    // Five resolved rows; B and C (adjacent, middle) get recategorized then fail.
    for (const id of ['A', 'B', 'C', 'D', 'E']) {
      s.resolvedTickets.push(fakeTicket(id, { resolved_at: NOW, resolved_source: 'manual' }));
    }
    (api.bulkRecategorize as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok_ids: [],
      failed: [
        { id: 'B', reason: 'x' },
        { id: 'C', reason: 'x' },
      ],
    });

    await s.bulkRecategorize(['B', 'C'], 2);

    // Both failed → both must return to resolvedTickets in their original order.
    expect(s.resolvedTickets.map((t) => t.id)).toEqual(['A', 'B', 'C', 'D', 'E']);
    // And neither should be left lingering in the open list.
    expect(s.tickets.find((t) => t.id === 'B' || t.id === 'C')).toBeUndefined();
  });
});

/** A promise whose resolution the test controls — lets us hold a mutation
 *  "in flight" while asserting other store behaviour. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('ticketsStore.silentRefresh race guard (C1)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('skips the poll while an optimistic mutation is in flight', async () => {
    const { api } = await import('@/api/client');
    const d = deferred<unknown>();
    (api.resolveTicket as ReturnType<typeof vi.fn>).mockReturnValue(d.promise);
    (api.listTickets as ReturnType<typeof vi.fn>).mockResolvedValue([]);
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    // Begin an optimistic resolve but don't await it — mutating is now > 0.
    const inFlight = s.markResolved('a');
    expect(s.isMutating).toBe(true);

    await s.silentRefresh();
    expect(api.listTickets).not.toHaveBeenCalled();

    // Let the mutation finish; the guard lifts.
    d.resolve(undefined);
    await inFlight;
    expect(s.isMutating).toBe(false);
    await s.silentRefresh();
    expect(api.listTickets).toHaveBeenCalled();
  });

  it('does not clobber the optimistic move that the failed poll would have reverted', async () => {
    const { api } = await import('@/api/client');
    const d = deferred<unknown>();
    (api.resolveTicket as ReturnType<typeof vi.fn>).mockReturnValue(d.promise);
    // The server still reports the ticket as open (resolve not yet committed).
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) => (resolved ? [] : [fakeTicket('a')]),
    );
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    const inFlight = s.markResolved('a');
    await s.silentRefresh(); // guarded → no-op, optimistic move preserved
    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    expect(s.resolvedTickets.find((t) => t.id === 'a')).toBeDefined();

    d.resolve(undefined);
    await inFlight;
  });
});

describe('ticketsStore.pendingOverrides reconcile (C1)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('drops a pending override once the server data reflects it', async () => {
    const { api } = await import('@/api/client');
    (api.overrideCategory as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a', { category_id: 1 }));

    await s.applyOverride('a', 2);
    expect(s.pendingOverrides.a).toBe(2);

    // Server now returns the ticket already in category 2.
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) =>
        resolved ? [] : [fakeTicket('a', { category_id: 2 })],
    );
    await s.refresh();
    expect(s.pendingOverrides.a).toBeUndefined();
  });
});

describe('ticketsStore.editTicket on a resolved ticket (A1)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('edits the title of a ticket that lives in resolvedTickets', async () => {
    const { api } = await import('@/api/client');
    (api.editTicket as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const s = useTicketsStore();
    s.resolvedTickets.push(fakeTicket('r', { resolved_at: NOW, resolved_source: 'manual' }));

    await s.editTicket('r', { title: 'edited title' });

    const row = s.resolvedTickets.find((t) => t.id === 'r')!;
    expect(row.title).toBe('edited title');
    expect(row.title_user_edited).toBe(true);
    expect(api.editTicket).toHaveBeenCalledWith('r', { title: 'edited title' });
  });

  it('rolls back a resolved-ticket edit on API failure', async () => {
    const { api } = await import('@/api/client');
    (api.editTicket as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    const s = useTicketsStore();
    s.resolvedTickets.push(fakeTicket('r', { resolved_at: NOW, resolved_source: 'manual' }));

    await expect(s.editTicket('r', { title: 'edited title' })).rejects.toThrow('boom');
    expect(s.resolvedTickets.find((t) => t.id === 'r')!.title).toBe('t-r');
  });
});

describe('ticketsStore.nonActionableKindFilter (T107)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('filteredNonActionableTickets returns all non-actionable tickets when filter is null', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('a', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'spam',
      }),
      fakeTicket('b', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'thanks',
      }),
      fakeTicket('c', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'auto_reply',
      }),
    );

    expect(s.filteredNonActionableTickets.map((t) => t.id).sort()).toEqual(['a', 'b', 'c']);
  });

  it('filteredNonActionableTickets filters by kind when filter is set', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('a', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'spam',
      }),
      fakeTicket('b', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'thanks',
      }),
      fakeTicket('c', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'spam',
      }),
    );

    s.setNonActionableKindFilter('spam');
    expect(s.filteredNonActionableTickets.map((t) => t.id).sort()).toEqual(['a', 'c']);
  });

  it('treats a filter for an absent kind as inert — shows all, not empty (finding #1)', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('a', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'spam',
      }),
    );

    // 'thanks' is not present in the set, so the filter cannot hide the spam
    // ticket — an active filter for an unselectable kind is inert.
    s.setNonActionableKindFilter('thanks');
    expect(s.filteredNonActionableTickets.map((t) => t.id)).toEqual(['a']);
    expect(s.effectiveNonActionableKindFilter).toBeNull();
  });

  it('presentNonActionableKinds lists only present kinds in canonical order', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('a', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'out_of_office',
      }),
      fakeTicket('b', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'spam',
      }),
      fakeTicket('c', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: null,
      }),
    );

    expect(s.presentNonActionableKinds).toEqual(['spam', 'out_of_office']);
  });

  it('stops hiding tickets once the active kind drains from the set (finding #1)', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('spam-1', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'spam',
      }),
      fakeTicket('manual-1', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: null,
      }),
    );
    s.setNonActionableKindFilter('spam');
    expect(s.filteredNonActionableTickets.map((t) => t.id)).toEqual(['spam-1']);

    // The last spam ticket is reopened/recategorized; only a manual-mark
    // (kind=null) non-actionable ticket survives. 'spam' is no longer present.
    s.resolvedTickets.splice(
      0,
      s.resolvedTickets.length,
      fakeTicket('manual-1', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: null,
      }),
    );

    // The stale filter must not strand the surviving ticket, and the effective
    // filter clears so the chip highlight stays consistent.
    expect(s.filteredNonActionableTickets.map((t) => t.id)).toEqual(['manual-1']);
    expect(s.effectiveNonActionableKindFilter).toBeNull();
  });

  it('setNonActionableKindFilter(null) clears the filter', () => {
    const s = useTicketsStore();
    s.resolvedTickets.push(
      fakeTicket('a', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'spam',
      }),
      fakeTicket('b', {
        resolved_at: NOW,
        resolved_source: 'non_actionable',
        non_actionable_kind: 'thanks',
      }),
    );

    s.setNonActionableKindFilter('spam');
    expect(s.filteredNonActionableTickets).toHaveLength(1);

    s.setNonActionableKindFilter(null);
    expect(s.filteredNonActionableTickets).toHaveLength(2);
  });
});

describe('ticketsStore.bulkMarkNonActionable', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('moves every ok id and rolls back failed ids', async () => {
    const { api } = await import('@/api/client');
    (api.bulkMarkNonActionable as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok_ids: ['x', 'z'],
      failed: [{ id: 'y', reason: 'already resolved' }],
    });
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('x'), fakeTicket('y'), fakeTicket('z'));

    const result = await s.bulkMarkNonActionable(['x', 'y', 'z']);

    expect(result.ok_ids).toEqual(['x', 'z']);
    expect(s.resolvedTickets.map((t) => t.id).sort()).toEqual(['x', 'z']);
    expect(s.tickets.find((t) => t.id === 'y')).toBeDefined();
  });
});

describe('ticketsStore.bulkReopen partial-failure rollback', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('restores failed rows to their original resolved positions regardless of failed[] order', async () => {
    const { api } = await import('@/api/client');
    const s = useTicketsStore();
    // Resolved column order: X(0) A(1) B(2) C(3) Y(4). Reopen A, B, C.
    s.resolvedTickets.push(
      fakeTicket('X', { resolved_at: NOW, resolved_source: 'manual' }),
      fakeTicket('A', { resolved_at: NOW, resolved_source: 'manual' }),
      fakeTicket('B', { resolved_at: NOW, resolved_source: 'manual' }),
      fakeTicket('C', { resolved_at: NOW, resolved_source: 'manual' }),
      fakeTicket('Y', { resolved_at: NOW, resolved_source: 'manual' }),
    );
    // Server rejects all three, reported in scrambled (non-ascending) order.
    (api.bulkReopen as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok_ids: [],
      failed: [
        { id: 'C', reason: 'locked' },
        { id: 'A', reason: 'locked' },
        { id: 'B', reason: 'locked' },
      ],
    });

    await s.bulkReopen(['A', 'B', 'C']);

    // All three return to resolved in their original interleaved order.
    expect(s.resolvedTickets.map((t) => t.id)).toEqual(['X', 'A', 'B', 'C', 'Y']);
    // None leaked into the open list.
    expect(s.tickets.map((t) => t.id)).toEqual([]);
  });
});

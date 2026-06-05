// Race spec — background silentRefresh() firing WHILE an operator's optimistic
// mutation is in flight must not clobber the pending change (auto-sync race,
// cross-package invariant: optimistic state the server doesn't yet reflect).
//
// Two guards protect optimistic state: (1) the `mutating` counter — bails
// `silentRefresh()` while a mutation is in flight at poll start; (2) the
// `mutationGen` counter — discards a poll whose fetch was already in flight
// when a mutation began (the R.2 reverse ordering), even one that finished
// during the fetch. These tests lock both directions in.
//
// tickets.spec.ts already covers the markResolved vs silentRefresh path; this
// file extends coverage to the category-override path (applyOverride), which is
// the scenario most likely to silently regress because its optimistic state
// lives in `pendingOverrides` rather than in a list move.

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
    assignTicket: vi.fn(),
    bulkAssign: vi.fn(),
  },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
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

/** A promise whose resolution the test controls — lets us hold a mutation
 *  "in flight" while a background silentRefresh fires. */
function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe('ticketsStore — silentRefresh vs in-flight applyOverride (R.2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('does not clobber a pending category override when the poll returns stale server state', async () => {
    const { api } = await import('@/api/client');

    // The override PATCH is held in flight — operator's intent is applied
    // optimistically but not yet committed server-side.
    const patch = deferred<unknown>();
    (api.overrideCategory as ReturnType<typeof vi.fn>).mockReturnValue(patch.promise);

    // A background poll that, if it ran, would return the ticket STILL in its
    // original category 1 (the server hasn't seen the override yet).
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) =>
        resolved ? [] : [fakeTicket('a', { category_id: 1 })],
    );

    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a', { category_id: 1 }));

    // 1. Operator overrides category 1 → 2; don't await — mutation is in flight.
    const inFlight = s.applyOverride('a', 2);

    // The optimistic override is reflected locally.
    expect(s.isMutating).toBe(true);
    expect(s.pendingOverrides.a).toBe(2);

    // 2. Background auto-sync fires mid-mutation.
    await s.silentRefresh();

    // 3. The guard short-circuited the poll: server was never queried and the
    //    operator's pending override is intact (NOT clobbered back to cat 1).
    expect(api.listTickets).not.toHaveBeenCalled();
    expect(s.pendingOverrides.a).toBe(2);
    // byCategory groups by the optimistic override, so ticket 'a' sits in cat 2.
    expect(s.byCategory.get(2)?.map((t) => t.id)).toEqual(['a']);
    expect(s.byCategory.get(1) ?? []).toEqual([]);

    // 4. Commit the mutation; the guard lifts and final state is consistent.
    patch.resolve(undefined);
    await inFlight;
    expect(s.isMutating).toBe(false);
    expect(s.pendingOverrides.a).toBe(2);

    // A subsequent poll now runs (guard lifted). Server has caught up and
    // reports cat 2, so the pending override is reconciled away.
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) =>
        resolved ? [] : [fakeTicket('a', { category_id: 2 })],
    );
    await s.silentRefresh();
    expect(api.listTickets).toHaveBeenCalled();
    expect(s.pendingOverrides.a).toBeUndefined();
    expect(s.byId.get('a')?.category_id).toBe(2);
  });

  it('queues the poll behind a timer-driven auto-sync and still skips while mutating', async () => {
    // Mirrors App.vue's setInterval(tickets.silentRefresh, autoSyncSeconds*1000).
    vi.useFakeTimers();
    try {
      const { api } = await import('@/api/client');
      const patch = deferred<unknown>();
      (api.overrideCategory as ReturnType<typeof vi.fn>).mockReturnValue(patch.promise);
      (api.listTickets as ReturnType<typeof vi.fn>).mockResolvedValue([]);

      const s = useTicketsStore();
      s.tickets.push(fakeTicket('a', { category_id: 1 }));

      const inFlight = s.applyOverride('a', 2);
      expect(s.isMutating).toBe(true);

      // Arm a periodic silent refresh, then advance the clock to fire it.
      const timer = setInterval(() => void s.silentRefresh(), 5000);
      vi.advanceTimersByTime(5000);
      await Promise.resolve(); // let the (no-op) silentRefresh microtask settle
      clearInterval(timer);

      // The tick fired while mutating > 0 → poll skipped, override preserved.
      expect(api.listTickets).not.toHaveBeenCalled();
      expect(s.pendingOverrides.a).toBe(2);

      patch.resolve(undefined);
      await inFlight;
      expect(s.isMutating).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it('does not clobber an in-flight markResolved move (cross-check, applyOverride sibling)', async () => {
    const { api } = await import('@/api/client');
    const patch = deferred<unknown>();
    (api.resolveTicket as ReturnType<typeof vi.fn>).mockReturnValue(patch.promise);
    // Stale server view: still reports the ticket as open.
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) => (resolved ? [] : [fakeTicket('a')]),
    );

    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    const inFlight = s.markResolved('a');
    await s.silentRefresh();

    // Optimistic move survives: gone from open, present in resolved.
    expect(api.listTickets).not.toHaveBeenCalled();
    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    expect(s.resolvedTickets.find((t) => t.id === 'a')).toBeDefined();

    patch.resolve(undefined);
    await inFlight;
    expect(s.isMutating).toBe(false);
  });

  it('does not clobber a list-move mutation that begins after a silentRefresh fetch is already in flight (R.2 reverse ordering)', async () => {
    const { api } = await import('@/api/client');

    // The poll's GETs are held in flight — dispatched BEFORE the operator's
    // mutation, so they carry pre-mutation (stale) server state.
    const openFetch = deferred<Ticket[]>();
    const resolvedFetch = deferred<Ticket[]>();
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) =>
        resolved ? resolvedFetch.promise : openFetch.promise,
    );
    // Hold the resolve PATCH in flight too, so mutating > 0 when the poll lands.
    const patch = deferred<unknown>();
    (api.resolveTicket as ReturnType<typeof vi.fn>).mockReturnValue(patch.promise);

    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    // 1. Poll starts while idle (passes the mutating==0 guard); GETs in flight.
    const poll = s.silentRefresh();

    // 2. Operator resolves 'a' mid-fetch — optimistic move applied locally.
    const move = s.markResolved('a');
    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    expect(s.resolvedTickets.find((t) => t.id === 'a')).toBeDefined();

    // 3. Stale poll lands: server still reports 'a' OPEN.
    openFetch.resolve([fakeTicket('a')]);
    resolvedFetch.resolve([]);
    await poll;

    // 4. Optimistic resolve survived — the poll discarded its stale snapshot.
    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    expect(s.resolvedTickets.find((t) => t.id === 'a')).toBeDefined();

    patch.resolve(undefined);
    await move;
    expect(s.isMutating).toBe(false);
  });

  it('manual refresh() does not clobber an in-flight optimistic mutation', async () => {
    const { api } = await import('@/api/client');
    // Hold the resolve PATCH in flight so mutating > 0 across the refresh.
    const patch = deferred<unknown>();
    (api.resolveTicket as ReturnType<typeof vi.fn>).mockReturnValue(patch.promise);
    // Stale server view: still reports the ticket OPEN.
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) => (resolved ? [] : [fakeTicket('a')]),
    );

    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    // Operator resolves 'a' (optimistic move), then hits 'r' / Topbar refresh
    // while the PATCH is still in flight.
    const inFlight = s.markResolved('a');
    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    await s.refresh();

    // The stale wholesale snapshot was discarded — optimistic move survives.
    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    expect(s.resolvedTickets.find((t) => t.id === 'a')).toBeDefined();

    patch.resolve(undefined);
    await inFlight;
    expect(s.isMutating).toBe(false);
  });

  it('discards a poll whose fetch overlapped a mutation that already completed (gen guard)', async () => {
    const { api } = await import('@/api/client');

    const openFetch = deferred<Ticket[]>();
    const resolvedFetch = deferred<Ticket[]>();
    (api.listTickets as ReturnType<typeof vi.fn>).mockImplementation(
      ({ resolved }: { resolved: boolean }) =>
        resolved ? resolvedFetch.promise : openFetch.promise,
    );
    (api.resolveTicket as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);

    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    // 1. Poll starts (idle); GETs in flight; generation captured.
    const poll = s.silentRefresh();

    // 2. A full mutation begins AND completes during the fetch window.
    await s.markResolved('a');
    expect(s.isMutating).toBe(false); // mutating back to 0 …
    expect(s.resolvedTickets.find((t) => t.id === 'a')).toBeDefined();

    // 3. Stale poll lands: mutating==0 now, but the generation advanced.
    openFetch.resolve([fakeTicket('a')]);
    resolvedFetch.resolve([]);
    await poll;

    // 4. The committed resolve is preserved (NOT reverted to open).
    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    expect(s.resolvedTickets.find((t) => t.id === 'a')).toBeDefined();
  });
});

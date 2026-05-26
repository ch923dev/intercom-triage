// Tickets store. Per tasks.md T031; ingest-pivot Slice C.
//
// The operator has no Intercom Access Token, so the board is served from the
// stored `tickets` table the Chrome extension ingests into (`GET /tickets`).
// An empty board means the operator hasn't synced yet — the UI surfaces the
// extension callout instead of mock data.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { BulkResult, Ticket } from '@/types/api';

interface TicketsState {
  tickets: Ticket[];
  loading: boolean;
  error: string | null;
  lastRefresh: Date | null;
  /** Optimistic local overrides waiting on the server PATCH. */
  pendingOverrides: Record<string, number>;
}

export const useTicketsStore = defineStore('tickets', () => {
  const state = ref<TicketsState>({
    tickets: [],
    loading: false,
    error: null,
    lastRefresh: null,
    pendingOverrides: {},
  });

  /** Resolved tickets list — backs both the Resolved column (cards whose
   *  `resolved_source` is `'manual'` / `'intercom_closed'`) and the
   *  Non-actionable column (cards whose `resolved_source` is `'non_actionable'`).
   *  Storage stays unified so mark/bulk/reopen rollback paths keep their
   *  single-array semantics; the two columns derive via computed getters. */
  const resolvedTickets = ref<Ticket[]>([]);

  /** Resolved tickets excluding non-actionable — feeds the Resolved column. */
  const pureResolvedTickets = computed(() =>
    resolvedTickets.value.filter((t) => t.resolved_source !== 'non_actionable'),
  );

  /** Resolved tickets whose source is `'non_actionable'` — feeds the
   *  Non-actionable column. */
  const nonActionableTickets = computed(() =>
    resolvedTickets.value.filter((t) => t.resolved_source === 'non_actionable'),
  );

  /** Active search query. Empty string means no filter. */
  const query = ref('');

  const tickets = computed(() => state.value.tickets);
  const loading = computed(() => state.value.loading);
  const lastRefresh = computed(() => state.value.lastRefresh);

  /** Subset of `state.tickets` matching the current `query`.
   *  Matches case-insensitively against title, summary, author.name, author.email.
   *  Returns the full list when the query is empty or whitespace-only. */
  const visibleTickets = computed(() => {
    const q = query.value.trim().toLowerCase();
    if (!q) return state.value.tickets;
    return state.value.tickets.filter((t) => {
      const title = (t.title ?? '').toLowerCase();
      const summary = (t.summary ?? '').toLowerCase();
      const authorName = (t.author.name ?? '').toLowerCase();
      const authorEmail = (t.author.email ?? '').toLowerCase();
      return (
        title.includes(q) ||
        summary.includes(q) ||
        authorName.includes(q) ||
        authorEmail.includes(q)
      );
    });
  });

  /** Group visible tickets by `category_id` (applying optimistic overrides).
   *  Derives from visibleTickets so search filters the board columns. */
  const byCategory = computed(() => {
    const map = new Map<number, Ticket[]>();
    for (const t of visibleTickets.value) {
      const catId = state.value.pendingOverrides[t.id] ?? t.category_id;
      if (catId === null) continue; // pending proposal — keyed by proposal_id elsewhere
      if (!map.has(catId)) map.set(catId, []);
      map.get(catId)!.push(t);
    }
    return map;
  });

  /** Derives from visibleTickets so search filters proposal columns too. */
  const byProposal = computed(() => {
    const map = new Map<number, Ticket[]>();
    for (const t of visibleTickets.value) {
      if (t.proposal_id === null) continue;
      if (!map.has(t.proposal_id)) map.set(t.proposal_id, []);
      map.get(t.proposal_id)!.push(t);
    }
    return map;
  });

  /** Every ticket keyed by id — intentionally walks the raw list, NOT
   *  visibleTickets, so flyout and follow-up lookups resolve tickets that are
   *  filtered out by the current search query. */
  const byId = computed(() => {
    const map = new Map<string, Ticket>();
    for (const t of state.value.tickets) map.set(t.id, t);
    return map;
  });

  /** Reload the stored board. Filter settings are applied server-side. */
  async function refresh() {
    state.value.loading = true;
    state.value.error = null;
    try {
      const [open, resolved] = await Promise.all([
        api.listTickets({ resolved: false }),
        api.listTickets({ resolved: true }),
      ]);
      state.value.tickets = open;
      resolvedTickets.value = resolved;
    } catch (e) {
      state.value.error = (e as Error).message;
      throw e;
    } finally {
      state.value.lastRefresh = new Date();
      state.value.loading = false;
    }
  }

  /** Silent board refresh for auto-sync polling — does NOT set loading=true so
   *  the "Loading…" banner never flickers. Error state is still updated on
   *  failure. */
  async function silentRefresh() {
    state.value.error = null;
    try {
      const [open, resolved] = await Promise.all([
        api.listTickets({ resolved: false }),
        api.listTickets({ resolved: true }),
      ]);
      state.value.tickets = open;
      resolvedTickets.value = resolved;
    } catch (e) {
      state.value.error = (e as Error).message;
    } finally {
      state.value.lastRefresh = new Date();
    }
  }

  /** Set the live search query that filters the board. */
  function setQuery(q: string) {
    query.value = q;
  }

  /** Edit the AI-supplied title / summary. Optimistic local update; rolls back
   *  on server failure. An empty string on either clears the override
   *  server-side (next sync restores the AI value). */
  async function editTicket(
    ticketId: string,
    patch: { title?: string; summary?: string },
  ) {
    const idx = state.value.tickets.findIndex((t) => t.id === ticketId);
    if (idx === -1) return;
    const prev = state.value.tickets[idx]!;
    const optimistic: Ticket = { ...prev };
    if (patch.title !== undefined) {
      const trimmed = patch.title.trim();
      optimistic.title = trimmed || prev.title;
      optimistic.title_user_edited = trimmed.length > 0;
    }
    if (patch.summary !== undefined) {
      const trimmed = patch.summary.trim();
      optimistic.summary = trimmed || '';
      optimistic.summary_user_edited = trimmed.length > 0;
    }
    state.value.tickets = [
      ...state.value.tickets.slice(0, idx),
      optimistic,
      ...state.value.tickets.slice(idx + 1),
    ];
    try {
      await api.editTicket(ticketId, patch);
    } catch (e) {
      // Roll back to the pre-edit ticket on failure.
      state.value.tickets = [
        ...state.value.tickets.slice(0, idx),
        prev,
        ...state.value.tickets.slice(idx + 1),
      ];
      throw e;
    }
  }

  /** Optimistically move ticket to resolvedTickets; rolls back on server failure. */
  async function markResolved(id: string) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    // Optimistic move
    state.value.tickets.splice(idx, 1);
    resolvedTickets.value.unshift({
      ...original,
      resolved_at: new Date().toISOString(),
      resolved_source: 'manual',
      resolution_chip_state: null,
    });
    try {
      await api.resolveTicket(id);
    } catch (e) {
      // Rollback
      resolvedTickets.value = resolvedTickets.value.filter((t) => t.id !== id);
      state.value.tickets.splice(idx, 0, original);
      throw e;
    }
  }

  /** Optimistically move ticket to resolvedTickets with non-actionable source. */
  async function markNonActionable(id: string) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    state.value.tickets.splice(idx, 1);
    resolvedTickets.value.unshift({
      ...original,
      resolved_at: new Date().toISOString(),
      resolved_source: 'non_actionable',
      resolution_chip_state: null,
    });
    try {
      await api.markNonActionable(id);
    } catch (e) {
      resolvedTickets.value = resolvedTickets.value.filter((t) => t.id !== id);
      state.value.tickets.splice(idx, 0, original);
      throw e;
    }
  }

  /** Optimistically move ticket from resolvedTickets back to open; rolls back on failure. */
  async function reopen(id: string) {
    const idx = resolvedTickets.value.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = resolvedTickets.value[idx]!;
    resolvedTickets.value.splice(idx, 1);
    state.value.tickets.unshift({
      ...original,
      resolved_at: null,
      resolved_source: null,
      resolution_chip_state: null,
    });
    try {
      await api.reopenTicket(id);
    } catch (e) {
      state.value.tickets = state.value.tickets.filter((t) => t.id !== id);
      resolvedTickets.value.splice(idx, 0, original);
      throw e;
    }
  }

  /** Set (or clear) the per-ticket AI-resolve override; reflects optimistically. */
  async function setAiResolve(id: string, enabled: boolean | null) {
    await api.setAiResolve(id, enabled);
    // Optimistically reflect the raw override in both lists; effective value
    // recomputes on next refresh.
    for (const list of [state.value.tickets, resolvedTickets.value]) {
      const t = list.find((t) => t.id === id);
      if (t) t.ai_resolve_override = enabled;
    }
  }

  /** Suppress the resolution chip until the next update_at advance. */
  async function dismissChip(id: string) {
    await api.dismissChip(id);
    for (const list of [state.value.tickets, resolvedTickets.value]) {
      const t = list.find((t) => t.id === id);
      if (t) t.resolution_chip_state = null;
    }
  }

  /** Optimistic category override; rolls back on server failure.
   *  If the ticket is currently resolved, also moves it back to open
   *  (the backend clears resolution atomically on category override). */
  async function applyOverride(ticketId: string, categoryId: number) {
    // If the ticket is in resolvedTickets, move it back to open optimistically.
    const resolvedIdx = resolvedTickets.value.findIndex((t) => t.id === ticketId);
    let movedFromResolved: Ticket | undefined;
    if (resolvedIdx !== -1) {
      movedFromResolved = resolvedTickets.value[resolvedIdx]!;
      resolvedTickets.value.splice(resolvedIdx, 1);
      state.value.tickets.unshift({
        ...movedFromResolved,
        resolved_at: null,
        resolved_source: null,
        category_id: categoryId,
        user_override: true,
      });
    }

    const previous = state.value.pendingOverrides[ticketId];
    state.value.pendingOverrides = { ...state.value.pendingOverrides, [ticketId]: categoryId };
    try {
      await api.overrideCategory(ticketId, categoryId);
    } catch (e) {
      // Roll back pending overrides.
      const next = { ...state.value.pendingOverrides };
      if (previous === undefined) delete next[ticketId];
      else next[ticketId] = previous;
      state.value.pendingOverrides = next;
      // Roll back resolved→open move if we made one.
      if (movedFromResolved !== undefined) {
        state.value.tickets = state.value.tickets.filter((t) => t.id !== ticketId);
        resolvedTickets.value.splice(resolvedIdx, 0, movedFromResolved);
      }
      throw e;
    }
  }

  // ── Bulk actions (Phase 12, plan §8d) ──────────────────────────────────────
  //
  // Pattern: snapshot affected rows → optimistic mutate → API call →
  // roll back any id reported in `failed[]` from the snapshot. Each helper
  // returns the BulkResult so the caller (BulkActionBar) can render a toast
  // with ok / failed counts.

  /** Bulk resolve — moves matching open rows into resolvedTickets. */
  async function bulkResolve(ids: string[]): Promise<BulkResult> {
    const idSet = new Set(ids);
    const snapshot: Array<{ idx: number; row: Ticket }> = [];
    const moved: Ticket[] = [];
    // Walk in reverse so splices don't invalidate indexes ahead of us.
    for (let i = state.value.tickets.length - 1; i >= 0; i--) {
      const t = state.value.tickets[i]!;
      if (!idSet.has(t.id)) continue;
      snapshot.push({ idx: i, row: t });
      state.value.tickets.splice(i, 1);
      moved.push({
        ...t,
        resolved_at: new Date().toISOString(),
        resolved_source: 'manual',
        resolution_chip_state: null,
      });
    }
    // Most-recent first — same order as `markResolved`.
    resolvedTickets.value = [...moved, ...resolvedTickets.value];

    try {
      const result = await api.bulkResolve(ids);
      _rollbackFromSnapshot(result.failed, snapshot);
      return result;
    } catch (e) {
      // Whole-batch failure — roll back every optimistic move.
      _rollbackAll(snapshot);
      throw e;
    }
  }

  /** Bulk mark non-actionable — moves matching open rows into resolvedTickets. */
  async function bulkMarkNonActionable(ids: string[]): Promise<BulkResult> {
    const idSet = new Set(ids);
    const snapshot: Array<{ idx: number; row: Ticket }> = [];
    const moved: Ticket[] = [];
    for (let i = state.value.tickets.length - 1; i >= 0; i--) {
      const t = state.value.tickets[i]!;
      if (!idSet.has(t.id)) continue;
      snapshot.push({ idx: i, row: t });
      state.value.tickets.splice(i, 1);
      moved.push({
        ...t,
        resolved_at: new Date().toISOString(),
        resolved_source: 'non_actionable',
        resolution_chip_state: null,
      });
    }
    resolvedTickets.value = [...moved, ...resolvedTickets.value];

    try {
      const result = await api.bulkMarkNonActionable(ids);
      _rollbackFromSnapshot(result.failed, snapshot);
      return result;
    } catch (e) {
      _rollbackAll(snapshot);
      throw e;
    }
  }

  /** Bulk reopen — moves matching resolved rows back to the open list. */
  async function bulkReopen(ids: string[]): Promise<BulkResult> {
    const idSet = new Set(ids);
    const snapshot: Array<{ idx: number; row: Ticket }> = [];
    const moved: Ticket[] = [];
    for (let i = resolvedTickets.value.length - 1; i >= 0; i--) {
      const t = resolvedTickets.value[i]!;
      if (!idSet.has(t.id)) continue;
      snapshot.push({ idx: i, row: t });
      resolvedTickets.value.splice(i, 1);
      moved.push({
        ...t,
        resolved_at: null,
        resolved_source: null,
        resolution_chip_state: null,
      });
    }
    state.value.tickets = [...moved, ...state.value.tickets];

    try {
      const result = await api.bulkReopen(ids);
      // Reopen rollback is the inverse direction: a failed id needs to go
      // back into resolvedTickets and out of state.value.tickets.
      for (const failure of result.failed) {
        const original = snapshot.find((s) => s.row.id === failure.id);
        if (!original) continue;
        state.value.tickets = state.value.tickets.filter((t) => t.id !== failure.id);
        resolvedTickets.value.splice(original.idx, 0, original.row);
      }
      return result;
    } catch (e) {
      // Roll every optimistic move back.
      state.value.tickets = state.value.tickets.filter((t) => !idSet.has(t.id));
      for (const { idx, row } of [...snapshot].reverse()) {
        resolvedTickets.value.splice(idx, 0, row);
      }
      throw e;
    }
  }

  /** Bulk recategorize — applies pending overrides; reopens resolved rows. */
  async function bulkRecategorize(ids: string[], categoryId: number): Promise<BulkResult> {
    const idSet = new Set(ids);

    // Snapshot prior overrides + any resolved→open moves so we can roll back.
    const overrideSnap: Record<string, number | undefined> = {};
    const resolvedMoves: Array<{ idx: number; row: Ticket }> = [];

    // Move any selected resolved tickets back to the open list optimistically.
    for (let i = resolvedTickets.value.length - 1; i >= 0; i--) {
      const t = resolvedTickets.value[i]!;
      if (!idSet.has(t.id)) continue;
      resolvedMoves.push({ idx: i, row: t });
      resolvedTickets.value.splice(i, 1);
      state.value.tickets.unshift({
        ...t,
        resolved_at: null,
        resolved_source: null,
        category_id: categoryId,
        user_override: true,
      });
    }

    const nextOverrides = { ...state.value.pendingOverrides };
    for (const id of ids) {
      overrideSnap[id] = nextOverrides[id];
      nextOverrides[id] = categoryId;
    }
    state.value.pendingOverrides = nextOverrides;

    try {
      const result = await api.bulkRecategorize(ids, categoryId);
      // Roll back per-id failures.
      if (result.failed.length > 0) {
        const failedSet = new Set(result.failed.map((f) => f.id));
        const reverted = { ...state.value.pendingOverrides };
        for (const id of failedSet) {
          const prev = overrideSnap[id];
          if (prev === undefined) delete reverted[id];
          else reverted[id] = prev;
        }
        state.value.pendingOverrides = reverted;
        // Restore any resolved-row moves whose ids failed.
        for (const { idx, row } of resolvedMoves) {
          if (!failedSet.has(row.id)) continue;
          state.value.tickets = state.value.tickets.filter((t) => t.id !== row.id);
          resolvedTickets.value.splice(idx, 0, row);
        }
      }
      return result;
    } catch (e) {
      // Whole-batch failure — restore every snapshot.
      const reverted = { ...state.value.pendingOverrides };
      for (const id of ids) {
        const prev = overrideSnap[id];
        if (prev === undefined) delete reverted[id];
        else reverted[id] = prev;
      }
      state.value.pendingOverrides = reverted;
      state.value.tickets = state.value.tickets.filter((t) => !idSet.has(t.id));
      for (const { idx, row } of [...resolvedMoves].reverse()) {
        resolvedTickets.value.splice(idx, 0, row);
      }
      throw e;
    }
  }

  /** Bulk dismiss chip — clears `resolution_chip_state` locally for ok ids. */
  async function bulkDismissChip(ids: string[]): Promise<BulkResult> {
    const result = await api.bulkDismissChip(ids);
    const okSet = new Set(result.ok_ids);
    for (const list of [state.value.tickets, resolvedTickets.value]) {
      for (const t of list) {
        if (okSet.has(t.id)) t.resolution_chip_state = null;
      }
    }
    return result;
  }

  /** Roll back from a snapshot — reinsert each row into state.value.tickets
   *  at its original index and prune it from resolvedTickets. Used by
   *  bulkResolve when per-id `failed[]` is non-empty. */
  function _rollbackFromSnapshot(
    failures: { id: string; reason: string }[],
    snapshot: Array<{ idx: number; row: Ticket }>,
  ): void {
    const failedSet = new Set(failures.map((f) => f.id));
    // Reverse so smaller indexes go in last and don't shift later ones.
    for (const { idx, row } of [...snapshot].reverse()) {
      if (!failedSet.has(row.id)) continue;
      resolvedTickets.value = resolvedTickets.value.filter((t) => t.id !== row.id);
      state.value.tickets.splice(idx, 0, row);
    }
  }

  function _rollbackAll(snapshot: Array<{ idx: number; row: Ticket }>): void {
    const allIds = new Set(snapshot.map((s) => s.row.id));
    resolvedTickets.value = resolvedTickets.value.filter((t) => !allIds.has(t.id));
    for (const { idx, row } of [...snapshot].reverse()) {
      state.value.tickets.splice(idx, 0, row);
    }
  }

  return {
    tickets,
    loading,
    lastRefresh,
    query,
    visibleTickets,
    byCategory,
    byProposal,
    byId,
    refresh,
    silentRefresh,
    setQuery,
    applyOverride,
    editTicket,
    isEmpty: computed(() => !state.value.loading && state.value.tickets.length === 0),
    pendingOverrides: computed(() => state.value.pendingOverrides),
    // Resolution
    resolvedTickets,
    pureResolvedTickets,
    nonActionableTickets,
    markResolved,
    markNonActionable,
    reopen,
    setAiResolve,
    dismissChip,
    // Bulk (Phase 12)
    bulkResolve,
    bulkMarkNonActionable,
    bulkReopen,
    bulkRecategorize,
    bulkDismissChip,
  };
});

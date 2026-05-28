// Tickets store. Per tasks.md T031; ingest-pivot Slice C.
//
// The operator has no Intercom Access Token, so the board is served from the
// stored `tickets` table the Chrome extension ingests into (`GET /tickets`).
// An empty board means the operator hasn't synced yet — the UI surfaces the
// extension callout instead of mock data.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { BulkResult, ParkedReason, Ticket } from '@/types/api';
import { needsReview } from '@/utils/review';
import {
  cloneFilter,
  EMPTY_FILTER,
  isEmptyFilter,
  ticketMatchesFilter,
  type SavedFilter,
} from '@/utils/savedViews';

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
   *  `resolved_source` is `'manual'` / `'intercom_closed'` / `'ai_resolved'`) and
   *  the Non-actionable column (cards whose `resolved_source` is `'non_actionable'`).
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

  /** Active saved-view / smart filter (roadmap 1.1). The ad-hoc facet filter
   *  the board reacts to — layered ON TOP of the server-side lookback/state
   *  filter and the live `query`. `EMPTY_FILTER` (every facet inactive) is the
   *  pass-through default. Named presets live in the `savedViews` store and
   *  drive this via `setFilter`. */
  const activeFilter = ref<SavedFilter>(cloneFilter(EMPTY_FILTER));

  /** True when the active filter narrows anything (drives a "filtered" badge). */
  const isFilterActive = computed(() => !isEmptyFilter(activeFilter.value));

  /** Count of optimistic mutations currently awaiting their server call. While
   *  this is > 0 the board holds optimistic state the server doesn't yet
   *  reflect, so `silentRefresh` must not overwrite it (auto-sync race). Each
   *  mutating action increments on entry and decrements in `finally`. */
  const mutating = ref(0);

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

  /** Effective category for a ticket — optimistic override beats AI/stored
   *  value (mirrors the byCategory grouping + invariant #13 "override beats
   *  AI"). Shared by the column grouping and the saved-view category facet. */
  function effectiveCategoryId(t: Ticket): number | null {
    return state.value.pendingOverrides[t.id] ?? t.category_id;
  }

  /** Effective override state — true when the operator has confirmed the
   *  category, folding in any optimistic pending override so a just-confirmed
   *  ticket drops out of the needs-review lane before the server round-trips
   *  (mirrors effectiveCategoryId). */
  function effectiveOverridden(t: Ticket): boolean {
    return t.id in state.value.pendingOverrides || t.user_override;
  }

  /** Needs-review lane (roadmap 2.3). OPEN, non-overridden tickets whose
   *  categorization self-confidence is below the threshold — a derived
   *  view-layer split over `ai_confidence`, NOT a stored state (mirrors the
   *  non-actionable column, invariant #10). Confirming a ticket (writing an
   *  override) flips `effectiveOverridden` and removes it from the lane. Walks
   *  the raw open list so the count is stable regardless of the active search /
   *  saved-view filter. */
  const needsReviewTickets = computed(() =>
    state.value.tickets.filter(
      (t) => t.parked_at === null && needsReview(t, effectiveOverridden(t)),
    ),
  );

  /** When true, the board narrows every category column to needs-review tickets
   *  (roadmap 2.3). A board-level lane toggle, layered on top of search + the
   *  saved-view filter. Toggled from the Topbar. */
  const reviewOnly = ref(false);
  function setReviewOnly(v: boolean) {
    reviewOnly.value = v;
  }
  function toggleReviewOnly() {
    reviewOnly.value = !reviewOnly.value;
  }

  /** When true, the board narrows to PARKED tickets (roadmap 4.1, Layout B).
   *  A board-level toggle like `reviewOnly`, driven by the Topbar parked chip. */
  const parkedOnly = ref(false);
  function setParkedOnly(v: boolean) {
    parkedOnly.value = v;
  }
  function toggleParkedOnly() {
    parkedOnly.value = !parkedOnly.value;
  }

  /** Open tickets currently parked (parked_at set). Parked rows ride in the
   *  open list (resolved_at is null), so this is a straight filter. */
  const parkedTickets = computed(() => state.value.tickets.filter((t) => t.parked_at !== null));

  /** Count of parked tickets whose wake time has passed ("ready to resume"). */
  const readyParkedCount = computed(() => {
    const now = Date.now();
    return parkedTickets.value.filter(
      (t) => t.parked_until !== null && Date.parse(t.parked_until) <= now,
    ).length;
  });

  /** `visibleTickets` further narrowed by the active saved-view filter
   *  (roadmap 1.1). Pass-through when no facet is active. A single `Date.now()`
   *  is sampled per recompute so every card in one pass shares an age clock. */
  const facetVisibleTickets = computed(() => {
    let base = visibleTickets.value;
    if (reviewOnly.value) base = base.filter((t) => needsReview(t, effectiveOverridden(t)));
    // Layout B: parked tickets leave the category columns. The parked chip flips
    // `parkedOnly` to show ONLY parked; otherwise parked rows are hidden.
    base = parkedOnly.value
      ? base.filter((t) => t.parked_at !== null)
      : base.filter((t) => t.parked_at === null);
    if (!isFilterActive.value) return base;
    const now = Date.now();
    return base.filter((t) =>
      ticketMatchesFilter(t, activeFilter.value, effectiveCategoryId(t), now),
    );
  });

  /** Group facet-filtered visible tickets by `category_id` (applying optimistic
   *  overrides). Derives from facetVisibleTickets so search AND the active
   *  saved-view filter both narrow the board columns. */
  const byCategory = computed(() => {
    const map = new Map<number, Ticket[]>();
    for (const t of facetVisibleTickets.value) {
      const catId = effectiveCategoryId(t);
      if (catId === null) continue; // pending proposal — keyed by proposal_id elsewhere
      if (!map.has(catId)) map.set(catId, []);
      map.get(catId)!.push(t);
    }
    return map;
  });

  /** Derives from facetVisibleTickets so search + saved-view filter the
   *  proposal columns too. */
  const byProposal = computed(() => {
    const map = new Map<number, Ticket[]>();
    for (const t of facetVisibleTickets.value) {
      if (t.proposal_id === null) continue;
      if (!map.has(t.proposal_id)) map.set(t.proposal_id, []);
      map.get(t.proposal_id)!.push(t);
    }
    return map;
  });

  /** Resolved column list with the active saved-view filter applied (roadmap
   *  1.1). The resolution facet decides whether resolved buckets show at all;
   *  the category/urgency/age facets narrow within. Pass-through when no facet
   *  is active. (Resolved lists intentionally ignore the live search `query`,
   *  preserving the pre-1.1 behavior of the Resolved/Non-actionable columns.) */
  const filteredPureResolvedTickets = computed(() => {
    if (!isFilterActive.value) return pureResolvedTickets.value;
    const now = Date.now();
    return pureResolvedTickets.value.filter((t) =>
      ticketMatchesFilter(t, activeFilter.value, effectiveCategoryId(t), now),
    );
  });

  const filteredNonActionableTickets = computed(() => {
    if (!isFilterActive.value) return nonActionableTickets.value;
    const now = Date.now();
    return nonActionableTickets.value.filter((t) =>
      ticketMatchesFilter(t, activeFilter.value, effectiveCategoryId(t), now),
    );
  });

  /** Every ticket keyed by id — intentionally walks the raw list, NOT
   *  visibleTickets, so flyout and follow-up lookups resolve tickets that are
   *  filtered out by the current search query. */
  const byId = computed(() => {
    const map = new Map<string, Ticket>();
    for (const t of state.value.tickets) map.set(t.id, t);
    return map;
  });

  /** Drop pending overrides the freshly-fetched server data already reflects.
   *  Without this, a successfully-applied override lingers in `pendingOverrides`
   *  forever (slow staleness/memory leak across a session). */
  function _reconcilePendingOverrides() {
    const next = { ...state.value.pendingOverrides };
    let changed = false;
    for (const t of [...state.value.tickets, ...resolvedTickets.value]) {
      if (t.id in next && next[t.id] === t.category_id) {
        delete next[t.id];
        changed = true;
      }
    }
    if (changed) state.value.pendingOverrides = next;
  }

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
      _reconcilePendingOverrides();
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
   *  failure. Skips entirely while a manual refresh or an optimistic mutation
   *  is in flight: a wholesale list replacement mid-mutation would clobber the
   *  optimistic state and corrupt index-based rollback. */
  async function silentRefresh() {
    if (state.value.loading || mutating.value > 0) return;
    state.value.error = null;
    try {
      const [open, resolved] = await Promise.all([
        api.listTickets({ resolved: false }),
        api.listTickets({ resolved: true }),
      ]);
      state.value.tickets = open;
      resolvedTickets.value = resolved;
      _reconcilePendingOverrides();
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

  /** Set the active saved-view / smart filter (roadmap 1.1). Stores a defensive
   *  copy so the caller's object can mutate without leaking into the board. */
  function setFilter(filter: SavedFilter) {
    activeFilter.value = cloneFilter(filter);
  }

  /** Clear the active saved-view filter back to the pass-through default. */
  function clearFilter() {
    activeFilter.value = cloneFilter(EMPTY_FILTER);
  }

  /** Edit the AI-supplied title / summary. Optimistic local update; rolls back
   *  on server failure. An empty string on either clears the override
   *  server-side (next sync restores the AI value). The flyout can display a
   *  resolved ticket, so search both lists — otherwise editing a resolved
   *  ticket's title silently no-ops. */
  async function editTicket(ticketId: string, patch: { title?: string; summary?: string }) {
    const openIdx = state.value.tickets.findIndex((t) => t.id === ticketId);
    const list = openIdx !== -1 ? 'open' : 'resolved';
    const target = openIdx !== -1 ? state.value.tickets : resolvedTickets.value;
    const idx = openIdx !== -1 ? openIdx : target.findIndex((t) => t.id === ticketId);
    if (idx === -1) return;
    const prev = target[idx]!;
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
    const writeAt = (row: Ticket) => {
      const next = [...target.slice(0, idx), row, ...target.slice(idx + 1)];
      if (list === 'open') state.value.tickets = next;
      else resolvedTickets.value = next;
    };
    mutating.value++;
    writeAt(optimistic);
    try {
      await api.editTicket(ticketId, patch);
    } catch (e) {
      writeAt(prev); // roll back to the pre-edit ticket
      throw e;
    } finally {
      mutating.value--;
    }
  }

  /** Optimistically move ticket to resolvedTickets; rolls back on server failure. */
  async function markResolved(id: string) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    // Optimistic move
    mutating.value++;
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
    } finally {
      mutating.value--;
    }
  }

  /** Optimistically move ticket to resolvedTickets with non-actionable source. */
  async function markNonActionable(id: string) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    mutating.value++;
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
    } finally {
      mutating.value--;
    }
  }

  /** Optimistically move ticket from resolvedTickets back to open; rolls back on failure. */
  async function reopen(id: string) {
    const idx = resolvedTickets.value.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = resolvedTickets.value[idx]!;
    mutating.value++;
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
    } finally {
      mutating.value--;
    }
  }

  /** Park a ticket in place (it stays in the open list, drops out of columns).
   *  Optimistic; rolls back on server failure. */
  async function parkTicket(
    id: string,
    untilAt: string,
    reason: ParkedReason,
    note: string | null = null,
  ) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    mutating.value++;
    state.value.tickets.splice(idx, 1, {
      ...original,
      parked_at: new Date().toISOString(),
      parked_until: untilAt,
      parked_reason: reason,
      parked_note: note,
    });
    try {
      await api.parkTicket(id, untilAt, reason, note);
    } catch (e) {
      state.value.tickets.splice(idx, 1, original);
      throw e;
    } finally {
      mutating.value--;
    }
  }

  /** Clear a ticket's parked state in place; rolls back on failure. */
  async function unparkTicket(id: string) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    mutating.value++;
    state.value.tickets.splice(idx, 1, {
      ...original,
      parked_at: null,
      parked_until: null,
      parked_reason: null,
      parked_note: null,
    });
    try {
      await api.unparkTicket(id);
    } catch (e) {
      state.value.tickets.splice(idx, 1, original);
      throw e;
    } finally {
      mutating.value--;
    }
  }

  /** Set (or clear) the per-ticket AI-resolve override; reflects optimistically. */
  async function setAiResolve(id: string, enabled: boolean | null) {
    mutating.value++;
    try {
      await api.setAiResolve(id, enabled);
      // Optimistically reflect the raw override in both lists; effective value
      // recomputes on next refresh.
      for (const list of [state.value.tickets, resolvedTickets.value]) {
        const t = list.find((t) => t.id === id);
        if (t) t.ai_resolve_override = enabled;
      }
    } finally {
      mutating.value--;
    }
  }

  /** Suppress the resolution chip until the next update_at advance. */
  async function dismissChip(id: string) {
    mutating.value++;
    try {
      await api.dismissChip(id);
      for (const list of [state.value.tickets, resolvedTickets.value]) {
        const t = list.find((t) => t.id === id);
        if (t) t.resolution_chip_state = null;
      }
    } finally {
      mutating.value--;
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
    mutating.value++;
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
    } finally {
      mutating.value--;
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
    mutating.value++;
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
    } finally {
      mutating.value--;
    }
  }

  /** Bulk mark non-actionable — moves matching open rows into resolvedTickets. */
  async function bulkMarkNonActionable(ids: string[]): Promise<BulkResult> {
    const idSet = new Set(ids);
    const snapshot: Array<{ idx: number; row: Ticket }> = [];
    const moved: Ticket[] = [];
    mutating.value++;
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
    } finally {
      mutating.value--;
    }
  }

  /** Bulk reopen — moves matching resolved rows back to the open list. */
  async function bulkReopen(ids: string[]): Promise<BulkResult> {
    const idSet = new Set(ids);
    const snapshot: Array<{ idx: number; row: Ticket }> = [];
    const moved: Ticket[] = [];
    mutating.value++;
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
      // Reopen rollback is the inverse direction: a failed id goes back into
      // resolvedTickets and out of state.value.tickets. Restore in ascending
      // original-index order (the snapshot is descending — reverse it) so the
      // splices land at the right slots, matching `_rollbackFromSnapshot`.
      const failedSet = new Set(result.failed.map((f) => f.id));
      state.value.tickets = state.value.tickets.filter((t) => !failedSet.has(t.id));
      for (const { idx, row } of [...snapshot].reverse()) {
        if (!failedSet.has(row.id)) continue;
        resolvedTickets.value.splice(idx, 0, row);
      }
      return result;
    } catch (e) {
      // Roll every optimistic move back.
      state.value.tickets = state.value.tickets.filter((t) => !idSet.has(t.id));
      for (const { idx, row } of [...snapshot].reverse()) {
        resolvedTickets.value.splice(idx, 0, row);
      }
      throw e;
    } finally {
      mutating.value--;
    }
  }

  /** Bulk recategorize — applies pending overrides; reopens resolved rows. */
  async function bulkRecategorize(ids: string[], categoryId: number): Promise<BulkResult> {
    const idSet = new Set(ids);

    // Snapshot prior overrides + any resolved→open moves so we can roll back.
    const overrideSnap: Record<string, number | undefined> = {};
    const resolvedMoves: Array<{ idx: number; row: Ticket }> = [];

    mutating.value++;
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
    } finally {
      mutating.value--;
    }
  }

  /** Bulk dismiss chip — clears `resolution_chip_state` locally for ok ids. */
  async function bulkDismissChip(ids: string[]): Promise<BulkResult> {
    mutating.value++;
    try {
      const result = await api.bulkDismissChip(ids);
      const okSet = new Set(result.ok_ids);
      for (const list of [state.value.tickets, resolvedTickets.value]) {
        for (const t of list) {
          if (okSet.has(t.id)) t.resolution_chip_state = null;
        }
      }
      return result;
    } finally {
      mutating.value--;
    }
  }

  /** Bulk park — sets the trio on every ok id the server confirms. */
  async function bulkPark(
    ids: string[],
    untilAt: string,
    reason: ParkedReason,
    note: string | null = null,
  ): Promise<BulkResult> {
    mutating.value++;
    try {
      const result = await api.bulkPark(ids, untilAt, reason, note);
      const okSet = new Set(result.ok_ids);
      const stamped = new Date().toISOString();
      for (const t of state.value.tickets) {
        if (okSet.has(t.id)) {
          t.parked_at = stamped;
          t.parked_until = untilAt;
          t.parked_reason = reason;
          t.parked_note = note;
        }
      }
      return result;
    } finally {
      mutating.value--;
    }
  }

  /** Bulk unpark — clears the trio on every ok id. */
  async function bulkUnpark(ids: string[]): Promise<BulkResult> {
    mutating.value++;
    try {
      const result = await api.bulkUnpark(ids);
      const okSet = new Set(result.ok_ids);
      for (const t of state.value.tickets) {
        if (okSet.has(t.id)) {
          t.parked_at = null;
          t.parked_until = null;
          t.parked_reason = null;
          t.parked_note = null;
        }
      }
      return result;
    } finally {
      mutating.value--;
    }
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
    facetVisibleTickets,
    byCategory,
    byProposal,
    byId,
    refresh,
    silentRefresh,
    setQuery,
    // Saved views / smart filters (roadmap 1.1)
    activeFilter,
    isFilterActive,
    setFilter,
    clearFilter,
    filteredPureResolvedTickets,
    filteredNonActionableTickets,
    // Needs-review lane (roadmap 2.3)
    needsReviewTickets,
    reviewOnly,
    setReviewOnly,
    toggleReviewOnly,
    applyOverride,
    editTicket,
    isEmpty: computed(() => !state.value.loading && state.value.tickets.length === 0),
    isMutating: computed(() => mutating.value > 0),
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
    // Parked / snoozed (roadmap 4.1)
    parkedTickets,
    readyParkedCount,
    parkedOnly,
    setParkedOnly,
    toggleParkedOnly,
    parkTicket,
    unparkTicket,
    bulkPark,
    bulkUnpark,
  };
});

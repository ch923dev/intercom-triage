// Tickets store. Per tasks.md T031; ingest-pivot Slice C.
//
// The operator has no Intercom Access Token, so the board is served from the
// stored `tickets` table the Chrome extension ingests into (`GET /tickets`).
// An empty board means the operator hasn't synced yet — the UI surfaces the
// extension callout instead of mock data.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { Ticket } from '@/types/api';

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

  /** Active search query. Empty string means no filter. */
  const query = ref('');

  const tickets = computed(() => state.value.tickets);
  const loading = computed(() => state.value.loading);
  const error = computed(() => state.value.error);
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
      state.value.tickets = await api.listTickets();
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
      state.value.tickets = await api.listTickets();
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

  /** Optimistic category override; rolls back on server failure. */
  async function applyOverride(ticketId: string, categoryId: number) {
    const previous = state.value.pendingOverrides[ticketId];
    state.value.pendingOverrides = { ...state.value.pendingOverrides, [ticketId]: categoryId };
    try {
      await api.overrideCategory(ticketId, categoryId);
    } catch (e) {
      // Roll back.
      const next = { ...state.value.pendingOverrides };
      if (previous === undefined) delete next[ticketId];
      else next[ticketId] = previous;
      state.value.pendingOverrides = next;
      throw e;
    }
  }

  return {
    tickets,
    loading,
    error,
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
  };
});

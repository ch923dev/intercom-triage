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

  const tickets = computed(() => state.value.tickets);
  const loading = computed(() => state.value.loading);
  const error = computed(() => state.value.error);
  const lastRefresh = computed(() => state.value.lastRefresh);

  /** Group visible tickets by `category_id` (applying optimistic overrides). */
  const byCategory = computed(() => {
    const map = new Map<number, Ticket[]>();
    for (const t of state.value.tickets) {
      const catId = state.value.pendingOverrides[t.id] ?? t.category_id;
      if (catId === null) continue; // pending proposal — keyed by proposal_id elsewhere
      if (!map.has(catId)) map.set(catId, []);
      map.get(catId)!.push(t);
    }
    return map;
  });

  const byProposal = computed(() => {
    const map = new Map<number, Ticket[]>();
    for (const t of state.value.tickets) {
      if (t.proposal_id === null) continue;
      if (!map.has(t.proposal_id)) map.set(t.proposal_id, []);
      map.get(t.proposal_id)!.push(t);
    }
    return map;
  });

  /** Every visible ticket keyed by id — for O(1) lookup by id. */
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
    byCategory,
    byProposal,
    byId,
    refresh,
    applyOverride,
    editTicket,
    isEmpty: computed(() => !state.value.loading && state.value.tickets.length === 0),
    pendingOverrides: computed(() => state.value.pendingOverrides),
  };
});

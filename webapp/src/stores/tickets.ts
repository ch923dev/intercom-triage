// Tickets store. Per tasks.md T031.
// Real /tickets/fetch lands in T025; for the scaffold the store carries a
// `mock` mode that loads the design's sample data so the UI can be developed
// against realistic shapes before the backend route exists.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api, ApiError } from '@/api/client';
import { SAMPLE_TICKETS } from '@/mock/sampleTickets';
import type { FilterSettings, Ticket } from '@/types/api';

interface TicketsState {
  tickets: Ticket[];
  loading: boolean;
  error: string | null;
  lastRefresh: Date | null;
  /** Optimistic local overrides waiting on the server PATCH. */
  pendingOverrides: Record<string, number>;
  /** Set true when the live endpoint isn't wired yet. */
  mock: boolean;
}

export const useTicketsStore = defineStore('tickets', () => {
  const state = ref<TicketsState>({
    tickets: [],
    loading: false,
    error: null,
    lastRefresh: null,
    pendingOverrides: {},
    mock: false,
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

  async function refresh(filter: FilterSettings) {
    state.value.loading = true;
    state.value.error = null;
    try {
      const data = await api.fetchTickets(filter);
      state.value.tickets = data;
      state.value.mock = false;
    } catch (e) {
      // Backend `/tickets/fetch` isn't merged yet (T025). Fall back to the
      // sample-data shipped with the design so the UI is workable.
      if (e instanceof ApiError && e.status === 404) {
        state.value.tickets = SAMPLE_TICKETS;
        state.value.mock = true;
      } else {
        state.value.error = (e as Error).message;
        throw e;
      }
    } finally {
      state.value.lastRefresh = new Date();
      state.value.loading = false;
    }
  }

  /** Optimistic category override; rolls back on server failure. */
  async function applyOverride(ticketId: string, categoryId: number) {
    const previous = state.value.pendingOverrides[ticketId];
    state.value.pendingOverrides = { ...state.value.pendingOverrides, [ticketId]: categoryId };
    if (state.value.mock) return; // no server in mock mode
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
    refresh,
    applyOverride,
    isMock: computed(() => state.value.mock),
    pendingOverrides: computed(() => state.value.pendingOverrides),
  };
});

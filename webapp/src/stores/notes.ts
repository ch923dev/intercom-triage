// Per-ticket next-step notes store. Reference: tasks.md T052, plan §8a.
// Seeded from `GET /notes`; the flyout writes through `setNote` (debounced by
// the component). An empty body deletes the row server-side.

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { TicketNote } from '@/types/api';

/** Count of non-empty lines — drives the card's `Notes (N)` chip. */
export function countNoteLines(body: string | null | undefined): number {
  if (!body) return 0;
  return body.split('\n').filter((line) => line.trim().length > 0).length;
}

export const useNotesStore = defineStore('notes', () => {
  /** ticket_id → note record. */
  const map = ref<Record<string, TicketNote>>({});

  function bodyOf(ticketId: string): string {
    return map.value[ticketId]?.body ?? '';
  }

  /** Load every stored note. Falls back to empty on a backend error. */
  async function load() {
    try {
      const rows = await api.listNotes();
      map.value = Object.fromEntries(rows.map((r) => [r.ticket_id, r]));
    } catch {
      map.value = {};
    }
  }

  /** Persist a note. An empty body deletes the row. */
  async function setNote(ticketId: string, body: string) {
    const result = await api.putNote(ticketId, body);
    if ('deleted' in result) {
      const next = { ...map.value };
      delete next[ticketId];
      map.value = next;
    } else {
      map.value = { ...map.value, [ticketId]: result };
    }
  }

  return { bodyOf, load, setNote };
});

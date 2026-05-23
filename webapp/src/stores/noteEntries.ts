// Time-tabled notes store. Spec:
// docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md
//
// Append-only per-ticket investigation log. `load()` seeds from
// `GET /notes/entries`; `addEntry` is optimistic and replaces the temp row
// with the server-issued id on success. The matching follow-up upsert
// happens server-side inside the same transaction — this store does not
// touch the followups store. The flyout reads the active followup directly
// from `useFollowupsStore` so the bucket-board view stays consistent.

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { NoteEntry } from '@/types/api';

export const useNoteEntriesStore = defineStore('noteEntries', () => {
  /** ticket_id → asc-by-created_at array of non-deleted entries. */
  const map = ref<Record<string, NoteEntry[]>>({});

  /** Monotonically decreasing temp id for optimistic rows; replaced on save. */
  let nextTempId = -1;

  function entriesOf(ticketId: string): NoteEntry[] {
    return map.value[ticketId] ?? [];
  }

  function countOf(ticketId: string): number {
    return entriesOf(ticketId).length;
  }

  async function load() {
    try {
      const rows = await api.listNoteEntries();
      const grouped: Record<string, NoteEntry[]> = {};
      for (const r of rows) {
        (grouped[r.ticket_id] ??= []).push(r);
      }
      map.value = grouped;
    } catch {
      map.value = {};
    }
  }

  async function addEntry(
    ticketId: string,
    body: string,
    timerMin: number | null = null,
    reason: string | null = null,
  ): Promise<NoteEntry> {
    const tempId = nextTempId--;
    const optimistic: NoteEntry = {
      id: tempId,
      ticket_id: ticketId,
      body,
      timer_min: timerMin,
      reason,
      created_at: new Date().toISOString(),
    };
    const prior = entriesOf(ticketId);
    map.value = { ...map.value, [ticketId]: [...prior, optimistic] };

    try {
      const saved = await api.addNoteEntry({
        ticket_id: ticketId,
        body,
        timer_min: timerMin,
        reason,
      });
      const replaced = entriesOf(ticketId).map((e) => (e.id === tempId ? saved : e));
      map.value = { ...map.value, [ticketId]: replaced };
      return saved;
    } catch (e) {
      const reverted = entriesOf(ticketId).filter((x) => x.id !== tempId);
      map.value = { ...map.value, [ticketId]: reverted };
      throw e;
    }
  }

  async function deleteEntry(entryId: number): Promise<void> {
    // Locate the row across all tickets — entry ids are unique server-side.
    let ticketId: string | null = null;
    let snapshot: NoteEntry[] | null = null;
    for (const [tid, list] of Object.entries(map.value)) {
      if (list.some((e) => e.id === entryId)) {
        ticketId = tid;
        snapshot = list;
        break;
      }
    }
    if (ticketId === null || snapshot === null) return;

    map.value = {
      ...map.value,
      [ticketId]: snapshot.filter((e) => e.id !== entryId),
    };

    try {
      await api.deleteNoteEntry(entryId);
    } catch (e) {
      map.value = { ...map.value, [ticketId]: snapshot };
      throw e;
    }
  }

  return { entriesOf, countOf, load, addEntry, deleteEntry };
});

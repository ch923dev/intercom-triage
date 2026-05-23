// Note attachments store. Spec:
// docs/superpowers/specs/2026-05-23-note-attachments-design.md
//
// Lazy load per ticket — `load(ticketId)` is no-op after the first call for a
// given ticket. Uploads are optimistic with a negative temp id; the server-issued
// row replaces it on resolve, or it is dropped on rejection. Removes are
// optimistic too.

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { NoteAttachment } from '@/types/api';

export const useAttachmentsStore = defineStore('attachments', () => {
  /** ticket_id → list of attachments (both owner_kinds). */
  const map = ref<Record<string, NoteAttachment[]>>({});
  /** Tickets that have completed a successful load — used to dedupe load() calls. */
  const loadedTickets = ref<Set<string>>(new Set());

  let nextTempId = -1;

  function byTicket(ticketId: string): NoteAttachment[] {
    return (map.value[ticketId] ?? []).filter((a) => a.owner_kind === 'ticket');
  }

  function byEntry(entryId: number): NoteAttachment[] {
    const sId = String(entryId);
    return Object.values(map.value)
      .flat()
      .filter((a) => a.owner_kind === 'entry' && a.owner_id === sId);
  }

  function _appendTo(ticketId: string, row: NoteAttachment): void {
    const prior = map.value[ticketId] ?? [];
    map.value = { ...map.value, [ticketId]: [...prior, row] };
  }

  function _removeFrom(ticketId: string, attachmentId: number): NoteAttachment | undefined {
    const prior = map.value[ticketId] ?? [];
    const removed = prior.find((a) => a.id === attachmentId);
    map.value = { ...map.value, [ticketId]: prior.filter((a) => a.id !== attachmentId) };
    return removed;
  }

  async function load(ticketId: string): Promise<void> {
    if (loadedTickets.value.has(ticketId)) return;
    try {
      const rows = await api.listAttachments(ticketId);
      map.value = { ...map.value, [ticketId]: rows };
      loadedTickets.value = new Set([...loadedTickets.value, ticketId]);
    } catch {
      // leave the map untouched; caller can retry on next flyout open.
    }
  }

  async function upload(
    file: File,
    ownerKind: 'entry' | 'ticket',
    ownerId: string,
    ticketId: string,
  ): Promise<NoteAttachment> {
    const tempId = nextTempId--;
    const optimistic: NoteAttachment = {
      id: tempId,
      owner_kind: ownerKind,
      owner_id: ownerId,
      ticket_id: ticketId,
      filename: file.name,
      mime: file.type || 'application/octet-stream',
      size_bytes: file.size,
      created_at: new Date().toISOString(),
      raw_url: '',
      thumb_url: null,
    };
    _appendTo(ticketId, optimistic);

    try {
      const saved = await api.uploadAttachment(file, ownerKind, ownerId, ticketId);
      const next = (map.value[ticketId] ?? []).map((a) => (a.id === tempId ? saved : a));
      map.value = { ...map.value, [ticketId]: next };
      return saved;
    } catch (e) {
      _removeFrom(ticketId, tempId);
      throw e;
    }
  }

  async function remove(attachmentId: number): Promise<void> {
    // Locate the row across all tickets — ids are unique server-side.
    let ticketId: string | null = null;
    for (const [tid, list] of Object.entries(map.value)) {
      if (list.some((a) => a.id === attachmentId)) {
        ticketId = tid;
        break;
      }
    }
    if (ticketId === null) return;
    const snapshot = map.value[ticketId];
    const removed = _removeFrom(ticketId, attachmentId);
    if (removed === undefined) return;
    try {
      await api.deleteAttachment(attachmentId);
    } catch (e) {
      map.value = { ...map.value, [ticketId]: snapshot };
      throw e;
    }
  }

  return { byTicket, byEntry, load, upload, remove };
});

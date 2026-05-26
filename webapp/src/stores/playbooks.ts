// Playbooks store. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md
//
// Reusable next-steps recipes scoped to a category. `ensureForCategory` lazily
// fetches a category's active playbooks once and caches them; the flyout and
// the library page read from the same `byCategory` map. The library also loads
// archived rows into `archivedByCategory` for the restore view. Mutations are
// optimistic with rollback, matching the tickets/noteEntries stores.

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { Playbook } from '@/types/api';

export const usePlaybooksStore = defineStore('playbooks', () => {
  /** category_id → active playbooks (asc by created_at). */
  const byCategory = ref<Record<number, Playbook[]>>({});
  /** category_id → archived playbooks (only populated by `loadAll(true)`). */
  const archivedByCategory = ref<Record<number, Playbook[]>>({});
  const loaded = ref<Set<number>>(new Set());

  function forCategory(categoryId: number): Playbook[] {
    return byCategory.value[categoryId] ?? [];
  }

  function archivedFor(categoryId: number): Playbook[] {
    return archivedByCategory.value[categoryId] ?? [];
  }

  async function ensureForCategory(categoryId: number): Promise<void> {
    if (loaded.value.has(categoryId)) return;
    const rows = await api.listPlaybooks({ categoryId });
    byCategory.value = { ...byCategory.value, [categoryId]: rows };
    loaded.value = new Set(loaded.value).add(categoryId);
  }

  async function loadAll(includeArchived = false): Promise<void> {
    const rows = await api.listPlaybooks(includeArchived ? { includeArchived: true } : {});
    const active: Record<number, Playbook[]> = {};
    const archived: Record<number, Playbook[]> = {};
    const seen = new Set<number>();
    for (const r of rows) {
      if (r.archived_at === null) (active[r.category_id] ??= []).push(r);
      else (archived[r.category_id] ??= []).push(r);
      seen.add(r.category_id);
    }
    byCategory.value = active;
    archivedByCategory.value = archived;
    loaded.value = seen;
  }

  async function create(body: {
    category_id: number;
    label: string;
    body: string;
    source_ticket_id?: string | null;
  }): Promise<Playbook> {
    const saved = await api.createPlaybook(body);
    const prior = forCategory(saved.category_id);
    byCategory.value = { ...byCategory.value, [saved.category_id]: [...prior, saved] };
    return saved;
  }

  async function update(id: number, body: { label?: string; body?: string }): Promise<void> {
    const saved = await api.updatePlaybook(id, body);
    const prior = forCategory(saved.category_id);
    byCategory.value = {
      ...byCategory.value,
      [saved.category_id]: prior.map((p) => (p.id === id ? saved : p)),
    };
  }

  async function archive(id: number): Promise<void> {
    const bucket = findBucket(byCategory.value, id);
    if (bucket === null) return;
    const { categoryId, snapshot, row } = bucket;
    byCategory.value = { ...byCategory.value, [categoryId]: snapshot.filter((p) => p.id !== id) };
    try {
      await api.archivePlaybook(id);
      const archived = { ...row, archived_at: new Date().toISOString() };
      archivedByCategory.value = {
        ...archivedByCategory.value,
        [categoryId]: [...archivedFor(categoryId), archived],
      };
    } catch (e) {
      byCategory.value = { ...byCategory.value, [categoryId]: snapshot };
      throw e;
    }
  }

  async function restore(id: number): Promise<void> {
    const bucket = findBucket(archivedByCategory.value, id);
    if (bucket === null) return;
    const { categoryId, snapshot, row } = bucket;
    archivedByCategory.value = {
      ...archivedByCategory.value,
      [categoryId]: snapshot.filter((p) => p.id !== id),
    };
    const restored = { ...row, archived_at: null };
    byCategory.value = {
      ...byCategory.value,
      [categoryId]: [...forCategory(categoryId), restored],
    };
    try {
      await api.restorePlaybook(id);
    } catch (e) {
      archivedByCategory.value = { ...archivedByCategory.value, [categoryId]: snapshot };
      byCategory.value = {
        ...byCategory.value,
        [categoryId]: forCategory(categoryId).filter((p) => p.id !== id),
      };
      throw e;
    }
  }

  async function draft(ticketId: string): Promise<string> {
    const { body } = await api.draftPlaybook(ticketId);
    return body;
  }

  function findBucket(
    map: Record<number, Playbook[]>,
    id: number,
  ): { categoryId: number; snapshot: Playbook[]; row: Playbook } | null {
    for (const [cid, list] of Object.entries(map)) {
      const row = list.find((p) => p.id === id);
      if (row) return { categoryId: Number(cid), snapshot: list, row };
    }
    return null;
  }

  return {
    byCategory,
    archivedByCategory,
    forCategory,
    archivedFor,
    ensureForCategory,
    loadAll,
    create,
    update,
    archive,
    restore,
    draft,
  };
});

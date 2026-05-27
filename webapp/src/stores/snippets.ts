// Snippets store (roadmap 1.5).
//
// Short canned replies with `{{variable}}` placeholders. Global (not
// category-scoped), so a flat list rather than the playbooks store's
// per-category map. The library page reads `active` / `archived`; `loadAll`
// fetches once. Mutations are optimistic with rollback, matching the
// playbooks / noteEntries stores.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { Snippet } from '@/types/api';

export const useSnippetsStore = defineStore('snippets', () => {
  const snippets = ref<Snippet[]>([]);

  const active = computed(() => snippets.value.filter((s) => s.archived_at === null));
  const archived = computed(() => snippets.value.filter((s) => s.archived_at !== null));

  /** Fetch the full library (active rows, plus archived when requested). */
  async function loadAll(includeArchived = false): Promise<void> {
    snippets.value = await api.listSnippets(includeArchived ? { includeArchived: true } : {});
  }

  async function create(body: { title: string; body: string }): Promise<Snippet> {
    const saved = await api.createSnippet(body);
    snippets.value = [...snippets.value, saved];
    return saved;
  }

  async function update(id: number, body: { title?: string; body?: string }): Promise<void> {
    const saved = await api.updateSnippet(id, body);
    snippets.value = snippets.value.map((s) => (s.id === id ? saved : s));
  }

  async function archive(id: number): Promise<void> {
    const row = snippets.value.find((s) => s.id === id);
    if (!row || row.archived_at !== null) return;
    const snapshot = snippets.value;
    snippets.value = snippets.value.map((s) =>
      s.id === id ? { ...s, archived_at: new Date().toISOString() } : s,
    );
    try {
      await api.archiveSnippet(id);
    } catch (e) {
      snippets.value = snapshot;
      throw e;
    }
  }

  async function restore(id: number): Promise<void> {
    const row = snippets.value.find((s) => s.id === id);
    if (!row || row.archived_at === null) return;
    const snapshot = snippets.value;
    snippets.value = snippets.value.map((s) => (s.id === id ? { ...s, archived_at: null } : s));
    try {
      await api.restoreSnippet(id);
    } catch (e) {
      snippets.value = snapshot;
      throw e;
    }
  }

  return { snippets, active, archived, loadAll, create, update, archive, restore };
});

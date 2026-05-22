// Categories + pending proposals store. Per tasks.md T031 / T037 / T038.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { Category, CategoryProposal } from '@/types/api';

interface CategoriesState {
  categories: Category[];
  pendingProposals: CategoryProposal[];
  loading: boolean;
  error: string | null;
}

export const useCategoriesStore = defineStore('categories', () => {
  const state = ref<CategoriesState>({
    categories: [],
    pendingProposals: [],
    loading: false,
    error: null,
  });

  // Detailed proposals (with example ticket ids) for the review page — only
  // fetched on demand from `/proposals`, kept separate from the lightweight
  // `pendingProposals` the board columns render.
  const proposals = ref<CategoryProposal[]>([]);

  const categories = computed(() => state.value.categories);
  const pendingProposals = computed(() => state.value.pendingProposals);
  const loading = computed(() => state.value.loading);
  const error = computed(() => state.value.error);

  /** Active categories AND pending proposals as a single ordered list — what the board renders. */
  const columns = computed(() => [
    ...state.value.categories.map((c) => ({
      kind: 'category' as const,
      id: c.id,
      key: `cat-${c.id}`,
      name: c.name,
      color: c.color,
      sortOrder: c.sort_order,
      isFallback: c.is_fallback,
    })),
    ...state.value.pendingProposals.map((p) => ({
      kind: 'proposal' as const,
      id: p.id,
      key: `prop-${p.id}`,
      name: p.name,
      color: null,
      sortOrder: Number.MAX_SAFE_INTEGER, // proposals after categories
      isFallback: false,
    })),
  ]);

  const byId = computed(() => {
    const m = new Map<number, Category>();
    state.value.categories.forEach((c) => m.set(c.id, c));
    return m;
  });

  async function load() {
    state.value.loading = true;
    state.value.error = null;
    try {
      const resp = await api.listCategories();
      state.value.categories = resp.categories;
      state.value.pendingProposals = resp.pending_proposals;
    } catch (e) {
      state.value.error = (e as Error).message;
      throw e;
    } finally {
      state.value.loading = false;
    }
  }

  async function loadProposals() {
    const resp = await api.listProposals();
    proposals.value = resp.proposals;
  }

  // ── T037 — category mutations (each reloads the canonical list) ────────────

  async function createCategory(name: string, description: string, color: string | null) {
    await api.createCategory({ name, description, color });
    await load();
  }

  async function patchCategory(id: number, patch: Partial<Category>) {
    await api.patchCategory(id, patch);
    await load();
  }

  async function archiveCategory(id: number) {
    await api.archiveCategory(id);
    await load();
  }

  async function mergeCategories(srcId: number, dstId: number): Promise<number> {
    const resp = await api.mergeCategory(srcId, dstId);
    await load();
    return resp.moved_count;
  }

  /** Swap the `sort_order` of two adjacent categories — used by the ↑/↓ controls. */
  async function reorder(id: number, direction: -1 | 1) {
    const sorted = [...state.value.categories].sort((a, b) => a.sort_order - b.sort_order);
    const idx = sorted.findIndex((c) => c.id === id);
    const swapIdx = idx + direction;
    if (idx < 0 || swapIdx < 0 || swapIdx >= sorted.length) return;
    const a = sorted[idx];
    const b = sorted[swapIdx];
    await api.patchCategory(a.id, { sort_order: b.sort_order });
    await api.patchCategory(b.id, { sort_order: a.sort_order });
    await load();
  }

  // ── T038 — proposal resolution ─────────────────────────────────────────────

  async function approveProposal(id: number, color: string | null) {
    await api.approveProposal(id, { color });
    await load();
    await loadProposals();
  }

  async function mergeProposal(id: number, categoryId: number) {
    await api.mergeProposal(id, categoryId);
    await load();
    await loadProposals();
  }

  async function rejectProposal(id: number) {
    await api.rejectProposal(id);
    await load();
    await loadProposals();
  }

  return {
    categories,
    pendingProposals,
    proposals,
    columns,
    byId,
    loading,
    error,
    load,
    loadProposals,
    createCategory,
    patchCategory,
    archiveCategory,
    mergeCategories,
    reorder,
    approveProposal,
    mergeProposal,
    rejectProposal,
  };
});

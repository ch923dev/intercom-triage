// Categories + pending proposals store. Per tasks.md T031.

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

  return { categories, pendingProposals, columns, byId, loading, error, load };
});

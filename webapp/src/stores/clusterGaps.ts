// Cluster content-gaps store (roadmap 3.2 — "what should I build a playbook for").
//
// Read-only: holds the ranked list of recurring-issue clusters whose dominant
// effective category has no active playbook yet. The Playbooks page loads it to
// surface a "Suggested playbooks to build" section. Kept as its own tiny store
// (not folded into the playbooks store) so it stays read-only and decoupled.

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { ClusterGap } from '@/types/api';

export const useClusterGapsStore = defineStore('clusterGaps', () => {
  /** Ranked gaps, most-recurring (largest cluster) first. Server-ordered. */
  const gaps = ref<ClusterGap[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);

  async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      gaps.value = await api.listClusterGaps();
    } catch (e) {
      error.value = (e as Error).message;
      throw e;
    } finally {
      loading.value = false;
    }
  }

  return { gaps, loading, error, load };
});

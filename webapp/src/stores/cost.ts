// Cost meter store (roadmap 1.4). Surfaces today's OpenRouter spend from the
// backend `/metrics` endpoint. The backend keeps these counters in-process and
// resets them on restart, so this is a "spend since the backend last started"
// figure — fine for a solo local tool.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { UsageBucket } from '@/types/api';

export const useCostStore = defineStore('cost', () => {
  const todayCostUsd = ref(0);
  const usage = ref<UsageBucket[]>([]);
  const loading = ref(false);
  const loaded = ref(false);

  /** Total estimated USD spend across every retained day/model bucket. */
  const totalCostUsd = computed(() =>
    usage.value.reduce((sum, b) => sum + b.estimated_cost_usd, 0),
  );

  /** Total tokens (prompt + completion) across all retained buckets. */
  const totalTokens = computed(() => usage.value.reduce((sum, b) => sum + b.total_tokens, 0));

  async function refresh(): Promise<void> {
    loading.value = true;
    try {
      const m = await api.getMetrics();
      todayCostUsd.value = m.today_cost_usd;
      usage.value = m.usage;
      loaded.value = true;
    } finally {
      loading.value = false;
    }
  }

  return { todayCostUsd, usage, loading, loaded, totalCostUsd, totalTokens, refresh };
});

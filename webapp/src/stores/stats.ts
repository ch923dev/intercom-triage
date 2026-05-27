// Stats dashboard store (roadmap 1.3). Surfaces the four success metrics
// (spec §8) rolled up server-side from the tickets table: category breakdown,
// volume trend, resolution mix (resolved_source), and time-to-resolve
// distribution. Read-only — refresh re-fetches `GET /stats` for the selected
// trailing window.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { StatsResponse } from '@/types/api';

/** Window presets offered in the dashboard header (trailing days). */
export const WINDOW_OPTIONS = [7, 14, 30, 90] as const;

export const useStatsStore = defineStore('stats', () => {
  const data = ref<StatsResponse | null>(null);
  const windowDays = ref<number>(30);
  const loading = ref(false);
  const loaded = ref(false);
  const error = ref<string | null>(null);

  /** Largest single-category count — used to scale the breakdown bars. */
  const maxCategoryCount = computed(() =>
    data.value ? data.value.category_breakdown.reduce((m, c) => Math.max(m, c.count), 0) : 0,
  );

  /** Largest single-day volume — used to scale the trend sparkline. */
  const maxVolumeCount = computed(() =>
    data.value ? data.value.volume_trend.reduce((m, p) => Math.max(m, p.count), 0) : 0,
  );

  /** Largest single resolve-time bucket count — used to scale those bars. */
  const maxResolveBucketCount = computed(() =>
    data.value ? data.value.resolve_time_buckets.reduce((m, b) => Math.max(m, b.count), 0) : 0,
  );

  /** Total resolved tickets across the resolution mix (everything but `open`). */
  const resolvedTotal = computed(() => {
    const m = data.value?.resolution_mix;
    if (!m) return 0;
    return m.manual + m.intercom_closed + m.non_actionable + m.ai_resolved;
  });

  async function refresh(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      data.value = await api.getStats(windowDays.value);
      loaded.value = true;
    } catch (e) {
      error.value = e instanceof Error ? e.message : String(e);
    } finally {
      loading.value = false;
    }
  }

  /** Switch the trailing window and re-fetch. */
  async function setWindow(days: number): Promise<void> {
    windowDays.value = days;
    await refresh();
  }

  return {
    data,
    windowDays,
    loading,
    loaded,
    error,
    maxCategoryCount,
    maxVolumeCount,
    maxResolveBucketCount,
    resolvedTotal,
    refresh,
    setWindow,
  };
});

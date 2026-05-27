// Stats dashboard store unit tests (roadmap 1.3).

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useStatsStore } from './stats';
import { api } from '@/api/client';
import type { StatsResponse } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    getStats: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function makeStats(over: Partial<StatsResponse> = {}): StatsResponse {
  return {
    window_days: 30,
    total_tickets: 6,
    category_breakdown: [
      { category_id: 1, category_name: 'Bug', count: 4 },
      { category_id: 2, category_name: 'Billing', count: 2 },
    ],
    volume_trend: [
      { date: '2026-05-25', count: 1 },
      { date: '2026-05-26', count: 0 },
      { date: '2026-05-27', count: 5 },
    ],
    resolution_mix: {
      open: 2,
      manual: 2,
      intercom_closed: 1,
      non_actionable: 0,
      ai_resolved: 1,
    },
    resolve_time_buckets: [
      { label: '< 1h', lower_hours: 0, upper_hours: 1, count: 1 },
      { label: '1–4h', lower_hours: 1, upper_hours: 4, count: 3 },
      { label: '≥ 7d', lower_hours: 168, upper_hours: null, count: 0 },
    ],
    median_resolve_hours: 2.5,
    ...over,
  };
}

describe('statsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('refresh() loads the rollup for the default 30-day window', async () => {
    mocked.getStats.mockResolvedValue(makeStats());
    const store = useStatsStore();

    expect(store.loaded).toBe(false);
    await store.refresh();

    expect(mocked.getStats).toHaveBeenCalledWith(30);
    expect(store.data?.total_tickets).toBe(6);
    expect(store.loaded).toBe(true);
    expect(store.loading).toBe(false);
    expect(store.error).toBeNull();
  });

  it('max-count getters scale the bars/sparkline', async () => {
    mocked.getStats.mockResolvedValue(makeStats());
    const store = useStatsStore();
    await store.refresh();

    expect(store.maxCategoryCount).toBe(4); // Bug
    expect(store.maxVolumeCount).toBe(5); // 2026-05-27
    expect(store.maxResolveBucketCount).toBe(3); // 1–4h
  });

  it('resolvedTotal sums every non-open resolution source', async () => {
    mocked.getStats.mockResolvedValue(makeStats());
    const store = useStatsStore();
    await store.refresh();

    // manual 2 + intercom_closed 1 + non_actionable 0 + ai_resolved 1 == 4
    expect(store.resolvedTotal).toBe(4);
  });

  it('setWindow() switches the window and re-fetches', async () => {
    mocked.getStats.mockResolvedValue(makeStats({ window_days: 7 }));
    const store = useStatsStore();

    await store.setWindow(7);

    expect(store.windowDays).toBe(7);
    expect(mocked.getStats).toHaveBeenCalledWith(7);
  });

  it('captures the error and clears loading when getStats rejects', async () => {
    mocked.getStats.mockRejectedValue(new Error('boom'));
    const store = useStatsStore();

    await store.refresh();

    expect(store.error).toBe('boom');
    expect(store.loading).toBe(false);
    expect(store.loaded).toBe(false);
    expect(store.data).toBeNull();
  });

  it('getters are zero-safe before any data loads', () => {
    const store = useStatsStore();
    expect(store.maxCategoryCount).toBe(0);
    expect(store.maxVolumeCount).toBe(0);
    expect(store.maxResolveBucketCount).toBe(0);
    expect(store.resolvedTotal).toBe(0);
  });
});

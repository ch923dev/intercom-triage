// Cost meter store unit tests (roadmap 1.4).

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useCostStore } from './cost';
import { api } from '@/api/client';
import type { MetricsResponse, UsageBucket } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    getMetrics: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function makeBucket(over: Partial<UsageBucket> = {}): UsageBucket {
  return {
    date: '2026-05-27',
    model: 'anthropic/claude-sonnet-4.5',
    prompt_tokens: 100,
    completion_tokens: 50,
    total_tokens: 150,
    calls: 1,
    estimated_cost_usd: 0.00105,
    ...over,
  };
}

function makeMetrics(over: Partial<MetricsResponse> = {}): MetricsResponse {
  return {
    counters: {},
    usage: [makeBucket()],
    today_cost_usd: 0.00105,
    ...over,
  };
}

describe('costStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('refresh() pulls today cost + usage and marks loaded', async () => {
    mocked.getMetrics.mockResolvedValue(makeMetrics());
    const store = useCostStore();

    expect(store.loaded).toBe(false);
    await store.refresh();

    expect(store.todayCostUsd).toBeCloseTo(0.00105);
    expect(store.usage).toHaveLength(1);
    expect(store.loaded).toBe(true);
    expect(store.loading).toBe(false);
  });

  it('totalCostUsd + totalTokens sum across buckets', async () => {
    mocked.getMetrics.mockResolvedValue(
      makeMetrics({
        usage: [
          makeBucket({ model: 'a', estimated_cost_usd: 0.1, total_tokens: 100 }),
          makeBucket({ model: 'b', estimated_cost_usd: 0.25, total_tokens: 300 }),
        ],
        today_cost_usd: 0.35,
      }),
    );
    const store = useCostStore();
    await store.refresh();

    expect(store.totalCostUsd).toBeCloseTo(0.35);
    expect(store.totalTokens).toBe(400);
  });

  it('clears loading even when getMetrics rejects', async () => {
    mocked.getMetrics.mockRejectedValue(new Error('boom'));
    const store = useCostStore();

    await expect(store.refresh()).rejects.toThrow('boom');
    expect(store.loading).toBe(false);
    expect(store.loaded).toBe(false);
  });
});

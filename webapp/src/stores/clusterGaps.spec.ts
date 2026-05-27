import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useClusterGapsStore } from './clusterGaps';
import { api } from '@/api/client';
import type { ClusterGap } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listClusterGaps: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function make(over: Partial<ClusterGap> = {}): ClusterGap {
  return {
    cluster_id: 1,
    label: 'login outage',
    top_terms: ['login', 'password', 'reset'],
    size: 3,
    category_id: 1,
    category_name: 'Urgent',
    member_count: 3,
    ...over,
  };
}

describe('clusterGapsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('load stores the server-ranked gaps', async () => {
    mocked.listClusterGaps.mockResolvedValue([
      make({ cluster_id: 11, size: 4, label: 'big' }),
      make({ cluster_id: 10, size: 2, label: 'small' }),
    ]);
    const s = useClusterGapsStore();
    await s.load();
    expect(s.gaps.map((g) => g.cluster_id)).toEqual([11, 10]);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('starts empty', () => {
    const s = useClusterGapsStore();
    expect(s.gaps).toEqual([]);
  });

  it('records the error and rethrows on failure', async () => {
    mocked.listClusterGaps.mockRejectedValue(new Error('boom'));
    const s = useClusterGapsStore();
    await expect(s.load()).rejects.toThrow('boom');
    expect(s.error).toBe('boom');
    expect(s.loading).toBe(false);
  });
});

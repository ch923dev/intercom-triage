import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { usePlaybooksStore } from './playbooks';
import { api } from '@/api/client';
import type { Playbook } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listPlaybooks: vi.fn(),
    createPlaybook: vi.fn(),
    updatePlaybook: vi.fn(),
    archivePlaybook: vi.fn(),
    restorePlaybook: vi.fn(),
    draftPlaybook: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function make(over: Partial<Playbook> = {}): Playbook {
  return {
    id: 1,
    category_id: 1,
    label: 'issue',
    body: 'steps',
    source_ticket_id: null,
    created_at: '2026-05-26T10:00:00Z',
    updated_at: '2026-05-26T10:00:00Z',
    archived_at: null,
    ...over,
  };
}

describe('playbooksStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('ensureForCategory caches results and serves forCategory', async () => {
    mocked.listPlaybooks.mockResolvedValue([make({ id: 1, label: 'a' })]);
    const s = usePlaybooksStore();
    await s.ensureForCategory(1);
    expect(s.forCategory(1).map((p) => p.label)).toEqual(['a']);
    // Second call does not re-fetch.
    await s.ensureForCategory(1);
    expect(mocked.listPlaybooks).toHaveBeenCalledTimes(1);
  });

  it('create appends to the category bucket', async () => {
    mocked.listPlaybooks.mockResolvedValue([]);
    mocked.createPlaybook.mockResolvedValue(make({ id: 5, label: 'new', category_id: 2 }));
    const s = usePlaybooksStore();
    await s.ensureForCategory(2);
    const created = await s.create({ category_id: 2, label: 'new', body: 'x' });
    expect(created.id).toBe(5);
    expect(s.forCategory(2).map((p) => p.label)).toEqual(['new']);
  });

  it('archive removes from the active bucket and rolls back on failure', async () => {
    mocked.listPlaybooks.mockResolvedValue([make({ id: 9, category_id: 1 })]);
    const s = usePlaybooksStore();
    await s.ensureForCategory(1);

    mocked.archivePlaybook.mockRejectedValue(new Error('500'));
    await expect(s.archive(9)).rejects.toThrow();
    expect(s.forCategory(1).map((p) => p.id)).toEqual([9]);
  });

  it('draft returns the server body without storing it', async () => {
    mocked.draftPlaybook.mockResolvedValue({ body: '1. do thing' });
    const s = usePlaybooksStore();
    expect(await s.draft('T1')).toBe('1. do thing');
  });
});

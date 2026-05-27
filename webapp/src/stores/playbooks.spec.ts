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
    suggestedPlaybooks: vi.fn(),
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

  it('update replaces the row in its category bucket', async () => {
    mocked.listPlaybooks.mockResolvedValue([make({ id: 3, category_id: 1, label: 'old' })]);
    const s = usePlaybooksStore();
    await s.ensureForCategory(1);
    mocked.updatePlaybook.mockResolvedValue(make({ id: 3, category_id: 1, label: 'new' }));
    await s.update(3, { label: 'new' });
    expect(s.forCategory(1).map((p) => p.label)).toEqual(['new']);
  });

  it('loadAll(true) splits active and archived buckets', async () => {
    mocked.listPlaybooks.mockResolvedValue([
      make({ id: 1, category_id: 1, label: 'active', archived_at: null }),
      make({ id: 2, category_id: 1, label: 'gone', archived_at: '2026-05-26T11:00:00Z' }),
    ]);
    const s = usePlaybooksStore();
    await s.loadAll(true);
    expect(s.forCategory(1).map((p) => p.label)).toEqual(['active']);
    expect(s.archivedFor(1).map((p) => p.label)).toEqual(['gone']);
  });

  it('ensureSuggestion caches the top suggested playbook id', async () => {
    mocked.suggestedPlaybooks.mockResolvedValue([
      { playbook: make({ id: 7 }), score: 0.9 },
      { playbook: make({ id: 8 }), score: 0.3 },
    ]);
    const s = usePlaybooksStore();
    await s.ensureSuggestion('T1');
    expect(s.suggestedTopFor('T1')).toBe(7);
  });

  it('ensureSuggestion records null when there is no suggestion', async () => {
    mocked.suggestedPlaybooks.mockResolvedValue([]);
    const s = usePlaybooksStore();
    await s.ensureSuggestion('T2');
    expect(s.suggestedTopFor('T2')).toBeNull();
  });

  it('ensureSuggestion is best-effort: swallows errors, leaves no highlight', async () => {
    mocked.suggestedPlaybooks.mockRejectedValue(new Error('500'));
    const s = usePlaybooksStore();
    await expect(s.ensureSuggestion('T3')).resolves.toBeUndefined();
    expect(s.suggestedTopFor('T3')).toBeNull();
  });

  it('restore moves a row back to active and rolls back on failure', async () => {
    mocked.listPlaybooks.mockResolvedValue([
      make({ id: 2, category_id: 1, label: 'gone', archived_at: '2026-05-26T11:00:00Z' }),
    ]);
    const s = usePlaybooksStore();
    await s.loadAll(true);
    mocked.restorePlaybook.mockRejectedValue(new Error('500'));
    await expect(s.restore(2)).rejects.toThrow();
    expect(s.archivedFor(1).map((p) => p.id)).toEqual([2]);
    expect(s.forCategory(1)).toEqual([]);
  });
});

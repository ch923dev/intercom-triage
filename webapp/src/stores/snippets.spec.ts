import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useSnippetsStore } from './snippets';
import { api } from '@/api/client';
import type { Snippet } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listSnippets: vi.fn(),
    createSnippet: vi.fn(),
    updateSnippet: vi.fn(),
    archiveSnippet: vi.fn(),
    restoreSnippet: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function make(over: Partial<Snippet> = {}): Snippet {
  return {
    id: 1,
    title: 'greeting',
    body: 'Hi {{customer_name}}',
    created_at: '2026-05-27T10:00:00Z',
    updated_at: '2026-05-27T10:00:00Z',
    archived_at: null,
    ...over,
  };
}

describe('snippetsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('loadAll populates and splits active / archived', async () => {
    mocked.listSnippets.mockResolvedValue([
      make({ id: 1, title: 'live', archived_at: null }),
      make({ id: 2, title: 'gone', archived_at: '2026-05-27T11:00:00Z' }),
    ]);
    const s = useSnippetsStore();
    await s.loadAll(true);
    expect(s.active.map((x) => x.title)).toEqual(['live']);
    expect(s.archived.map((x) => x.title)).toEqual(['gone']);
  });

  it('create appends to the list', async () => {
    mocked.listSnippets.mockResolvedValue([]);
    mocked.createSnippet.mockResolvedValue(make({ id: 5, title: 'new' }));
    const s = useSnippetsStore();
    await s.loadAll();
    const created = await s.create({ title: 'new', body: 'x' });
    expect(created.id).toBe(5);
    expect(s.active.map((x) => x.title)).toEqual(['new']);
  });

  it('update replaces the row', async () => {
    mocked.listSnippets.mockResolvedValue([make({ id: 3, title: 'old' })]);
    const s = useSnippetsStore();
    await s.loadAll();
    mocked.updateSnippet.mockResolvedValue(make({ id: 3, title: 'fresh' }));
    await s.update(3, { title: 'fresh' });
    expect(s.active.map((x) => x.title)).toEqual(['fresh']);
  });

  it('archive moves a row to archived and rolls back on failure', async () => {
    mocked.listSnippets.mockResolvedValue([make({ id: 9 })]);
    const s = useSnippetsStore();
    await s.loadAll();

    mocked.archiveSnippet.mockRejectedValue(new Error('500'));
    await expect(s.archive(9)).rejects.toThrow();
    // Rolled back — still active.
    expect(s.active.map((x) => x.id)).toEqual([9]);
    expect(s.archived).toEqual([]);
  });

  it('archive succeeds optimistically', async () => {
    mocked.listSnippets.mockResolvedValue([make({ id: 9 })]);
    mocked.archiveSnippet.mockResolvedValue({ ok: true });
    const s = useSnippetsStore();
    await s.loadAll();
    await s.archive(9);
    expect(s.active).toEqual([]);
    expect(s.archived.map((x) => x.id)).toEqual([9]);
  });

  it('restore moves a row back to active and rolls back on failure', async () => {
    mocked.listSnippets.mockResolvedValue([make({ id: 2, archived_at: '2026-05-27T11:00:00Z' })]);
    const s = useSnippetsStore();
    await s.loadAll(true);
    mocked.restoreSnippet.mockRejectedValue(new Error('500'));
    await expect(s.restore(2)).rejects.toThrow();
    expect(s.archived.map((x) => x.id)).toEqual([2]);
    expect(s.active).toEqual([]);
  });
});

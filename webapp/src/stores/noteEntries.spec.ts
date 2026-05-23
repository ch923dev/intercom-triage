// Time-tabled notes store unit tests.

import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useNoteEntriesStore } from './noteEntries';
import { api } from '@/api/client';
import type { NoteEntry } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listNoteEntries: vi.fn(),
    addNoteEntry: vi.fn(),
    deleteNoteEntry: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function makeEntry(over: Partial<NoteEntry> = {}): NoteEntry {
  return {
    id: 1,
    ticket_id: 'T1',
    body: 'a',
    timer_min: null,
    reason: null,
    created_at: '2026-05-23T10:00:00Z',
    ...over,
  };
}

describe('noteEntriesStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('load() seeds map keyed by ticket_id with chronological arrays', async () => {
    mocked.listNoteEntries.mockResolvedValue([
      makeEntry({ id: 1, ticket_id: 'T1', body: 'first' }),
      makeEntry({ id: 2, ticket_id: 'T1', body: 'second' }),
      makeEntry({ id: 3, ticket_id: 'T2', body: 'other' }),
    ]);
    const s = useNoteEntriesStore();
    await s.load();
    expect(s.entriesOf('T1').map((e) => e.body)).toEqual(['first', 'second']);
    expect(s.entriesOf('T2').map((e) => e.body)).toEqual(['other']);
    expect(s.countOf('T1')).toBe(2);
    expect(s.countOf('missing')).toBe(0);
  });

  it('load() falls back to empty on backend error', async () => {
    mocked.listNoteEntries.mockRejectedValue(new Error('boom'));
    const s = useNoteEntriesStore();
    await s.load();
    expect(s.entriesOf('T1')).toEqual([]);
  });

  it('addEntry() optimistically appends then replaces with server row', async () => {
    const saved = makeEntry({ id: 42, body: 'saved', created_at: '2026-05-23T10:01:00Z' });
    mocked.addNoteEntry.mockResolvedValue(saved);

    const s = useNoteEntriesStore();
    const pending = s.addEntry('T1', 'saved', 15, 'reason');

    expect(s.entriesOf('T1').map((e) => e.body)).toEqual(['saved']);
    expect(s.entriesOf('T1')[0].id).toBeLessThan(0);

    await pending;
    expect(s.entriesOf('T1').map((e) => e.id)).toEqual([42]);
  });

  it('addEntry() rolls back when the server rejects', async () => {
    mocked.addNoteEntry.mockRejectedValue(new Error('500'));
    const s = useNoteEntriesStore();
    await expect(s.addEntry('T1', 'oops')).rejects.toThrow();
    expect(s.entriesOf('T1')).toEqual([]);
  });

  it('deleteEntry() removes the row optimistically and rolls back on failure', async () => {
    const e = makeEntry({ id: 7, ticket_id: 'T1' });
    mocked.listNoteEntries.mockResolvedValue([e]);
    const s = useNoteEntriesStore();
    await s.load();

    mocked.deleteNoteEntry.mockRejectedValue(new Error('500'));
    await expect(s.deleteEntry(7)).rejects.toThrow();
    expect(s.entriesOf('T1').map((x) => x.id)).toEqual([7]);
  });

  it('deleteEntry() succeeds and the row is gone', async () => {
    const e = makeEntry({ id: 7, ticket_id: 'T1' });
    mocked.listNoteEntries.mockResolvedValue([e]);
    const s = useNoteEntriesStore();
    await s.load();

    mocked.deleteNoteEntry.mockResolvedValue({ ok: true, deleted: true, id: 7 });
    await s.deleteEntry(7);
    expect(s.entriesOf('T1')).toEqual([]);
    expect(s.countOf('T1')).toBe(0);
  });
});

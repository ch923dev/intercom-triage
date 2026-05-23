// Note attachments store unit tests.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAttachmentsStore } from './attachments';
import { api } from '@/api/client';
import type { NoteAttachment } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listAttachments: vi.fn(),
    uploadAttachment: vi.fn(),
    deleteAttachment: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function make(over: Partial<NoteAttachment> = {}): NoteAttachment {
  return {
    id: 1,
    owner_kind: 'ticket',
    owner_id: 'T1',
    ticket_id: 'T1',
    filename: 'a.txt',
    mime: 'text/plain',
    size_bytes: 1,
    created_at: '2026-05-23T10:00:00Z',
    raw_url: '/api/attachments/1/raw',
    thumb_url: null,
    ...over,
  };
}

describe('attachmentsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('load() seeds map and marks ticket as loaded', async () => {
    mocked.listAttachments.mockResolvedValue([make({ id: 1 }), make({ id: 2 })]);
    const s = useAttachmentsStore();
    await s.load('T1');
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([1, 2]);
    expect(mocked.listAttachments).toHaveBeenCalledTimes(1);

    await s.load('T1');
    expect(mocked.listAttachments).toHaveBeenCalledTimes(1); // no-op second call
  });

  it('byTicket filters to owner_kind=ticket', async () => {
    mocked.listAttachments.mockResolvedValue([
      make({ id: 1, owner_kind: 'ticket', owner_id: 'T1' }),
      make({ id: 2, owner_kind: 'entry', owner_id: '42' }),
    ]);
    const s = useAttachmentsStore();
    await s.load('T1');
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([1]);
  });

  it('byEntry filters to matching entry id', async () => {
    mocked.listAttachments.mockResolvedValue([
      make({ id: 1, owner_kind: 'entry', owner_id: '42' }),
      make({ id: 2, owner_kind: 'entry', owner_id: '99' }),
      make({ id: 3, owner_kind: 'ticket', owner_id: 'T1' }),
    ]);
    const s = useAttachmentsStore();
    await s.load('T1');
    expect(s.byEntry(42).map((a) => a.id)).toEqual([1]);
    expect(s.byEntry(99).map((a) => a.id)).toEqual([2]);
  });

  it('upload() shows optimistic placeholder then replaces with server row', async () => {
    const saved = make({ id: 100, filename: 'saved.txt' });
    mocked.uploadAttachment.mockResolvedValue(saved);
    const s = useAttachmentsStore();
    const file = new File(['x'], 'saved.txt', { type: 'text/plain' });
    const pending = s.upload(file, 'ticket', 'T1', 'T1');

    // optimistic row appears immediately with a temp negative id.
    expect(s.byTicket('T1').length).toBe(1);
    expect(s.byTicket('T1')[0].id).toBeLessThan(0);

    await pending;
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([100]);
  });

  it('upload() rolls back on server rejection', async () => {
    mocked.uploadAttachment.mockRejectedValue(new Error('500'));
    const s = useAttachmentsStore();
    const file = new File(['x'], 'fail.txt', { type: 'text/plain' });
    await expect(s.upload(file, 'ticket', 'T1', 'T1')).rejects.toThrow();
    expect(s.byTicket('T1')).toEqual([]);
  });

  it('remove() removes optimistically and rolls back on failure', async () => {
    mocked.listAttachments.mockResolvedValue([make({ id: 7 })]);
    const s = useAttachmentsStore();
    await s.load('T1');
    mocked.deleteAttachment.mockRejectedValue(new Error('500'));
    await expect(s.remove(7)).rejects.toThrow();
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([7]);
  });

  it('remove() succeeds and clears the row', async () => {
    mocked.listAttachments.mockResolvedValue([make({ id: 7 })]);
    const s = useAttachmentsStore();
    await s.load('T1');
    mocked.deleteAttachment.mockResolvedValue({ ok: true, deleted: true, id: 7 });
    await s.remove(7);
    expect(s.byTicket('T1')).toEqual([]);
  });
});

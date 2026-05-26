// Follow-up store spec — alarm tick (T051), snooze rollback, banner dedup.
// Covers the C2/C3 fixes from the 2026-05-27 webapp review.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useFollowupsStore } from './followups';
import type { Followup } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listFollowups: vi.fn(),
    setFollowup: vi.fn(),
    clearFollowup: vi.fn(),
    snoozeFollowup: vi.fn(),
    markFollowupFired: vi.fn(),
    bulkSetFollowup: vi.fn(),
    bulkClearFollowup: vi.fn(),
  },
}));

function fakeFollowup(ticketId: string, overrides: Partial<Followup> = {}): Followup {
  const iso = new Date().toISOString();
  return {
    ticket_id: ticketId,
    due_at: iso,
    reason: null,
    fired: false,
    created_at: iso,
    updated_at: iso,
    ...overrides,
  };
}

/** ISO timestamp `seconds` in the past (so the follow-up is already due). */
function pastIso(seconds = 60): string {
  return new Date(Date.now() - seconds * 1000).toISOString();
}

describe('followupsStore.tick', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('raises a banner once for a newly-due follow-up and does not re-fire', async () => {
    const { api } = await import('@/api/client');
    const due = pastIso();
    (api.setFollowup as ReturnType<typeof vi.fn>).mockResolvedValue(
      fakeFollowup('t1', { due_at: due }),
    );
    (api.markFollowupFired as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const s = useFollowupsStore();

    await s.setFollowup('t1', new Date(due), null);

    const fired = s.tick();
    expect(fired).toEqual(['t1']);
    expect(s.banners).toHaveLength(1);

    // Second tick: already fired → no duplicate banner, nothing newly fired.
    const firedAgain = s.tick();
    expect(firedAgain).toEqual([]);
    expect(s.banners).toHaveLength(1);
  });
});

describe('followupsStore.tick banner dedup (C3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('does not stack a second banner when one is already showing for the ticket', async () => {
    const { api } = await import('@/api/client');
    (api.markFollowupFired as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    const due = pastIso();
    (api.setFollowup as ReturnType<typeof vi.fn>).mockResolvedValue(
      fakeFollowup('t1', { due_at: due }),
    );
    const s = useFollowupsStore();

    await s.setFollowup('t1', new Date(due), null);
    s.tick(); // fires + raises banner, marks fired
    expect(s.banners).toHaveLength(1);

    // Reschedule to a past time clears `fired` but leaves the banner up.
    (api.setFollowup as ReturnType<typeof vi.fn>).mockResolvedValue(
      fakeFollowup('t1', { due_at: pastIso(30), fired: false }),
    );
    await s.setFollowup('t1', new Date(pastIso(30)), null);

    s.tick();
    expect(s.banners).toHaveLength(1); // deduped, not 2
  });
});

describe('followupsStore.snooze rollback (C2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('restores the record and re-raises the banner when the API call fails', async () => {
    const { api } = await import('@/api/client');
    const due = pastIso();
    (api.setFollowup as ReturnType<typeof vi.fn>).mockResolvedValue(
      fakeFollowup('t1', { due_at: due }),
    );
    (api.markFollowupFired as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    (api.snoozeFollowup as ReturnType<typeof vi.fn>).mockRejectedValue(new Error('boom'));
    const s = useFollowupsStore();

    await s.setFollowup('t1', new Date(due), null);
    s.tick();
    expect(s.banners).toHaveLength(1);

    await expect(s.snooze('t1', 15)).rejects.toThrow('boom');

    // Record preserved (not lost), banner back up so the alarm isn't silently gone.
    expect(s.get('t1')).toBeDefined();
    expect(s.get('t1')!.due_at).toBe(due);
    expect(s.banners).toHaveLength(1);
  });

  it('applies the snoozed record and drops the banner on success', async () => {
    const { api } = await import('@/api/client');
    const due = pastIso();
    const snoozed = fakeFollowup('t1', { due_at: new Date(Date.now() + 900_000).toISOString() });
    (api.setFollowup as ReturnType<typeof vi.fn>).mockResolvedValue(
      fakeFollowup('t1', { due_at: due }),
    );
    (api.markFollowupFired as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
    (api.snoozeFollowup as ReturnType<typeof vi.fn>).mockResolvedValue(snoozed);
    const s = useFollowupsStore();

    await s.setFollowup('t1', new Date(due), null);
    s.tick();

    await s.snooze('t1', 15);
    expect(s.banners).toHaveLength(0);
    expect(s.get('t1')!.due_at).toBe(snoozed.due_at);
  });
});

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useBugAlertsStore } from './bugAlerts';
import { api } from '@/api/client';
import type { BugAlert } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listBugAlerts: vi.fn(),
    dismissBugAlert: vi.fn(),
    ackBugAlert: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function make(over: Partial<BugAlert> = {}): BugAlert {
  return {
    ticket_id: 'T1',
    severity: 'medium',
    confidence: 0.8,
    evidence: 'the export button does nothing',
    occurrences: 1,
    first_detected_at: '2026-08-13T09:00:00Z',
    last_detected_at: '2026-08-13T09:00:00Z',
    posted_at: null,
    posted_severity: null,
    slack_channel: null,
    slack_ts: null,
    dismissed_at: null,
    acked_at: null,
    acked_by: null,
    title: 'Export broken',
    url: 'https://example.com/conv/T1',
    ...over,
  };
}

describe('bugAlertsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => vi.restoreAllMocks());

  it('load keeps the server ordering', async () => {
    mocked.listBugAlerts.mockResolvedValue([
      make({ ticket_id: 'high', severity: 'high' }),
      make({ ticket_id: 'low', severity: 'low' }),
    ]);
    const s = useBugAlertsStore();
    await s.load();
    expect(s.alerts.map((a) => a.ticket_id)).toEqual(['high', 'low']);
    expect(s.loading).toBe(false);
    expect(s.error).toBeNull();
  });

  it('records the error and rethrows when the list fails', async () => {
    mocked.listBugAlerts.mockRejectedValue(new Error('boom'));
    const s = useBugAlertsStore();
    await expect(s.load()).rejects.toThrow('boom');
    expect(s.error).toBe('boom');
    expect(s.loading).toBe(false);
  });

  it('pendingCount counts only undismissed alerts', async () => {
    mocked.listBugAlerts.mockResolvedValue([
      make({ ticket_id: 'a' }),
      make({ ticket_id: 'b', dismissed_at: '2026-08-13T10:00:00Z' }),
      make({ ticket_id: 'c' }),
    ]);
    const s = useBugAlertsStore();
    await s.load();
    expect(s.pendingCount).toBe(2);
  });

  it('dismiss replaces only the affected row, without refetching', async () => {
    mocked.listBugAlerts.mockResolvedValue([make({ ticket_id: 'a' }), make({ ticket_id: 'b' })]);
    const s = useBugAlertsStore();
    await s.load();

    mocked.dismissBugAlert.mockResolvedValue(
      make({ ticket_id: 'b', dismissed_at: '2026-08-13T10:00:00Z' }),
    );
    await s.dismiss('b');

    expect(s.alerts.find((a) => a.ticket_id === 'b')?.dismissed_at).toBe('2026-08-13T10:00:00Z');
    expect(s.alerts.find((a) => a.ticket_id === 'a')?.dismissed_at).toBeNull();
    // A refetch would flicker and could clobber a detection that landed between
    // the two calls, so the list endpoint must not be called again.
    expect(mocked.listBugAlerts).toHaveBeenCalledTimes(1);
  });

  it('a failed dismiss leaves the row untouched', async () => {
    mocked.listBugAlerts.mockResolvedValue([make({ ticket_id: 'a' })]);
    const s = useBugAlertsStore();
    await s.load();

    mocked.dismissBugAlert.mockRejectedValue(new Error('offline'));
    await expect(s.dismiss('a')).rejects.toThrow('offline');

    expect(s.alerts[0].dismissed_at).toBeNull();
    expect(s.error).toBe('offline');
    expect(s.dismissing.has('a')).toBe(false);
  });

  it('ack replaces the row and names the acknowledger', async () => {
    mocked.listBugAlerts.mockResolvedValue([make({ ticket_id: 'a' }), make({ ticket_id: 'b' })]);
    const s = useBugAlertsStore();
    await s.load();

    mocked.ackBugAlert.mockResolvedValue({
      alert: make({
        ticket_id: 'b',
        acked_at: '2026-08-15T10:00:00Z',
        acked_by: { id: 1, name: 'Christian' },
      }),
      slack_updated: true,
    });
    await s.ack('b');

    const row = s.alerts.find((x) => x.ticket_id === 'b');
    expect(row?.acked_by?.name).toBe('Christian');
    expect(s.alerts.find((x) => x.ticket_id === 'a')?.acked_at).toBeNull();
    expect(mocked.listBugAlerts).toHaveBeenCalledTimes(1); // no refetch
    expect(s.mirrorFailed.has('b')).toBe(false);
  });

  it('flags an announced alert whose Slack message could not be updated', async () => {
    mocked.listBugAlerts.mockResolvedValue([make({ ticket_id: 'a', slack_ts: '123.45' })]);
    const s = useBugAlertsStore();
    await s.load();

    mocked.ackBugAlert.mockResolvedValue({
      alert: make({ ticket_id: 'a', slack_ts: '123.45', acked_at: '2026-08-15T10:00:00Z' }),
      slack_updated: false,
    });
    await s.ack('a');

    // The ack itself succeeded — it must not be reported as an error.
    expect(s.error).toBeNull();
    expect(s.alerts[0].acked_at).not.toBeNull();
    expect(s.mirrorFailed.has('a')).toBe(true);
  });

  it('does not flag a never-announced alert as a failed mirror', async () => {
    mocked.listBugAlerts.mockResolvedValue([make({ ticket_id: 'a', slack_ts: null })]);
    const s = useBugAlertsStore();
    await s.load();

    mocked.ackBugAlert.mockResolvedValue({
      alert: make({ ticket_id: 'a', slack_ts: null, acked_at: '2026-08-15T10:00:00Z' }),
      slack_updated: false,
    });
    await s.ack('a');

    // There was no message to update, so nothing is out of date.
    expect(s.mirrorFailed.has('a')).toBe(false);
  });

  it('a failed ack leaves the row untouched', async () => {
    mocked.listBugAlerts.mockResolvedValue([make({ ticket_id: 'a' })]);
    const s = useBugAlertsStore();
    await s.load();

    mocked.ackBugAlert.mockRejectedValue(new Error('offline'));
    await expect(s.ack('a')).rejects.toThrow('offline');

    expect(s.alerts[0].acked_at).toBeNull();
    expect(s.error).toBe('offline');
    expect(s.acking.has('a')).toBe(false);
  });

  it('pendingCount still counts an acknowledged but undismissed alert', async () => {
    mocked.listBugAlerts.mockResolvedValue([
      make({ ticket_id: 'a', acked_at: '2026-08-15T10:00:00Z', acked_by: { id: 1, name: 'C' } }),
      make({ ticket_id: 'b', dismissed_at: '2026-08-15T10:00:00Z' }),
    ]);
    const s = useBugAlertsStore();
    await s.load();
    // Owned is not finished.
    expect(s.pendingCount).toBe(1);
  });

  it('tracks the in-flight ticket id while dismissing', async () => {
    mocked.listBugAlerts.mockResolvedValue([make({ ticket_id: 'a' })]);
    const s = useBugAlertsStore();
    await s.load();

    let release: (v: BugAlert) => void = () => undefined;
    mocked.dismissBugAlert.mockReturnValue(
      new Promise<BugAlert>((resolve) => {
        release = resolve;
      }),
    );
    const pending = s.dismiss('a');
    expect(s.dismissing.has('a')).toBe(true);

    release(make({ ticket_id: 'a', dismissed_at: '2026-08-13T10:00:00Z' }));
    await pending;
    expect(s.dismissing.has('a')).toBe(false);
  });
});

// Settings store — the guard that keeps a transient GET failure from
// overwriting the team-wide settings row. Reference: tasks.md T198, invariant #18.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useSettingsStore } from './settings';
import { api } from '@/api/client';
import type { FilterSettings } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    getSettings: vi.fn(),
    putSettings: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

/** A stored row that differs from every client default, so a test can tell
 *  "the server's values" from "the defaults" by inspection. */
function serverRow(over: Partial<FilterSettings> = {}): FilterSettings {
  return {
    lookback_unit: 'days',
    lookback_value: 30,
    states: ['open', 'snoozed'],
    include_category_ids: [3, 7],
    mute_alarms: false,
    use_ai: true,
    ai_resolve_default: true,
    ai_resolve_confidence_threshold: 0.85,
    hide_empty_categories: false,
    ...over,
  };
}

describe('settingsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('refuses to PUT client defaults after a failed load', async () => {
    // The whole point: `update()` PUTs the entire row, so writing after a failed
    // load would reset the team's lookback, state filter, category include-list
    // and AI threshold to whatever this client happens to have in DEFAULTS.
    mocked.getSettings.mockRejectedValue(new Error('503'));
    const s = useSettingsStore();
    await s.load();

    expect(s.loaded).toBe(false);
    expect(s.loadError).toBe('503');
    await expect(s.setMuteAlarms(true)).rejects.toThrow(/refusing to overwrite/i);
    expect(mocked.putSettings).not.toHaveBeenCalled();
  });

  it('recovers by re-loading when the backend comes back', async () => {
    mocked.getSettings.mockRejectedValueOnce(new Error('503'));
    const s = useSettingsStore();
    await s.load();
    expect(s.loaded).toBe(false);

    const row = serverRow();
    mocked.getSettings.mockResolvedValue(row);
    mocked.putSettings.mockResolvedValue({ ...row, mute_alarms: true });

    await s.setMuteAlarms(true);

    expect(mocked.putSettings).toHaveBeenCalledTimes(1);
    // The PUT must carry the SERVER's values plus the patch — not DEFAULTS.
    const sent = mocked.putSettings.mock.calls[0]![0];
    expect(sent.lookback_value).toBe(30);
    expect(sent.include_category_ids).toEqual([3, 7]);
    expect(sent.mute_alarms).toBe(true);
    expect(s.muteAlarms).toBe(true);
  });

  it('PUTs normally after a successful load', async () => {
    // The guard must not be over-tightened into blocking the happy path.
    const row = serverRow();
    mocked.getSettings.mockResolvedValue(row);
    mocked.putSettings.mockResolvedValue({ ...row, use_ai: false });

    const s = useSettingsStore();
    await s.load();
    expect(s.loaded).toBe(true);
    expect(s.loadError).toBeNull();

    await s.setUseAi(false);

    expect(mocked.getSettings).toHaveBeenCalledTimes(1); // no redundant re-load
    expect(mocked.putSettings).toHaveBeenCalledTimes(1);
    expect(s.useAi).toBe(false);
  });

  it('renders defaults while unloaded so the board can still paint', async () => {
    mocked.getSettings.mockRejectedValue(new Error('offline'));
    const s = useSettingsStore();
    await s.load();

    expect(s.lookbackValue).toBe(24);
    expect(s.states).toEqual(['open']);
    expect(s.loaded).toBe(false);
  });
});

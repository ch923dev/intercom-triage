// App shell boot sequence. Reference: tasks.md T200.
//
// The bug this pins: `onMounted` and the `auth.isAuthenticated` watcher BOTH
// called `loadAll()`, so every page load ran the whole bootstrap twice — 14
// requests instead of 7, and two `tickets.refresh()` calls racing. The watcher
// is now the single owner, which only works because `watch()` runs at setup,
// i.e. before `onMounted` flips the flag. That ordering is implicit, so the
// "does not load when bootstrap fails" case below is not optional: it is the
// guard against the opposite failure, where nothing loads at all.

import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount } from '@vue/test-utils';
import App from './App.vue';
import { api } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: {
    refreshSession: vi.fn(),
    getSettings: vi.fn(),
    listCategories: vi.fn(),
    listFollowups: vi.fn(),
    listNotes: vi.fn(),
    listNoteEntries: vi.fn(),
    listTickets: vi.fn(),
  },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

const mocked = vi.mocked(api);

const USER = {
  id: 1,
  onlysales_id: 'os-1',
  email: 'op@onlysales.io',
  name: 'Op',
  scope: null,
};

function resolveBootstrapCalls() {
  mocked.getSettings.mockResolvedValue({
    lookback_unit: 'hours',
    lookback_value: 24,
    states: ['open'],
    include_category_ids: null,
    mute_alarms: false,
    use_ai: true,
    ai_resolve_default: false,
    ai_resolve_confidence_threshold: 0.7,
    hide_empty_categories: true,
  });
  mocked.listCategories.mockResolvedValue({ categories: [], pending_proposals: [] });
  mocked.listFollowups.mockResolvedValue([]);
  mocked.listNotes.mockResolvedValue([]);
  mocked.listNoteEntries.mockResolvedValue([]);
  mocked.listTickets.mockResolvedValue([]);
}

describe('App boot', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
    resolveBootstrapCalls();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads the board exactly once per boot', async () => {
    mocked.refreshSession.mockResolvedValue({ access_token: 'tok', user: USER });

    const wrapper = mount(App, { shallow: true });
    await flushPromises();
    await flushPromises();

    expect(mocked.getSettings).toHaveBeenCalledTimes(1);
    expect(mocked.listCategories).toHaveBeenCalledTimes(1);
    expect(mocked.listFollowups).toHaveBeenCalledTimes(1);
    // Two calls, not four: one for the open board and one for `?resolved=true`.
    expect(mocked.listTickets).toHaveBeenCalledTimes(2);

    wrapper.unmount();
  });

  it('does not load the board when bootstrap fails', async () => {
    mocked.refreshSession.mockRejectedValue(new Error('401'));

    const wrapper = mount(App, { shallow: true });
    await flushPromises();
    await flushPromises();

    expect(mocked.getSettings).not.toHaveBeenCalled();
    expect(mocked.listTickets).not.toHaveBeenCalled();

    wrapper.unmount();
  });
});

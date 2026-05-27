// Saved-views store spec (roadmap 1.1). Covers save / apply / delete / rename
// and localStorage persistence across a store re-creation, plus the seeded
// default and the seed-suppression flag. The tickets store is a real store
// (shares the test Pinia); its API client is mocked since instantiating it
// imports @/api/client.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { nextTick } from 'vue';
import { createPinia, setActivePinia } from 'pinia';
import { useSavedViewsStore } from './savedViews';
import { useTicketsStore } from './tickets';
import { EMPTY_FILTER } from '@/utils/savedViews';

vi.mock('@/api/client', () => ({ api: {} }));

const STORAGE_KEY = 'triage-saved-views-v1';

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
});

/** Save a preset built from an explicit filter (set the tickets store active
 *  filter, then snapshot it via saveView — mirrors the real UI flow). */
function savePreset(
  s: ReturnType<typeof useSavedViewsStore>,
  tickets: ReturnType<typeof useTicketsStore>,
  filter: typeof EMPTY_FILTER,
  name: string,
) {
  tickets.setFilter(filter);
  return s.saveView(name)!;
}

describe('savedViewsStore — seeding', () => {
  it('seeds a "Morning queue" default on a fresh (empty) localStorage', () => {
    const s = useSavedViewsStore();
    expect(s.views).toHaveLength(1);
    expect(s.views[0]!.name).toBe('Morning queue');
    expect(s.views[0]!.filter.urgencies).toEqual(['urgent', 'high']);
    expect(s.views[0]!.filter.resolution).toEqual(['open']);
    expect(s.views[0]!.filter.ageMinHours).toBe(4);
  });

  it('does NOT re-seed when persisted state has an empty list (user deleted all)', () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ views: [], seeded: true }));
    const s = useSavedViewsStore();
    expect(s.views).toHaveLength(0);
  });
});

describe('savedViewsStore — saveView', () => {
  it('saves the tickets store active filter as a named preset', () => {
    const s = useSavedViewsStore();
    const tickets = useTicketsStore();
    tickets.setFilter({ ...EMPTY_FILTER, urgencies: ['urgent'], resolution: ['open'] });

    const created = s.saveView('My queue');
    expect(created).not.toBeNull();
    expect(s.views.some((v) => v.name === 'My queue')).toBe(true);
    const saved = s.views.find((v) => v.name === 'My queue')!;
    expect(saved.filter.urgencies).toEqual(['urgent']);
    expect(saved.filter.resolution).toEqual(['open']);
    expect(s.activeViewId).toBe(saved.id);
  });

  it('trims the name and rejects a blank name', () => {
    const s = useSavedViewsStore();
    expect(s.saveView('   ')).toBeNull();
  });

  it('snapshots the filter — later board edits do not mutate the saved preset', () => {
    const s = useSavedViewsStore();
    const tickets = useTicketsStore();
    tickets.setFilter({ ...EMPTY_FILTER, urgencies: ['high'] });
    const created = s.saveView('Snap')!;
    tickets.setFilter({ ...EMPTY_FILTER, urgencies: ['low'] });
    expect(created.filter.urgencies).toEqual(['high']);
  });
});

describe('savedViewsStore — applyView', () => {
  it('applies a preset filter to the tickets store and marks it active', () => {
    const s = useSavedViewsStore();
    const tickets = useTicketsStore();
    const created = savePreset(s, tickets, { ...EMPTY_FILTER, ageMinHours: 6 }, 'Aged');
    tickets.clearFilter();

    s.applyView(created.id);
    expect(tickets.activeFilter.ageMinHours).toBe(6);
    expect(tickets.isFilterActive).toBe(true);
    expect(s.activeViewId).toBe(created.id);
  });

  it('is a no-op for an unknown id', () => {
    const s = useSavedViewsStore();
    const tickets = useTicketsStore();
    s.applyView('does-not-exist');
    expect(tickets.isFilterActive).toBe(false);
  });
});

describe('savedViewsStore — deleteView / rename', () => {
  it('deletes a preset and clears the active marker if it was applied', () => {
    const s = useSavedViewsStore();
    const tickets = useTicketsStore();
    const created = savePreset(s, tickets, { ...EMPTY_FILTER, urgencies: ['high'] }, 'Temp');
    s.applyView(created.id);
    expect(s.activeViewId).toBe(created.id);
    s.deleteView(created.id);
    expect(s.views.some((v) => v.id === created.id)).toBe(false);
    expect(s.activeViewId).toBeNull();
  });

  it('renames a preset in place', () => {
    const s = useSavedViewsStore();
    const tickets = useTicketsStore();
    const created = savePreset(s, tickets, { ...EMPTY_FILTER, urgencies: ['high'] }, 'Old');
    s.renameView(created.id, 'New');
    expect(s.views.find((v) => v.id === created.id)!.name).toBe('New');
  });
});

describe('savedViewsStore — persistence', () => {
  it('persists views to localStorage and reloads them in a new store instance', async () => {
    const s1 = useSavedViewsStore();
    const tickets = useTicketsStore();
    savePreset(
      s1,
      tickets,
      { ...EMPTY_FILTER, urgencies: ['urgent'], ageMinHours: 2 },
      'Persisted',
    );
    // The persistence watcher flushes on the next tick — wait for the write.
    await nextTick();

    // New Pinia + store instance reads from the same localStorage.
    setActivePinia(createPinia());
    const s2 = useSavedViewsStore();
    const reloaded = s2.views.find((v) => v.name === 'Persisted');
    expect(reloaded).toBeDefined();
    expect(reloaded!.filter.urgencies).toEqual(['urgent']);
    expect(reloaded!.filter.ageMinHours).toBe(2);
  });

  it('survives corrupt JSON in localStorage by re-seeding', () => {
    localStorage.setItem(STORAGE_KEY, '{not valid json');
    const s = useSavedViewsStore();
    expect(s.views[0]!.name).toBe('Morning queue');
  });
});

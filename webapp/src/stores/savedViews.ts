// Saved views store (roadmap 1.1). Client-only, per-device — like `tweaks`,
// these are a local convenience, not server state, so they live in
// localStorage under their OWN key (kept separate from `triage-tweaks-v1` so
// the two evolve without colliding).
//
// This store owns the *persisted named presets* only. The *active* (ad-hoc)
// filter the board reacts to lives in the tickets store (`activeFilter`), next
// to the board data it narrows — same way DrawerFiltersSection drives the
// board via the settings store. Applying a preset here calls back into the
// tickets store to set the active filter.

import { defineStore } from 'pinia';
import { computed, ref, watch } from 'vue';
import { useTicketsStore } from '@/stores/tickets';
import { cloneFilter, type SavedFilter, type SavedView } from '@/utils/savedViews';

const STORAGE_KEY = 'triage-saved-views-v1';

/** Seeded default preset — an *example* of a "morning queue": tickets the
 *  operator should look at first thing. Urgent + high, still open, and aged at
 *  least 4 hours (i.e. waiting on a reply overnight). The operator can edit or
 *  delete it like any other preset. */
function seedViews(): SavedView[] {
  return [
    {
      id: 'seed-morning-queue',
      name: 'Morning queue',
      filter: {
        categoryIds: null,
        urgencies: ['urgent', 'high'],
        resolution: ['open'],
        ageMinHours: 4,
      },
    },
  ];
}

interface PersistedShape {
  views: SavedView[];
  /** Marks that the user has touched the list, so we don't re-seed after they
   *  deliberately delete the default down to empty. */
  seeded: boolean;
}

function loadFromStorage(): PersistedShape {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { views: seedViews(), seeded: true };
    const parsed = JSON.parse(raw) as Partial<PersistedShape>;
    return {
      views: Array.isArray(parsed.views) ? parsed.views : seedViews(),
      seeded: parsed.seeded ?? true,
    };
  } catch {
    return { views: seedViews(), seeded: true };
  }
}

let idCounter = 0;
function makeId(): string {
  idCounter += 1;
  return `view-${Date.now().toString(36)}-${idCounter}`;
}

export const useSavedViewsStore = defineStore('savedViews', () => {
  const initial = loadFromStorage();
  const views = ref<SavedView[]>(initial.views);
  const seeded = ref(initial.seeded);
  /** Id of the preset currently applied to the board, or null for an ad-hoc /
   *  no filter. Cleared whenever the active filter drifts from the preset. */
  const activeViewId = ref<string | null>(null);

  const hasViews = computed(() => views.value.length > 0);

  /** Save the tickets store's current active filter as a new named preset. */
  function saveView(name: string): SavedView | null {
    const trimmed = name.trim();
    if (!trimmed) return null;
    const tickets = useTicketsStore();
    const view: SavedView = {
      id: makeId(),
      name: trimmed,
      filter: cloneFilter(tickets.activeFilter),
    };
    views.value = [...views.value, view];
    seeded.value = true;
    activeViewId.value = view.id;
    return view;
  }

  /** Apply a saved preset to the board (sets the tickets store active filter). */
  function applyView(id: string): void {
    const view = views.value.find((v) => v.id === id);
    if (!view) return;
    const tickets = useTicketsStore();
    tickets.setFilter(cloneFilter(view.filter));
    activeViewId.value = view.id;
  }

  /** Delete a preset. Clears the active marker if it was the applied one. */
  function deleteView(id: string): void {
    views.value = views.value.filter((v) => v.id !== id);
    if (activeViewId.value === id) activeViewId.value = null;
  }

  /** Rename a preset in place. */
  function renameView(id: string, name: string): void {
    const trimmed = name.trim();
    if (!trimmed) return;
    views.value = views.value.map((v) => (v.id === id ? { ...v, name: trimmed } : v));
  }

  /** Update a preset's stored filter to the board's current active filter. */
  function updateView(id: string, filter: SavedFilter): void {
    views.value = views.value.map((v) => (v.id === id ? { ...v, filter: cloneFilter(filter) } : v));
  }

  /** Drop the active-preset marker — the board still shows whatever filter is
   *  set, but it's no longer "the morning queue preset". */
  function clearActiveView(): void {
    activeViewId.value = null;
  }

  watch(
    [views, seeded],
    () => {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ views: views.value, seeded: seeded.value } satisfies PersistedShape),
      );
    },
    { deep: true, immediate: true },
  );

  return {
    views,
    seeded,
    activeViewId,
    hasViews,
    saveView,
    applyView,
    deleteView,
    renameView,
    updateView,
    clearActiveView,
  };
});

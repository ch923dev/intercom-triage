// Filter + behavior settings store. Per tasks.md T031.
// Until T027 (backend GET/PUT /settings) lands, persists to localStorage with
// the same shape so the API swap later is a one-line change in `load`/`save`.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import type { FilterSettings, LookbackUnit, TicketState } from '@/types/api';

const STORAGE_KEY = 'triage-filter-v1';

const DEFAULTS: FilterSettings = {
  lookback_unit: 'hours',
  lookback_value: 24,
  states: ['open'],
  include_category_ids: null,
};

function load(): FilterSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<FilterSettings>) };
  } catch {
    return DEFAULTS;
  }
}

function save(s: FilterSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
}

export const useSettingsStore = defineStore('settings', () => {
  const state = ref<FilterSettings>(load());

  const filter = computed(() => state.value);
  const lookbackValue = computed(() => state.value.lookback_value);
  const lookbackUnit = computed(() => state.value.lookback_unit);
  const states = computed(() => state.value.states);
  const includedCategoryIds = computed(() => state.value.include_category_ids);

  function setLookback(value: number, unit: LookbackUnit) {
    state.value = { ...state.value, lookback_value: value, lookback_unit: unit };
    save(state.value);
  }
  function toggleState(s: TicketState) {
    const set = new Set(state.value.states);
    if (set.has(s)) set.delete(s);
    else set.add(s);
    state.value = { ...state.value, states: [...set] };
    save(state.value);
  }
  function setIncludedCategoryIds(ids: number[] | null) {
    state.value = { ...state.value, include_category_ids: ids };
    save(state.value);
  }

  return {
    filter,
    lookbackValue,
    lookbackUnit,
    states,
    includedCategoryIds,
    setLookback,
    toggleState,
    setIncludedCategoryIds,
  };
});

// Filter settings store. Per tasks.md T031 / T035.
// Server-backed: reads `GET /settings`, writes `PUT /settings`. The backend
// owns the singleton row, so reloading the page restores the same filter.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { FilterSettings, LookbackUnit, TicketState } from '@/types/api';

const DEFAULTS: FilterSettings = {
  lookback_unit: 'hours',
  lookback_value: 24,
  states: ['open'],
  include_category_ids: null,
  mute_alarms: false,
};

export const useSettingsStore = defineStore('settings', () => {
  const state = ref<FilterSettings>({ ...DEFAULTS });
  const loaded = ref(false);
  const saving = ref(false);

  const filter = computed(() => state.value);
  const lookbackValue = computed(() => state.value.lookback_value);
  const lookbackUnit = computed(() => state.value.lookback_unit);
  const states = computed(() => state.value.states);
  const includedCategoryIds = computed(() => state.value.include_category_ids);
  const muteAlarms = computed(() => state.value.mute_alarms);

  /** Load the stored filter. Falls back to defaults if the backend is down. */
  async function load() {
    try {
      state.value = await api.getSettings();
    } catch {
      state.value = { ...DEFAULTS };
    } finally {
      loaded.value = true;
    }
  }

  /** Persist a partial change and adopt the server's canonical response. */
  async function update(patch: Partial<FilterSettings>) {
    const next = { ...state.value, ...patch };
    saving.value = true;
    try {
      state.value = await api.putSettings(next);
    } finally {
      saving.value = false;
    }
  }

  function setLookback(value: number, unit: LookbackUnit) {
    return update({ lookback_value: value, lookback_unit: unit });
  }

  function toggleState(s: TicketState) {
    const set = new Set(state.value.states);
    if (set.has(s)) set.delete(s);
    else set.add(s);
    return update({ states: [...set] });
  }

  function setIncludedCategoryIds(ids: number[] | null) {
    return update({ include_category_ids: ids });
  }

  /** FR-024 — the mute flag lives in the server settings row so the popup
   *  sees the same value the webapp wrote. */
  function setMuteAlarms(v: boolean) {
    return update({ mute_alarms: v });
  }

  return {
    filter,
    loaded,
    saving,
    lookbackValue,
    lookbackUnit,
    states,
    includedCategoryIds,
    muteAlarms,
    load,
    update,
    setLookback,
    toggleState,
    setIncludedCategoryIds,
    setMuteAlarms,
  };
});

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
  use_ai: true,
  ai_resolve_default: false,
  ai_resolve_confidence_threshold: 0.7,
  hide_empty_categories: true,
};

export const useSettingsStore = defineStore('settings', () => {
  const state = ref<FilterSettings>({ ...DEFAULTS });
  const saving = ref(false);

  const lookbackValue = computed(() => state.value.lookback_value);
  const lookbackUnit = computed(() => state.value.lookback_unit);
  const states = computed(() => state.value.states);
  const includedCategoryIds = computed(() => state.value.include_category_ids);
  const muteAlarms = computed(() => state.value.mute_alarms);
  const useAi = computed(() => state.value.use_ai);
  const aiResolveDefault = computed(() => state.value.ai_resolve_default);
  const aiResolveConfidenceThreshold = computed(() => state.value.ai_resolve_confidence_threshold);
  const hideEmptyCategories = computed(() => state.value.hide_empty_categories);

  /** Load the stored filter. Falls back to defaults if the backend is down. */
  async function load() {
    try {
      state.value = await api.getSettings();
    } catch {
      state.value = { ...DEFAULTS };
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

  /** FR-024 — the mute flag lives in the server settings row so it persists
   *  across reloads and both views read the same value. */
  function setMuteAlarms(v: boolean) {
    return update({ mute_alarms: v });
  }

  /** Toggle AI categorization. Affects future ingests only — the stored board
   *  is left as-is, so no board refresh is needed here. */
  function setUseAi(v: boolean) {
    return update({ use_ai: v });
  }

  /** Global default for AI-powered resolution suggestions. */
  function setAiResolveDefault(v: boolean) {
    return update({ ai_resolve_default: v });
  }

  /** Confidence threshold (0..1) the AI verdict must meet. */
  function setAiResolveConfidenceThreshold(v: number) {
    return update({ ai_resolve_confidence_threshold: v });
  }

  /** Toggle hiding of empty category columns on the Board. */
  function setHideEmptyCategories(v: boolean) {
    return update({ hide_empty_categories: v });
  }

  return {
    saving,
    lookbackValue,
    lookbackUnit,
    states,
    includedCategoryIds,
    muteAlarms,
    useAi,
    aiResolveDefault,
    aiResolveConfidenceThreshold,
    hideEmptyCategories,
    load,
    update,
    setLookback,
    toggleState,
    setIncludedCategoryIds,
    setMuteAlarms,
    setUseAi,
    setAiResolveDefault,
    setAiResolveConfidenceThreshold,
    setHideEmptyCategories,
  };
});

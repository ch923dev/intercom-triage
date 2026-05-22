// Tweaks (display preferences) store. Per plan §8b — dark mode, accent,
// density, show summary, show confidence. These are per-device display
// choices and stay in localStorage. The sixth tweak — mute alarms — lives in
// the server settings row instead (FR-024) so the popup shares it; see the
// `settings` store's `muteAlarms`.

import { defineStore } from 'pinia';
import { computed, ref, watch } from 'vue';
import type { Density } from '@/types/api';

const STORAGE_KEY = 'triage-tweaks-v1';

interface TweaksState {
  darkMode: boolean;
  accent: string;
  density: Density;
  showSummary: boolean;
  showConfidence: boolean;
}

const DEFAULTS: TweaksState = {
  darkMode: false,
  accent: '#ff4d2e',
  density: 'balanced',
  showSummary: true,
  showConfidence: true,
};

const ACCENT_SWATCHES = ['#ff4d2e', '#2e7fff', '#22a06b', '#a855f7', '#111111'] as const;

function loadFromStorage(): TweaksState {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULTS;
    return { ...DEFAULTS, ...(JSON.parse(raw) as Partial<TweaksState>) };
  } catch {
    return DEFAULTS;
  }
}

export const useTweaksStore = defineStore('tweaks', () => {
  const state = ref<TweaksState>(loadFromStorage());

  const darkMode = computed(() => state.value.darkMode);
  const accent = computed(() => state.value.accent);
  const density = computed(() => state.value.density);
  const showSummary = computed(() => state.value.showSummary);
  const showConfidence = computed(() => state.value.showConfidence);

  function setDarkMode(v: boolean) {
    state.value.darkMode = v;
  }
  function setAccent(v: string) {
    state.value.accent = v;
  }
  function setDensity(v: Density) {
    state.value.density = v;
  }
  function setShowSummary(v: boolean) {
    state.value.showSummary = v;
  }
  function setShowConfidence(v: boolean) {
    state.value.showConfidence = v;
  }

  // Persist + apply to <html>.
  watch(
    state,
    (next) => {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
      const root = document.documentElement;
      root.setAttribute('data-theme', next.darkMode ? 'dark' : 'light');
      root.style.setProperty('--accent', next.accent);
    },
    { deep: true, immediate: true },
  );

  return {
    darkMode,
    accent,
    density,
    showSummary,
    showConfidence,
    setDarkMode,
    setAccent,
    setDensity,
    setShowSummary,
    setShowConfidence,
    ACCENT_SWATCHES,
  };
});

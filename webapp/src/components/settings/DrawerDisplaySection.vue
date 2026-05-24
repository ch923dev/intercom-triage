<script setup lang="ts">
import Mono from '../Mono.vue';
import { useSettingsStore } from '@/stores/settings';
import { useTweaksStore } from '@/stores/tweaks';
import type { Density } from '@/types/api';

const settings = useSettingsStore();
const tweaks = useTweaksStore();

const densities: Density[] = ['compact', 'balanced', 'comfy'];
const DENSITY_LABEL: Record<Density, string> = {
  compact: 'Compact',
  balanced: 'Balanced',
  comfy: 'Comfy',
};
</script>

<template>
  <section>
    <Mono>Density</Mono>
    <div class="seg">
      <button
        v-for="d in densities"
        :key="d"
        :class="{ active: tweaks.density === d }"
        @click="tweaks.setDensity(d)"
      >
        {{ DENSITY_LABEL[d] }}
      </button>
    </div>

    <Mono>Card content</Mono>
    <label class="check">
      <input
        type="checkbox"
        :checked="tweaks.showSummary"
        @change="tweaks.setShowSummary(($event.target as HTMLInputElement).checked)"
      />
      <span class="sentence">Show AI summary on cards</span>
    </label>
    <label class="check">
      <input
        type="checkbox"
        :checked="tweaks.showConfidence"
        @change="tweaks.setShowConfidence(($event.target as HTMLInputElement).checked)"
      />
      <span class="sentence">Show AI confidence on cards</span>
    </label>

    <Mono>Accent color</Mono>
    <div class="swatches">
      <button
        v-for="c in tweaks.ACCENT_SWATCHES"
        :key="c"
        :class="{ active: tweaks.accent === c }"
        :style="{ background: c }"
        :title="`Accent ${c}`"
        @click="tweaks.setAccent(c)"
      />
    </div>

    <Mono>Theme</Mono>
    <div class="seg">
      <button :class="{ active: !tweaks.darkMode }" @click="tweaks.setDarkMode(false)">Light</button>
      <button :class="{ active: tweaks.darkMode }" @click="tweaks.setDarkMode(true)">Dark</button>
    </div>

    <Mono>Alarms</Mono>
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.muteAlarms"
        @change="settings.setMuteAlarms(($event.target as HTMLInputElement).checked)"
      />
      <span class="sentence">Mute alarm audio (banner still shows)</span>
    </label>
  </section>
</template>

<style scoped>
section {
  padding: 16px 0;
  border-bottom: var(--hairline) solid var(--line-soft);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ink);
  text-transform: capitalize;
  cursor: pointer;
}
.check .sentence {
  text-transform: none;
}
.seg {
  display: inline-flex;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  overflow: hidden;
}
.seg button {
  padding: 5px 12px;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 12px;
}
.seg button.active {
  background: var(--ink);
  color: var(--bg);
}
.swatches {
  display: flex;
  gap: 6px;
}
.swatches button {
  width: 16px;
  height: 16px;
  border-radius: 3px;
  border: var(--hairline) solid var(--line);
  cursor: pointer;
  padding: 0;
}
.swatches button.active {
  outline: 2px solid var(--ink);
  outline-offset: 1px;
}
</style>

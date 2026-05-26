<script setup lang="ts">
import Mono from '../Mono.vue';
import { useSettingsStore } from '@/stores/settings';

const settings = useSettingsStore();

function onToggleUseAi(event: Event) {
  void settings.setUseAi((event.target as HTMLInputElement).checked);
}

function onToggleAiResolveDefault(event: Event) {
  void settings.setAiResolveDefault((event.target as HTMLInputElement).checked);
}

function onConfidenceThreshold(event: Event) {
  const v = parseFloat((event.target as HTMLInputElement).value);
  if (!isNaN(v)) void settings.setAiResolveConfidenceThreshold(v);
}
</script>

<template>
  <section>
    <Mono>AI categorization</Mono>
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.useAi"
        :disabled="settings.saving"
        @change="onToggleUseAi"
      />
      <span class="sentence">Use AI to categorize &amp; summarize</span>
    </label>
    <p class="hint">
      When off, synced tickets land in the fallback category with no AI
      subject or summary — set those yourself on each ticket.
    </p>
  </section>

  <section>
    <Mono>Auto-resolve</Mono>
    <label class="check">
      <input
        type="checkbox"
        :checked="settings.aiResolveDefault"
        :disabled="settings.saving || !settings.useAi"
        @change="onToggleAiResolveDefault"
      />
      <span class="sentence">Let AI close resolved + non-actionable tickets</span>
    </label>
    <p v-if="!settings.useAi" class="hint">
      Enable AI categorization (above) to use auto-resolve suggestions.
    </p>
    <label class="slider-row">
      <span class="mono sentence">Confidence threshold</span>
      <input
        type="range"
        min="0.5"
        max="0.95"
        step="0.05"
        :value="settings.aiResolveConfidenceThreshold"
        :disabled="settings.saving || !settings.useAi"
        @change="onConfidenceThreshold"
      />
      <span class="mono threshold-val">{{ settings.aiResolveConfidenceThreshold.toFixed(2) }}</span>
    </label>
    <p class="hint">
      When AI confidence ≥ threshold, tickets the AI judges resolved or
      non-actionable are closed automatically. AI never closes other tickets
      without your confirmation.
    </p>
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
.hint {
  margin: 0;
  font-size: 11px;
  color: var(--ink-3);
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
.slider-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.slider-row input[type='range'] {
  flex: 1;
  min-width: 80px;
  accent-color: var(--accent);
}
.threshold-val {
  font-size: 11px;
  color: var(--ink-2);
  min-width: 28px;
  text-align: right;
}
</style>

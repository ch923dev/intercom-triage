<!-- Top bar — wordmark + ticket count + tweaks toggles.
     Recency slider + filter drawer land in T035; for the scaffold we just
     surface the four tweaks affecting the current card rendering. -->
<script setup lang="ts">
import { computed } from 'vue';
import Mono from './Mono.vue';
import { useTicketsStore } from '@/stores/tickets';
import { useTweaksStore } from '@/stores/tweaks';
import type { Density } from '@/types/api';

const tickets = useTicketsStore();
const tweaks = useTweaksStore();

const densities: Density[] = ['compact', 'balanced', 'comfy'];

const lastSync = computed(() => {
  const t = tickets.lastRefresh;
  if (!t) return 'never';
  const s = Math.floor((Date.now() - t.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
});

function toggleDark() {
  tweaks.setDarkMode(!tweaks.darkMode);
}
</script>

<template>
  <header class="topbar">
    <div class="brand">
      <div class="dot" />
      <span class="wordmark">Triage</span>
      <Mono :size="10">v0.1</Mono>
    </div>

    <div class="sep" />

    <Mono>{{ tickets.tickets.length }} tickets</Mono>

    <div v-if="tickets.isMock" class="badge mock">
      <Mono :color="'var(--accent)'">Mock data — backend /tickets/fetch pending T025</Mono>
    </div>

    <div class="spacer" />

    <!-- Density picker -->
    <div class="seg">
      <button
        v-for="d in densities"
        :key="d"
        :class="{ active: tweaks.density === d }"
        @click="tweaks.setDensity(d)"
      >
        <span class="mono">{{ d.slice(0, 1).toUpperCase() }}</span>
      </button>
    </div>

    <!-- Toggles -->
    <button class="ghost" :class="{ active: tweaks.showSummary }" @click="tweaks.setShowSummary(!tweaks.showSummary)">
      <span class="mono">Summary</span>
    </button>
    <button class="ghost" :class="{ active: tweaks.showConfidence }" @click="tweaks.setShowConfidence(!tweaks.showConfidence)">
      <span class="mono">Conf</span>
    </button>

    <!-- Accent picker -->
    <div class="swatches">
      <button
        v-for="c in tweaks.ACCENT_SWATCHES"
        :key="c"
        :class="{ active: tweaks.accent === c }"
        :style="{ background: c }"
        @click="tweaks.setAccent(c)"
        :title="`Accent ${c}`"
      />
    </div>

    <button class="ghost" @click="toggleDark">
      <span class="mono">{{ tweaks.darkMode ? 'Light' : 'Dark' }}</span>
    </button>

    <Mono>· last sync {{ lastSync }}</Mono>
  </header>
</template>

<style scoped>
.topbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  border-bottom: var(--hairline) solid var(--line);
  background: var(--bg);
  flex: 0 0 auto;
}
.brand {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.brand .dot {
  width: 8px;
  height: 8px;
  background: var(--accent);
}
.wordmark {
  font-family: var(--font-mono);
  font-size: 12px;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--ink);
  font-weight: 600;
}
.sep {
  width: 1px;
  height: 18px;
  background: var(--line);
}
.spacer {
  flex: 1;
}
.badge.mock {
  padding: 2px 8px;
  border: var(--hairline) solid var(--accent);
  border-radius: 2px;
  background: var(--accent-soft);
}
.seg {
  display: inline-flex;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  overflow: hidden;
}
.seg button {
  padding: 4px 8px;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}
.seg button.active {
  background: var(--ink);
  color: var(--bg);
}
.ghost {
  padding: 4px 10px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}
.ghost.active {
  background: var(--ink);
  color: var(--bg);
  border-color: var(--ink);
}
.swatches {
  display: flex;
  gap: 5px;
}
.swatches button {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  border: var(--hairline) solid var(--line);
  cursor: pointer;
  padding: 0;
}
.swatches button.active {
  outline: 2px solid var(--ink);
  outline-offset: 1px;
}
</style>

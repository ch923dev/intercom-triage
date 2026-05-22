<!-- Top bar — wordmark, page nav, refresh, display tweaks, settings.
     Reference: tasks.md T036 (refresh + last-refreshed), T035 (settings entry). -->
<script setup lang="ts">
import { computed } from 'vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useTweaksStore } from '@/stores/tweaks';
import { useViewStore } from '@/stores/view';
import type { View } from '@/stores/view';
import type { Density } from '@/types/api';

const tickets = useTicketsStore();
const tweaks = useTweaksStore();
const settings = useSettingsStore();
const categories = useCategoriesStore();
const followups = useFollowupsStore();
const view = useViewStore();

const densities: Density[] = ['compact', 'balanced', 'comfy'];
const NAV: { id: View; label: string }[] = [
  { id: 'board', label: 'Board' },
  { id: 'categories', label: 'Categories' },
  { id: 'proposals', label: 'Proposals' },
];

const lastSync = computed(() => {
  const t = tickets.lastRefresh;
  if (!t) return 'never';
  const s = Math.floor((Date.now() - t.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
});

const proposalCount = computed(() => categories.pendingProposals.length);

function refresh() {
  void tickets.refresh(settings.filter);
}

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

    <!-- Page nav -->
    <nav class="seg">
      <button
        v-for="n in NAV"
        :key="n.id"
        :class="{ active: view.view === n.id }"
        @click="view.go(n.id)"
      >
        <span class="mono">{{ n.label }}</span>
        <span v-if="n.id === 'proposals' && proposalCount" class="nav-badge">{{
          proposalCount
        }}</span>
      </button>
    </nav>

    <div class="sep" />

    <Mono>{{ tickets.tickets.length }} tickets</Mono>

    <!-- Follow-up status pill (T051) — accent-pulse while an alarm is firing. -->
    <button
      v-if="followups.pendingCount > 0"
      class="pill"
      :class="{ firing: followups.firing }"
      title="Pending follow-ups"
    >
      <span class="mono"
        >{{ followups.pendingCount }} follow-up{{ followups.pendingCount === 1 ? '' : 's' }}</span
      >
    </button>

    <div v-if="tickets.isMock" class="badge mock">
      <Mono :color="'var(--accent)'">Sample data — /tickets/fetch unavailable</Mono>
    </div>

    <div class="spacer" />

    <!-- Refresh (T036) -->
    <button class="ghost" :disabled="tickets.loading" @click="refresh">
      <span class="mono">{{ tickets.loading ? 'Refreshing…' : 'Refresh' }}</span>
    </button>
    <Mono>{{ lastSync }}</Mono>

    <div class="sep" />

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

    <button
      class="ghost"
      :class="{ active: tweaks.showSummary }"
      @click="tweaks.setShowSummary(!tweaks.showSummary)"
    >
      <span class="mono">Summary</span>
    </button>
    <button
      class="ghost"
      :class="{ active: tweaks.showConfidence }"
      @click="tweaks.setShowConfidence(!tweaks.showConfidence)"
    >
      <span class="mono">Conf</span>
    </button>

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

    <button
      class="ghost"
      :class="{ active: settings.muteAlarms }"
      title="Mute the alarm audio cue (the banner still shows)"
      @click="settings.setMuteAlarms(!settings.muteAlarms)"
    >
      <span class="mono">{{ settings.muteAlarms ? 'Muted' : 'Mute' }}</span>
    </button>

    <button class="ghost" @click="toggleDark">
      <span class="mono">{{ tweaks.darkMode ? 'Light' : 'Dark' }}</span>
    </button>

    <!-- Settings drawer (T035) -->
    <button class="ghost" title="Filter settings" @click="view.openDrawer()">
      <span class="mono">Settings</span>
    </button>
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
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
}
.seg button.active {
  background: var(--ink);
  color: var(--bg);
}
.nav-badge {
  font-family: var(--font-mono);
  font-size: 9px;
  padding: 0 4px;
  border-radius: var(--radius-pill);
  background: var(--accent);
  color: #fff;
  line-height: 14px;
}
.ghost {
  padding: 4px 10px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}
.ghost:disabled {
  opacity: 0.5;
  cursor: default;
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
.pill {
  padding: 3px 9px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-pill);
  background: var(--chip-bg);
  color: var(--ink-2);
  cursor: default;
}
.pill.firing {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
  animation: triagePulse 1.4s ease-in-out infinite;
}
</style>

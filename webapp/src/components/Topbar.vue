<!-- Top bar — wordmark, page nav, search, refresh, settings.
     Display tweaks (density / theme / accent / mute / summary / confidence)
     now live in the Settings drawer so the topbar stays scannable and the
     search input has room to breathe.
     Reference: tasks.md T036 (refresh + last-refreshed), T035 (settings entry). -->
<script setup lang="ts">
import { computed } from 'vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useSavedViewsStore } from '@/stores/savedViews';
import { useTicketsStore } from '@/stores/tickets';
import { useTweaksStore } from '@/stores/tweaks';
import { useViewStore } from '@/stores/view';
import type { View } from '@/stores/view';

const tickets = useTicketsStore();
const tweaks = useTweaksStore();
const categories = useCategoriesStore();
const followups = useFollowupsStore();
const savedViews = useSavedViewsStore();
const view = useViewStore();

const NAV: { id: View; label: string }[] = [
  { id: 'board', label: 'Board' },
  { id: 'followups', label: 'Follow-ups' },
  { id: 'categories', label: 'Categories' },
  { id: 'proposals', label: 'Proposals' },
  { id: 'playbooks', label: 'Playbooks' },
  { id: 'snippets', label: 'Snippets' },
];

const lastSync = computed(() => {
  const t = tickets.lastRefresh;
  if (!t) return 'never';
  const s = Math.floor((Date.now() - t.getTime()) / 1000);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  return `${Math.floor(s / 3600)}h ago`;
});

/** Faint auto-sync indicator appended to the last-sync timestamp.
 *  Shows the active interval label (e.g. "· auto · 30s") when polling is on. */
const autoSyncLabel = computed(() => {
  const s = tweaks.autoSyncSeconds;
  if (!s) return '';
  if (s < 60) return `· auto · ${s}s`;
  return `· auto · ${s / 60}m`;
});

/** Ticket count display. Shows "visible of total" when a query is active,
 *  plain count otherwise. */
const ticketCountLabel = computed(() => {
  const q = tickets.query.trim();
  if (!q) return `${tickets.tickets.length} tickets`;
  return `${tickets.visibleTickets.length} of ${tickets.tickets.length}`;
});

const proposalCount = computed(() => categories.pendingProposals.length);

function refresh() {
  void tickets.refresh();
}

function onSearchInput(e: Event) {
  tickets.setQuery((e.target as HTMLInputElement).value);
}

/** One-click saved-view apply (roadmap 1.1). `__clear__` resets to no filter;
 *  any other value applies that preset to the board. */
function onViewPick(e: Event) {
  const value = (e.target as HTMLSelectElement).value;
  if (value === '__clear__') {
    tickets.clearFilter();
    savedViews.clearActiveView();
    return;
  }
  if (value) savedViews.applyView(value);
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
        <span v-else-if="n.id === 'followups' && followups.pendingCount" class="nav-badge">{{
          followups.pendingCount
        }}</span>
      </button>
    </nav>

    <div class="sep" />

    <!-- Search input. Wrapped in a label so the magnifier glyph is part of the
         clickable hit-target. The `.search-input` class is preserved so the
         App.vue `/` shortcut (querySelector('.search-input')) still works. -->
    <label class="search" :class="{ active: !!tickets.query }">
      <span class="search-icon" aria-hidden="true">⌕</span>
      <input
        class="search-input"
        type="search"
        placeholder="Search tickets…"
        :value="tickets.query"
        @input="onSearchInput"
      />
      <span v-if="!tickets.query" class="search-kbd" aria-hidden="true">/</span>
    </label>

    <!-- Saved views quick-apply (roadmap 1.1) — one-click preset apply. The
         full editor (build / save / delete) lives in the Settings drawer. -->
    <label class="views-pick" :class="{ active: tickets.isFilterActive }">
      <select
        class="views-select"
        :value="savedViews.activeViewId ?? (tickets.isFilterActive ? '' : '__clear__')"
        title="Saved views"
        @change="onViewPick"
      >
        <option value="__clear__">All tickets</option>
        <option v-if="tickets.isFilterActive && !savedViews.activeViewId" value="" disabled>
          Custom filter…
        </option>
        <option v-for="v in savedViews.views" :key="v.id" :value="v.id">{{ v.name }}</option>
      </select>
    </label>

    <Mono>{{ ticketCountLabel }}</Mono>

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

    <div class="spacer" />

    <!-- Refresh (T036) -->
    <button class="ghost" :disabled="tickets.loading" @click="refresh">
      <span class="mono">{{ tickets.loading ? 'Refreshing…' : 'Refresh' }}</span>
    </button>
    <Mono
      >{{ lastSync }}<span v-if="autoSyncLabel" class="auto-label">{{ autoSyncLabel }}</span></Mono
    >

    <div class="sep" />

    <!-- Settings drawer (T035) — display tweaks now live inside it. -->
    <button class="ghost" title="Filter & display settings" @click="view.openDrawer()">
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
/* Search — the label is the visual chip; the input inside is borderless. */
.search {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  width: 320px;
  padding: 4px 10px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  transition:
    border-color 80ms ease,
    background 80ms ease;
}
.search:focus-within {
  border-color: var(--accent);
  background: var(--bg);
}
.search.active {
  border-color: var(--accent);
}
.search-icon {
  font-size: 14px;
  color: var(--ink-3);
  line-height: 1;
}
.search-input {
  flex: 1;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 11px;
  min-width: 0;
}
.search-input::placeholder {
  color: var(--ink-3);
}
.search-input::-webkit-search-cancel-button {
  cursor: pointer;
}
.search-kbd {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-3);
  padding: 1px 5px;
  border: var(--hairline) solid var(--line);
  border-radius: 3px;
  background: var(--bg);
  line-height: 1.2;
}
/* Faint auto-sync indicator appended to the last-sync timestamp. */
.auto-label {
  opacity: 0.55;
  margin-left: 2px;
}
/* Saved-views quick-apply select — styled as a chip to match the topbar. */
.views-pick {
  display: inline-flex;
  align-items: center;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
}
.views-pick.active {
  border-color: var(--accent);
}
.views-select {
  border: 0;
  background: transparent;
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 4px 8px;
  cursor: pointer;
  outline: none;
  max-width: 160px;
}
.views-pick.active .views-select {
  color: var(--accent);
}
</style>

<!-- Saved views / smart filters (roadmap 1.1). Lets the operator build an
     ad-hoc client-side filter over {category, urgency, resolution, age}, apply
     it to the board live, save it as a named preset, and re-apply / delete
     presets later. Server-side lookback/state filtering stays in
     DrawerFiltersSection; this layers on top of the loaded board.

     The active filter lives in the tickets store (`activeFilter`), so editing
     here narrows the board immediately. Presets persist in the savedViews
     store (localStorage `triage-saved-views-v1`). -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import CatDot from '../CatDot.vue';
import Mono from '../Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useSavedViewsStore } from '@/stores/savedViews';
import { useTicketsStore } from '@/stores/tickets';
import type { AIPriority } from '@/types/api';
import {
  RESOLUTION_FACETS,
  URGENCIES,
  cloneFilter,
  isEmptyFilter,
  type ResolutionFacet,
  type SavedFilter,
} from '@/utils/savedViews';

const tickets = useTicketsStore();
const savedViews = useSavedViewsStore();
const categories = useCategoriesStore();

const newName = ref('');

const filter = computed(() => tickets.activeFilter);
const isActive = computed(() => tickets.isFilterActive);

const RESOLUTION_LABELS: Record<ResolutionFacet, string> = {
  open: 'open',
  manual: 'resolved (manual)',
  intercom_closed: 'closed in Intercom',
  ai_resolved: 'AI-resolved',
  non_actionable: 'non-actionable',
};

/** Write a mutated copy of the active filter back to the store. Editing the
 *  active filter detaches it from any applied preset, so clear the marker. */
function patch(next: SavedFilter) {
  tickets.setFilter(next);
  savedViews.clearActiveView();
}

function toggleUrgency(u: AIPriority) {
  const set = new Set(filter.value.urgencies);
  if (set.has(u)) set.delete(u);
  else set.add(u);
  patch({ ...cloneFilter(filter.value), urgencies: [...set] });
}

function toggleResolution(r: ResolutionFacet) {
  const set = new Set(filter.value.resolution);
  if (set.has(r)) set.delete(r);
  else set.add(r);
  patch({ ...cloneFilter(filter.value), resolution: [...set] });
}

const allCategories = computed(() => filter.value.categoryIds === null);

function setAllCategories() {
  patch({ ...cloneFilter(filter.value), categoryIds: null });
}
function pickSpecificCategories() {
  patch({ ...cloneFilter(filter.value), categoryIds: categories.categories.map((c) => c.id) });
}
function isCategoryIncluded(id: number): boolean {
  const ids = filter.value.categoryIds;
  return ids !== null && ids.includes(id);
}
function toggleCategory(id: number) {
  const current = filter.value.categoryIds ?? categories.categories.map((c) => c.id);
  const set = new Set(current);
  if (set.has(id)) set.delete(id);
  else set.add(id);
  patch({ ...cloneFilter(filter.value), categoryIds: [...set] });
}

function onAge(event: Event) {
  const raw = (event.target as HTMLInputElement).value.trim();
  if (raw === '') {
    patch({ ...cloneFilter(filter.value), ageMinHours: null });
    return;
  }
  const n = Math.max(0, Number(raw) || 0);
  patch({ ...cloneFilter(filter.value), ageMinHours: n });
}

function clearFilter() {
  tickets.clearFilter();
  savedViews.clearActiveView();
}

function saveView() {
  const created = savedViews.saveView(newName.value);
  if (created) newName.value = '';
}

const canSave = computed(() => newName.value.trim().length > 0 && !isEmptyFilter(filter.value));
</script>

<template>
  <section>
    <Mono>Saved views</Mono>

    <!-- Presets list -->
    <div v-if="savedViews.hasViews" class="views">
      <div
        v-for="v in savedViews.views"
        :key="v.id"
        class="view-row"
        :class="{ active: savedViews.activeViewId === v.id }"
      >
        <button class="apply" :title="`Apply ${v.name}`" @click="savedViews.applyView(v.id)">
          {{ v.name }}
        </button>
        <button class="del" :title="`Delete ${v.name}`" @click="savedViews.deleteView(v.id)">
          ✕
        </button>
      </div>
    </div>
    <p v-else class="hint">No saved views yet. Build a filter below, then save it.</p>

    <!-- Save current filter -->
    <div class="save-row">
      <input
        v-model="newName"
        class="name"
        type="text"
        placeholder="Name this view…"
        @keyup.enter="saveView"
      />
      <button class="link" :disabled="!canSave" @click="saveView">Save current</button>
    </div>
    <p v-if="isActive" class="hint clear-row">
      Filter active.
      <button class="link inline" @click="clearFilter">Clear</button>
    </p>
  </section>

  <section>
    <Mono>Urgency</Mono>
    <div class="chips">
      <button
        v-for="u in URGENCIES"
        :key="u"
        class="chip"
        :class="{ on: filter.urgencies.includes(u) }"
        @click="toggleUrgency(u)"
      >
        {{ u }}
      </button>
    </div>
    <p class="hint">No selection = any urgency.</p>
  </section>

  <section>
    <Mono>Resolution</Mono>
    <label v-for="r in RESOLUTION_FACETS" :key="r" class="check">
      <input
        type="checkbox"
        :checked="filter.resolution.includes(r)"
        @change="toggleResolution(r)"
      />
      <span class="sentence">{{ RESOLUTION_LABELS[r] }}</span>
    </label>
    <p class="hint">No selection = any state.</p>
  </section>

  <section>
    <Mono>Age threshold</Mono>
    <div class="row">
      <input
        class="num"
        type="number"
        min="0"
        placeholder="any"
        :value="filter.ageMinHours ?? ''"
        @change="onAge"
      />
      <span class="hint">hours since last customer message</span>
    </div>
    <p class="hint">Blank = any age. Filters to tickets aged at least this long.</p>
  </section>

  <section>
    <Mono>Categories</Mono>
    <label class="check">
      <input type="radio" :checked="allCategories" @change="setAllCategories" />
      <span>All categories</span>
    </label>
    <div v-if="!allCategories" class="cat-list">
      <label v-for="c in categories.categories" :key="c.id" class="check indent">
        <input type="checkbox" :checked="isCategoryIncluded(c.id)" @change="toggleCategory(c.id)" />
        <CatDot :color="c.color" :size="8" />
        <span>{{ c.name }}</span>
      </label>
    </div>
    <button v-else class="link" @click="pickSpecificCategories">Pick specific categories…</button>
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
.views {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.view-row {
  display: flex;
  align-items: center;
  gap: 6px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  overflow: hidden;
}
.view-row.active {
  border-color: var(--accent);
}
.view-row .apply {
  flex: 1;
  text-align: left;
  padding: 6px 10px;
  border: 0;
  background: transparent;
  color: var(--ink);
  cursor: pointer;
  font-size: 12.5px;
}
.view-row.active .apply {
  color: var(--accent);
}
.view-row .del {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  padding: 6px 10px;
  font-size: 11px;
}
.view-row .del:hover {
  color: var(--accent);
}
.save-row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.name {
  flex: 1;
  padding: 5px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink);
  font-size: 12px;
  min-width: 0;
}
.num {
  width: 72px;
  padding: 5px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-mono);
}
.row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.chip {
  padding: 4px 10px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-pill);
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 12px;
  text-transform: capitalize;
}
.chip.on {
  background: var(--ink);
  color: var(--bg);
  border-color: var(--ink);
}
.hint {
  margin: 0;
  font-size: 11px;
  color: var(--ink-3);
}
.clear-row {
  display: flex;
  align-items: center;
  gap: 6px;
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
.check.indent {
  padding-left: 4px;
}
.check .sentence {
  text-transform: none;
}
.cat-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.link {
  align-self: flex-start;
  border: 0;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.link:disabled {
  opacity: 0.45;
  cursor: default;
}
.link.inline {
  align-self: auto;
}
</style>

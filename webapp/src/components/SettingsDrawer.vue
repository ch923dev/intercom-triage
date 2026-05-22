<!-- Settings drawer. Reference: tasks.md T035 — US-001, US-007, FR-011/012.
     Lookback window, conversation states, and which categories the board
     includes. Every change is persisted via `/settings` and re-fetches the
     board so the filter takes effect immediately. -->
<script setup lang="ts">
import { computed } from 'vue';
import CatDot from './CatDot.vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import type { LookbackUnit, TicketState } from '@/types/api';

const settings = useSettingsStore();
const tickets = useTicketsStore();
const categories = useCategoriesStore();
const view = useViewStore();

const STATES: TicketState[] = ['open', 'snoozed', 'closed'];
const UNITS: LookbackUnit[] = ['hours', 'days'];

/** Run a settings mutation, then refresh the board against the new filter. */
async function apply(mutate: () => Promise<void>) {
  await mutate();
  await tickets.refresh(settings.filter);
}

function onUnit(unit: LookbackUnit) {
  void apply(() => settings.setLookback(settings.lookbackValue, unit));
}

function onValue(event: Event) {
  const raw = Number((event.target as HTMLInputElement).value);
  const clamped = Math.min(720, Math.max(1, Math.round(raw || 1)));
  void apply(() => settings.setLookback(clamped, settings.lookbackUnit));
}

function onToggleState(s: TicketState) {
  void apply(() => settings.toggleState(s));
}

const allCategories = computed(() => settings.includedCategoryIds === null);

function setAllCategories() {
  void apply(() => settings.setIncludedCategoryIds(null));
}

function isIncluded(id: number): boolean {
  const ids = settings.includedCategoryIds;
  return ids === null || ids.includes(id);
}

function onToggleCategory(id: number) {
  const current = settings.includedCategoryIds ?? categories.categories.map((c) => c.id);
  const set = new Set(current);
  if (set.has(id)) set.delete(id);
  else set.add(id);
  void apply(() => settings.setIncludedCategoryIds([...set]));
}

/** Switch from "All" to an explicit list seeded with every current category. */
function pickSpecific() {
  void apply(() => settings.setIncludedCategoryIds(categories.categories.map((c) => c.id)));
}
</script>

<template>
  <div v-if="view.drawerOpen" class="scrim" @click="view.closeDrawer()">
    <aside class="drawer" @click.stop>
      <header>
        <Mono :size="11">Filter settings</Mono>
        <button class="x" aria-label="Close" @click="view.closeDrawer()">✕</button>
      </header>

      <div class="body">
        <!-- Lookback window -->
        <section>
          <Mono>Lookback window</Mono>
          <div class="row">
            <input
              class="num"
              type="number"
              min="1"
              max="720"
              :value="settings.lookbackValue"
              :disabled="settings.saving"
              @change="onValue"
            />
            <div class="seg">
              <button
                v-for="u in UNITS"
                :key="u"
                :class="{ active: settings.lookbackUnit === u }"
                :disabled="settings.saving"
                @click="onUnit(u)"
              >
                {{ u }}
              </button>
            </div>
          </div>
          <p class="hint">
            Conversations updated in the last {{ settings.lookbackValue }}
            {{ settings.lookbackUnit }}.
          </p>
        </section>

        <!-- States -->
        <section>
          <Mono>Conversation state</Mono>
          <label v-for="s in STATES" :key="s" class="check">
            <input
              type="checkbox"
              :checked="settings.states.includes(s)"
              :disabled="settings.saving"
              @change="onToggleState(s)"
            />
            <span>{{ s }}</span>
          </label>
        </section>

        <!-- Included categories -->
        <section>
          <Mono>Visible categories</Mono>
          <label class="check">
            <input
              type="radio"
              :checked="allCategories"
              :disabled="settings.saving"
              @change="setAllCategories"
            />
            <span>All categories</span>
          </label>
          <div v-if="!allCategories" class="cat-list">
            <label v-for="c in categories.categories" :key="c.id" class="check indent">
              <input
                type="checkbox"
                :checked="isIncluded(c.id)"
                :disabled="settings.saving"
                @change="onToggleCategory(c.id)"
              />
              <CatDot :color="c.color" :size="8" />
              <span>{{ c.name }}</span>
            </label>
          </div>
          <button v-else class="link" :disabled="settings.saving" @click="pickSpecific">
            Pick specific categories…
          </button>
        </section>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.25);
  display: flex;
  justify-content: flex-end;
  z-index: 50;
}
.drawer {
  width: 320px;
  background: var(--panel);
  border-left: var(--hairline) solid var(--line);
  display: flex;
  flex-direction: column;
  animation: triageSlide 0.16s ease-out;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: var(--hairline) solid var(--line);
}
.x {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 13px;
}
.body {
  padding: 8px 16px 24px;
  overflow-y: auto;
}
section {
  padding: 16px 0;
  border-bottom: var(--hairline) solid var(--line-soft);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.num {
  width: 64px;
  padding: 5px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-mono);
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
.check.indent {
  padding-left: 4px;
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
</style>

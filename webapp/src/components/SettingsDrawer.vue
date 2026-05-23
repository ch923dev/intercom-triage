<!-- Settings drawer. Reference: tasks.md T035 — US-001, US-007, FR-011/012.
     Lookback window, conversation states, and which categories the board
     includes. Every change is persisted via `/settings` and re-fetches the
     board so the filter takes effect immediately. -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import CatDot from './CatDot.vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import { useTweaksStore } from '@/stores/tweaks';
import { permission, requestPermission, supported } from '@/utils/notify';
import type { Density, LookbackUnit, TicketState } from '@/types/api';

const settings = useSettingsStore();
const tickets = useTicketsStore();
const categories = useCategoriesStore();
const view = useViewStore();
const tweaks = useTweaksStore();
const notifyHint = ref('');

const STATES: TicketState[] = ['open', 'snoozed', 'closed'];
const UNITS: LookbackUnit[] = ['hours', 'days'];
const densities: Density[] = ['compact', 'balanced', 'comfy'];
const DENSITY_LABEL: Record<Density, string> = {
  compact: 'Compact',
  balanced: 'Balanced',
  comfy: 'Comfy',
};

/** Run a settings mutation, then refresh the board against the new filter. */
async function apply(mutate: () => Promise<void>) {
  await mutate();
  await tickets.refresh();
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

/** AI toggle — no board refresh; it only affects the next ingest. */
function onToggleUseAi(event: Event) {
  void settings.setUseAi((event.target as HTMLInputElement).checked);
}

/** Auto-resolve default toggle. */
function onToggleAiResolveDefault(event: Event) {
  void settings.setAiResolveDefault((event.target as HTMLInputElement).checked);
}

/** Confidence threshold slider. */
function onConfidenceThreshold(event: Event) {
  const v = parseFloat((event.target as HTMLInputElement).value);
  if (!isNaN(v)) void settings.setAiResolveConfidenceThreshold(v);
}

/** Background sync interval selector — saves to the tweaks store (localStorage). */
function onAutoSyncChange(event: Event) {
  const raw = Number((event.target as HTMLSelectElement).value) as 0 | 30 | 60 | 300;
  tweaks.setAutoSyncSeconds(raw);
}

/** Desktop notifications toggle — turning it on prompts for browser
 *  permission the first time; a denial reverts the checkbox with a hint. */
async function onToggleNotifications(event: Event) {
  const input = event.target as HTMLInputElement;
  notifyHint.value = '';
  if (!input.checked) {
    tweaks.setDesktopNotifications(false);
    return;
  }
  if (!supported()) {
    notifyHint.value = 'This browser does not support notifications.';
    input.checked = false;
    return;
  }
  let perm = permission();
  if (perm === 'default') perm = await requestPermission();
  if (perm === 'granted') {
    tweaks.setDesktopNotifications(true);
  } else {
    notifyHint.value = 'Notifications blocked — allow them in browser site settings.';
    input.checked = false;
  }
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
        <!-- Display tweaks — per-device, persisted in localStorage via the
             tweaks store. Lives here (rather than the topbar) so the topbar
             stays focused on navigation + search. -->
        <section class="display">
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
            <button
              :class="{ active: !tweaks.darkMode }"
              @click="tweaks.setDarkMode(false)"
            >Light</button>
            <button
              :class="{ active: tweaks.darkMode }"
              @click="tweaks.setDarkMode(true)"
            >Dark</button>
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

        <!-- AI categorization toggle -->
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

        <!-- Auto-resolve (T16) -->
        <section>
          <Mono>Auto-resolve</Mono>
          <label class="check">
            <input
              type="checkbox"
              :checked="settings.aiResolveDefault"
              :disabled="settings.saving || !settings.useAi"
              @change="onToggleAiResolveDefault"
            />
            <span class="sentence">Let AI suggest resolution</span>
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
            Suggestions appear as chips on cards. AI never moves tickets
            automatically — you confirm every change.
          </p>
        </section>

        <!-- Desktop notifications -->
        <section>
          <Mono>Desktop notifications</Mono>
          <label class="check">
            <input
              type="checkbox"
              :checked="tweaks.desktopNotifications"
              @change="onToggleNotifications"
            />
            <span class="sentence">Notify on the desktop when a follow-up is due</span>
          </label>
          <p v-if="notifyHint" class="hint">{{ notifyHint }}</p>
          <p v-else class="hint">
            A browser notification fires alongside the in-app alarm, even when
            this tab is in the background.
          </p>
        </section>

        <!-- Background sync -->
        <section>
          <Mono>Background sync</Mono>
          <div class="row">
            <select
              class="sync-select"
              :value="tweaks.autoSyncSeconds"
              @change="onAutoSyncChange"
            >
              <option :value="0">Off</option>
              <option :value="30">30s</option>
              <option :value="60">1m</option>
              <option :value="300">5m</option>
            </select>
          </div>
          <p class="hint">
            Refreshes the board silently when the extension or another browser
            session ingests new tickets.
          </p>
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
/* Sentence-length labels must not be title-cased like the single-word ones. */
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
.sync-select {
  padding: 5px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 12px;
  cursor: pointer;
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

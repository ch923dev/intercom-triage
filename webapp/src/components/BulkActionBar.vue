<!-- Sticky bottom action bar for multi-select bulk operations.
     Reference: tasks.md T082, plan §8d.

     Visible when `selectionStore.count > 0`. Actions: Resolve, Reopen,
     Move-to (category picker), Follow-up (preset chips), Clear F/U, Dismiss
     chip, Clear selection. Disabled states per spec. -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import CatDot from './CatDot.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useSelectionStore } from '@/stores/selection';
import { useTicketsStore } from '@/stores/tickets';

const selection = useSelectionStore();
const tickets = useTicketsStore();
const categories = useCategoriesStore();
const followups = useFollowupsStore();

const moveOpen = ref(false);
const followupOpen = ref(false);
const busy = ref(false);
const toast = ref<string | null>(null);
let toastTimer = 0;

/** Selected ticket rows pulled out of the merged open + resolved lists. */
const selectedTickets = computed(() => {
  const ids = new Set(selection.asArray());
  const rows = [];
  for (const t of tickets.tickets) if (ids.has(t.id)) rows.push(t);
  for (const t of tickets.resolvedTickets) if (ids.has(t.id)) rows.push(t);
  return rows;
});

const allResolved = computed(
  () =>
    selectedTickets.value.length > 0 && selectedTickets.value.every((t) => t.resolved_at !== null),
);
const noneResolved = computed(
  () =>
    selectedTickets.value.length > 0 && selectedTickets.value.every((t) => t.resolved_at === null),
);
const anyHasChip = computed(() =>
  selectedTickets.value.some((t) => t.resolution_chip_state !== null),
);
const anyHasFollowup = computed(() => selectedTickets.value.some((t) => t.followup !== null));

/** Drop the chip preset row, since following the same template as the flyout's
 *  preset picker keeps the operator's spatial model intact. */
const presets: Array<{ label: string; minutes: number }> = [
  { label: '15m', minutes: 15 },
  { label: '1h', minutes: 60 },
  { label: '4h', minutes: 240 },
  { label: '24h', minutes: 24 * 60 },
];

function showToast(message: string) {
  toast.value = message;
  if (toastTimer) window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => {
    toast.value = null;
    toastTimer = 0;
  }, 4000);
}

function summarize(op: string, ok: number, failed: number): string {
  if (failed === 0) return `${ok} ${op}`;
  if (ok === 0) return `${op} failed (${failed})`;
  return `${ok} ${op}, ${failed} failed`;
}

async function runBulk<T>(fn: () => Promise<T>, op: string): Promise<T | undefined> {
  if (busy.value) return undefined;
  busy.value = true;
  try {
    const result = (await fn()) as unknown as { ok_ids?: string[]; failed?: { id: string }[] };
    const ok = result.ok_ids?.length ?? 0;
    const failed = result.failed?.length ?? 0;
    showToast(summarize(op, ok, failed));
    if (failed === 0) selection.clear();
    return result as T;
  } catch (e) {
    showToast(`${op} failed — ${(e as Error).message}`);
    return undefined;
  } finally {
    busy.value = false;
  }
}

function onResolve() {
  void runBulk(() => tickets.bulkResolve(selection.asArray()), 'resolved');
}
function onNonActionable() {
  void runBulk(() => tickets.bulkMarkNonActionable(selection.asArray()), 'marked non-actionable');
}
function onReopen() {
  void runBulk(() => tickets.bulkReopen(selection.asArray()), 'reopened');
}
function onMoveTo(categoryId: number) {
  moveOpen.value = false;
  void runBulk(() => tickets.bulkRecategorize(selection.asArray(), categoryId), 'moved');
}
function onFollowupPreset(minutes: number) {
  followupOpen.value = false;
  const dueAt = new Date(Date.now() + minutes * 60_000);
  void runBulk(() => followups.bulkSet(selection.asArray(), dueAt, null), 'follow-ups set');
}
function onClearFollowup() {
  void runBulk(() => followups.bulkClear(selection.asArray()), 'follow-ups cleared');
}
function onDismissChip() {
  void runBulk(() => tickets.bulkDismissChip(selection.asArray()), 'chips dismissed');
}
function onClearSelection() {
  selection.clear();
}
</script>

<template>
  <div v-if="!selection.isEmpty" class="bar-wrap" @click.stop>
    <div class="bar">
      <span class="count mono">{{ selection.count }} selected</span>

      <button type="button" class="clear" @click="onClearSelection">Clear</button>

      <div class="divider" />

      <button
        type="button"
        :disabled="busy || !noneResolved"
        :title="noneResolved ? 'Mark selected resolved' : 'Some selected are already resolved'"
        @click="onResolve"
      >
        Resolve
      </button>

      <button
        type="button"
        :disabled="busy || !noneResolved"
        :title="
          noneResolved ? 'Mark selected non-actionable' : 'Some selected are already resolved'
        "
        @click="onNonActionable"
      >
        Non-actionable
      </button>

      <button
        type="button"
        :disabled="busy || !allResolved"
        :title="allResolved ? 'Reopen selected' : 'All selected must be resolved'"
        @click="onReopen"
      >
        Reopen
      </button>

      <div class="divider" />

      <div class="dropdown">
        <button type="button" :disabled="busy" @click="moveOpen = !moveOpen">Move to ▾</button>
        <div v-if="moveOpen" class="menu" role="menu">
          <button
            v-for="cat in categories.categories"
            :key="cat.id"
            type="button"
            class="menu-item"
            role="menuitem"
            @click="onMoveTo(cat.id)"
          >
            <CatDot :color="cat.color" :size="8" />
            <span>{{ cat.name }}</span>
          </button>
        </div>
      </div>

      <div class="dropdown">
        <button type="button" :disabled="busy" @click="followupOpen = !followupOpen">
          Follow-up ▾
        </button>
        <div v-if="followupOpen" class="menu" role="menu">
          <button
            v-for="p in presets"
            :key="p.label"
            type="button"
            class="menu-item mono"
            role="menuitem"
            @click="onFollowupPreset(p.minutes)"
          >
            +{{ p.label }}
          </button>
        </div>
      </div>

      <button
        type="button"
        :disabled="busy || !anyHasFollowup"
        :title="anyHasFollowup ? 'Clear follow-ups on selected' : 'No follow-ups on selected'"
        @click="onClearFollowup"
      >
        Clear F/U
      </button>

      <div class="divider" />

      <button
        type="button"
        :disabled="busy || !anyHasChip"
        :title="anyHasChip ? 'Dismiss AI resolution chip' : 'No chips on selected'"
        @click="onDismissChip"
      >
        Dismiss chip
      </button>
    </div>

    <div v-if="toast" class="toast mono">{{ toast }}</div>
  </div>
</template>

<style scoped>
.bar-wrap {
  position: fixed;
  left: 50%;
  bottom: 24px;
  transform: translateX(-50%);
  z-index: 50;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  pointer-events: none;
}
.bar {
  pointer-events: auto;
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  box-shadow: var(--shadow);
  padding: 6px 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  animation: triageSlide 0.22s ease-out;
}
.count {
  color: var(--ink);
  padding: 0 4px;
}
.clear,
.bar > button {
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  background: transparent;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 4px 10px;
  cursor: pointer;
  transition:
    background 0.12s,
    border-color 0.12s,
    color 0.12s;
}
.clear {
  color: var(--ink-3);
}
.bar > button:hover:not(:disabled),
.dropdown > button:hover:not(:disabled),
.clear:hover {
  background: var(--hover);
  border-color: var(--accent);
  color: var(--accent);
}
.bar > button:disabled,
.dropdown > button:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.divider {
  width: 1px;
  height: 18px;
  background: var(--line);
}
.dropdown {
  position: relative;
}
.dropdown > button {
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  background: transparent;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 4px 10px;
  cursor: pointer;
}
.menu {
  position: absolute;
  bottom: calc(100% + 6px);
  left: 0;
  min-width: 160px;
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: 4px;
  box-shadow: var(--shadow);
  padding: 4px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  background: transparent;
  border: 0;
  color: var(--ink);
  font-size: 12px;
  padding: 6px 8px;
  border-radius: 3px;
  cursor: pointer;
  text-align: left;
}
.menu-item:hover {
  background: var(--hover);
}
.toast {
  pointer-events: auto;
  background: var(--ink);
  color: var(--bg);
  border-radius: var(--radius-chip);
  padding: 6px 12px;
  font-size: 11px;
  letter-spacing: 0.02em;
  box-shadow: var(--shadow);
  animation: triageSlide 0.22s ease-out;
}
</style>

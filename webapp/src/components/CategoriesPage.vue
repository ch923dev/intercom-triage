<!-- Category management page. Reference: tasks.md T037 — US-011, FR-017.
     Lists active categories with inline rename / recolor / reorder, an archive
     action, and a "Merge into…" action. The fallback category is protected:
     it cannot be archived or merged away. -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import CatDot from './CatDot.vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';

const categories = useCategoriesStore();
const tickets = useTicketsStore();
const settings = useSettingsStore();

// oklch swatch palette — matches the seeded category hues (plan §8b).
const SWATCHES = [
  'oklch(0.62 0.20 25)',
  'oklch(0.70 0.16 60)',
  'oklch(0.78 0.15 95)',
  'oklch(0.68 0.16 145)',
  'oklch(0.64 0.14 200)',
  'oklch(0.58 0.18 265)',
  'oklch(0.60 0.20 320)',
  'oklch(0.72 0.02 250)',
];

const sorted = computed(() =>
  [...categories.categories].sort((a, b) => a.sort_order - b.sort_order),
);

const busy = ref<number | null>(null);
const error = ref<string | null>(null);

/** Wrap a mutation: track the busy row and surface failures inline. */
async function run(id: number, fn: () => Promise<void>) {
  busy.value = id;
  error.value = null;
  try {
    await fn();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = null;
  }
}

function rename(id: number, event: Event) {
  const name = (event.target as HTMLInputElement).value.trim();
  if (!name) return;
  void run(id, () => categories.patchCategory(id, { name }));
}

function redescribe(id: number, event: Event) {
  const description = (event.target as HTMLInputElement).value.trim();
  if (!description) return;
  void run(id, () => categories.patchCategory(id, { description }));
}

function recolor(id: number, color: string) {
  void run(id, () => categories.patchCategory(id, { color }));
}

function move(id: number, direction: -1 | 1) {
  void run(id, () => categories.reorder(id, direction));
}

async function archive(id: number, name: string) {
  if (!window.confirm(`Archive “${name}”? Its tickets move to the fallback category.`)) return;
  await run(id, async () => {
    await categories.archiveCategory(id);
    await tickets.refresh(settings.filter);
  });
}

async function merge(srcId: number, event: Event) {
  const select = event.target as HTMLSelectElement;
  const dstId = Number(select.value);
  select.value = '';
  if (!dstId) return;
  const src = categories.byId.get(srcId);
  const dst = categories.byId.get(dstId);
  if (!window.confirm(`Merge “${src?.name}” into “${dst?.name}”? This archives “${src?.name}”.`)) {
    return;
  }
  await run(srcId, async () => {
    await categories.mergeCategories(srcId, dstId);
    await tickets.refresh(settings.filter);
  });
}

// ── Add a new category ─────────────────────────────────────────────────────
const newName = ref('');
const newDescription = ref('');
const newColor = ref(SWATCHES[0]);
const adding = ref(false);

async function add() {
  if (!newName.value.trim() || !newDescription.value.trim()) return;
  adding.value = true;
  error.value = null;
  try {
    await categories.createCategory(
      newName.value.trim(),
      newDescription.value.trim(),
      newColor.value,
    );
    newName.value = '';
    newDescription.value = '';
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    adding.value = false;
  }
}
</script>

<template>
  <div class="page">
    <div class="head">
      <Mono :size="11">Categories</Mono>
      <Mono>{{ sorted.length }} active</Mono>
    </div>

    <p v-if="error" class="error mono">{{ error }}</p>

    <ul class="rows">
      <li v-for="(cat, idx) in sorted" :key="cat.id" class="row" :class="{ busy: busy === cat.id }">
        <div class="reorder">
          <button :disabled="idx === 0 || busy !== null" title="Move up" @click="move(cat.id, -1)">
            ↑
          </button>
          <button
            :disabled="idx === sorted.length - 1 || busy !== null"
            title="Move down"
            @click="move(cat.id, 1)"
          >
            ↓
          </button>
        </div>

        <div class="swatches">
          <button
            v-for="s in SWATCHES"
            :key="s"
            class="swatch"
            :class="{ active: cat.color === s }"
            :style="{ background: s }"
            :title="s"
            :disabled="busy !== null"
            @click="recolor(cat.id, s)"
          />
        </div>

        <div class="fields">
          <div class="name-row">
            <CatDot :color="cat.color" :size="9" />
            <input
              class="name"
              :value="cat.name"
              :disabled="busy !== null"
              @change="rename(cat.id, $event)"
            />
            <Mono v-if="cat.is_fallback" :color="'var(--accent)'" :size="9">fallback</Mono>
            <Mono :size="9">{{ cat.source }}</Mono>
          </div>
          <input
            class="desc"
            :value="cat.description"
            :disabled="busy !== null"
            @change="redescribe(cat.id, $event)"
          />
        </div>

        <div class="actions">
          <select
            class="merge"
            :disabled="cat.is_fallback || busy !== null"
            :title="cat.is_fallback ? 'The fallback cannot be merged away' : 'Merge into…'"
            @change="merge(cat.id, $event)"
          >
            <option value="">Merge into…</option>
            <option
              v-for="dst in sorted.filter((d) => d.id !== cat.id)"
              :key="dst.id"
              :value="dst.id"
            >
              {{ dst.name }}
            </option>
          </select>
          <button
            class="archive"
            :disabled="cat.is_fallback || busy !== null"
            :title="cat.is_fallback ? 'The fallback cannot be archived' : 'Archive'"
            @click="archive(cat.id, cat.name)"
          >
            Archive
          </button>
        </div>
      </li>
    </ul>

    <!-- New category -->
    <form class="new" @submit.prevent="add">
      <Mono>New category</Mono>
      <div class="new-row">
        <div class="swatches">
          <button
            v-for="s in SWATCHES"
            :key="s"
            type="button"
            class="swatch"
            :class="{ active: newColor === s }"
            :style="{ background: s }"
            @click="newColor = s"
          />
        </div>
        <input v-model="newName" class="name" placeholder="Name" maxlength="120" />
        <input
          v-model="newDescription"
          class="desc"
          placeholder="Description — what belongs here"
          maxlength="600"
        />
        <button
          class="add"
          type="submit"
          :disabled="adding || !newName.trim() || !newDescription.trim()"
        >
          {{ adding ? 'Adding…' : 'Add' }}
        </button>
      </div>
    </form>
  </div>
</template>

<style scoped>
.page {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 40px;
}
.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 14px;
}
.error {
  color: var(--accent);
  margin: 0 0 12px;
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.row {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 8px;
  border-bottom: var(--hairline) solid var(--line-soft);
}
.row.busy {
  opacity: 0.55;
}
.reorder {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.reorder button {
  width: 20px;
  height: 16px;
  border: var(--hairline) solid var(--line);
  background: var(--bg);
  color: var(--ink-2);
  cursor: pointer;
  font-size: 9px;
  line-height: 1;
  border-radius: 2px;
}
.reorder button:disabled {
  opacity: 0.3;
  cursor: default;
}
.swatches {
  display: flex;
  gap: 3px;
}
.swatch {
  width: 14px;
  height: 14px;
  border-radius: 2px;
  border: var(--hairline) solid var(--line);
  cursor: pointer;
  padding: 0;
}
.swatch.active {
  outline: 2px solid var(--ink);
  outline-offset: 1px;
}
.fields {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 5px;
  min-width: 0;
}
.name-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
input.name {
  font-size: 13px;
  font-weight: 500;
  color: var(--ink);
  border: var(--hairline) solid transparent;
  background: transparent;
  padding: 3px 6px;
  border-radius: var(--radius-chip);
  width: 180px;
}
input.desc {
  font-size: 11.5px;
  color: var(--ink-2);
  border: var(--hairline) solid transparent;
  background: transparent;
  padding: 3px 6px;
  border-radius: var(--radius-chip);
  width: 100%;
}
input:hover:not(:disabled),
input:focus {
  border-color: var(--line);
  background: var(--bg);
  outline: none;
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
}
.merge,
.archive,
.add {
  font-family: var(--font-mono);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 5px 10px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink-2);
  cursor: pointer;
}
.archive:not(:disabled):hover {
  border-color: var(--accent);
  color: var(--accent);
}
.merge:disabled,
.archive:disabled,
.add:disabled {
  opacity: 0.4;
  cursor: default;
}
.new {
  margin-top: 24px;
  padding: 16px;
  border: var(--hairline) dashed var(--line);
  border-radius: var(--radius-card);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.new-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.new-row input.name,
.new-row input.desc {
  border-color: var(--line);
  background: var(--bg);
}
.new-row input.desc {
  flex: 1;
}
.add {
  background: var(--ink);
  color: var(--bg);
  border-color: var(--ink);
}
</style>

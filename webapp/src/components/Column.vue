<!-- Column. Per tasks.md T032 / T034.
     Header with cat dot + name + count, body with TicketCards inside a
     vuedraggable list so drag-to-override works between columns. -->
<script setup lang="ts">
import { computed } from 'vue';
import draggable from 'vuedraggable';
import CatDot from './CatDot.vue';
import Mono from './Mono.vue';
import TicketCard from './TicketCard.vue';
import { useSelectionStore } from '@/stores/selection';
import { useTicketsStore } from '@/stores/tickets';
import type { Ticket } from '@/types/api';

interface Column {
  id: number;
  key: string;
  name: string;
  color: string | null;
  isFallback: boolean;
}
interface Props {
  column: Column;
  tickets: Ticket[];
  selectedId?: string | null;
}
const props = defineProps<Props>();

const ticketsStore = useTicketsStore();
const selection = useSelectionStore();
const emit = defineEmits<{
  (e: 'select', ticket: Ticket): void;
}>();

/** How many cards in this column are currently in the bulk selection set.
 *  Drives the visibility + label of the "Select all" chip. */
const selectedInColumn = computed(() =>
  props.tickets.reduce((n, t) => n + (selection.has(t.id) ? 1 : 0), 0),
);

const allSelected = computed(
  () => props.tickets.length > 0 && selectedInColumn.value === props.tickets.length,
);

async function onChange(event: { added?: { element: Ticket } }) {
  // vuedraggable fires `added` on the destination list when an item moves in.
  if (!event.added) return;
  const id = event.added.element.id;
  // Bulk drag (plan §8d, FR-035): when the dragged card is part of the
  // multi-select set, the drop applies to every selected ticket. The other
  // selected cards stay visually in their previous columns during the drag —
  // they reposition reactively once `pendingOverrides` is rewritten for the
  // whole batch.
  if (selection.has(id) && selection.count > 1) {
    const ids = selection.asArray();
    const result = await ticketsStore.bulkRecategorize(ids, props.column.id);
    if (result.failed.length === 0) selection.clear();
    return;
  }
  void ticketsStore.applyOverride(id, props.column.id);
}

/** Click → modifier-aware dispatch.
 *  - Cmd/Ctrl+click → bulk toggle, no flyout.
 *  - Shift+click in same column → range select from `lastAnchor` to clicked id.
 *  - Shift+click in a different column → downgrade to bulk toggle.
 *  - Plain click → open flyout (existing behavior). */
function onCardClick(t: Ticket, e: MouseEvent) {
  if (e.metaKey || e.ctrlKey) {
    selection.toggle(t.id, props.column.key);
    return;
  }
  if (e.shiftKey) {
    const anchor = selection.lastAnchor;
    if (anchor && anchor.columnId === props.column.key) {
      const ordered = props.tickets.map((x) => x.id);
      selection.addRange(props.column.key, anchor.id, t.id, ordered);
    } else {
      selection.toggle(t.id, props.column.key);
    }
    return;
  }
  emit('select', t);
}

/** Select-all chip — toggles every card in this column in/out of the
 *  selection. Click again when all are selected to deselect them. */
function onSelectAllClick() {
  if (allSelected.value) {
    for (const t of props.tickets) selection.remove(t.id);
  } else {
    selection.addAll(
      props.tickets.map((t) => t.id),
      props.column.key,
    );
  }
}

function modelList() {
  return props.tickets;
}
</script>

<template>
  <section class="column">
    <header>
      <CatDot :color="props.column.color" :size="9" />
      <div class="name">{{ props.column.name }}</div>
      <button
        v-if="props.tickets.length > 0"
        type="button"
        class="select-all"
        :class="{ active: selectedInColumn > 0 }"
        :title="allSelected ? 'Deselect all in column' : 'Select all in column'"
        @click="onSelectAllClick"
      >
        {{ allSelected ? 'Clear' : `Select ${props.tickets.length}` }}
      </button>
      <Mono class="count">{{ props.tickets.length }}</Mono>
    </header>

    <draggable
      :model-value="modelList()"
      :group="{ name: 'tickets', pull: true, put: true }"
      item-key="id"
      class="cards"
      ghost-class="card-ghost"
      drag-class="card-dragging"
      @change="onChange"
    >
      <template #item="{ element }: { element: Ticket }">
        <TicketCard
          :ticket="element"
          :selected="props.selectedId === element.id"
          :multi-selected="selection.has(element.id)"
          :overridden="element.user_override || !!ticketsStore.pendingOverrides[element.id]"
          @click="(e: MouseEvent) => onCardClick(element, e)"
        />
      </template>
      <template #footer>
        <div v-if="props.tickets.length === 0" class="empty mono">empty</div>
      </template>
    </draggable>
  </section>
</template>

<style scoped>
.column {
  flex: 0 0 280px;
  display: flex;
  flex-direction: column;
  border-right: var(--hairline) solid var(--line-soft);
}
header {
  padding: 14px 14px 10px;
  border-bottom: var(--hairline) solid var(--line);
  display: flex;
  align-items: center;
  gap: 8px;
  position: sticky;
  top: 0;
  background: var(--bg);
  z-index: 1;
}
.name {
  font-size: 12.5px;
  color: var(--ink);
  font-weight: 500;
  letter-spacing: -0.005em;
}
.count {
  margin-left: auto;
}
.select-all {
  font-family: var(--font-mono);
  font-size: 9.5px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-3);
  background: transparent;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 2px 6px;
  cursor: pointer;
  opacity: 0;
  transition:
    opacity 0.12s,
    color 0.12s,
    border-color 0.12s;
  margin-left: auto;
}
.column:hover .select-all,
.select-all.active {
  opacity: 1;
}
.select-all.active {
  color: var(--accent);
  border-color: var(--accent);
}
.select-all:hover {
  color: var(--accent);
  border-color: var(--accent);
}
/* When the chip is shown the count needs its own left-margin reset. */
.select-all + .count {
  margin-left: 6px;
}
.cards {
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  flex: 1;
}
.empty {
  text-align: center;
  padding: 24px 8px;
  border: var(--hairline) dashed var(--line);
  border-radius: 3px;
  color: var(--ink-3);
}
.card-ghost {
  opacity: 0.4;
}
.card-dragging {
  cursor: grabbing;
}
</style>

<!-- NonActionableColumn — separate Kanban column for tickets whose
     `resolved_source === 'non_actionable'`. Mirrors ResolvedColumn:
     drag-in from any open category column marks selected tickets
     non-actionable; drag-out into a category column reopens + overrides
     (handled by Column.vue + applyOverride). -->
<script setup lang="ts">
import { computed } from 'vue';
import draggable from 'vuedraggable';
import Mono from './Mono.vue';
import TicketCard from './TicketCard.vue';
import { useSelectionStore } from '@/stores/selection';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import type { Ticket } from '@/types/api';

const tickets = useTicketsStore();
const view = useViewStore();
const selection = useSelectionStore();

const items = computed(() => tickets.nonActionableTickets);
const selectedId = computed(() => view.selectedTicketId);

const COLUMN_KEY = '__non_actionable__';

async function onChange(event: { added?: { element: Ticket } }) {
  if (!event.added) return;
  const id = event.added.element.id;
  if (selection.has(id) && selection.count > 1) {
    const ids = selection.asArray();
    const result = await tickets.bulkMarkNonActionable(ids);
    if (result.failed.length === 0) selection.clear();
    return;
  }
  void tickets.markNonActionable(id);
}

function onCardClick(t: Ticket, e: MouseEvent) {
  if (e.metaKey || e.ctrlKey) {
    selection.toggle(t.id, COLUMN_KEY);
    return;
  }
  if (e.shiftKey) {
    const anchor = selection.lastAnchor;
    if (anchor && anchor.columnId === COLUMN_KEY) {
      const ordered = items.value.map((x) => x.id);
      selection.addRange(COLUMN_KEY, anchor.id, t.id, ordered);
    } else {
      selection.toggle(t.id, COLUMN_KEY);
    }
    return;
  }
  view.selectTicket(t.id);
}
</script>

<template>
  <section class="column non-actionable">
    <header>
      <span class="dot" />
      <div class="name">Non-actionable</div>
      <Mono class="count">{{ items.length }}</Mono>
    </header>

    <draggable
      :model-value="items"
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
          :selected="selectedId === element.id"
          :multi-selected="selection.has(element.id)"
          @click="(e: MouseEvent) => onCardClick(element, e)"
        />
      </template>
      <template #footer>
        <div v-if="items.length === 0" class="empty mono">Nothing non-actionable</div>
      </template>
    </draggable>
  </section>
</template>

<style scoped>
.column.non-actionable {
  flex: 0 0 280px;
  display: flex;
  flex-direction: column;
  border-right: var(--hairline) solid var(--line-soft);
  border-left: 2px solid var(--ink-3);
  opacity: 0.95;
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
.dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--ink-3);
  flex-shrink: 0;
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

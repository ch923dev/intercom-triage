<!-- ResolvedColumn — always-visible Kanban column for resolved tickets.
     Reference: tasks.md T13 / T066. Joins the `tickets` vuedraggable group so
     operators can drag an open card here to resolve it. -->
<script setup lang="ts">
import { computed } from 'vue';
import draggable from 'vuedraggable';
import Mono from './Mono.vue';
import TicketCard from './TicketCard.vue';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import type { Ticket } from '@/types/api';

const tickets = useTicketsStore();
const view = useViewStore();

const items = computed(() => tickets.resolvedTickets);
const selectedId = computed(() => view.selectedTicketId);

function onChange(event: { added?: { element: Ticket } }) {
  if (event.added) {
    void tickets.markResolved(event.added.element.id);
  }
}

function onSelect(t: Ticket) {
  view.selectTicket(t.id);
}
</script>

<template>
  <section class="column resolved">
    <header>
      <span class="dot" />
      <div class="name">Resolved</div>
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
          @click="onSelect(element)"
        />
      </template>
      <template #footer>
        <div v-if="items.length === 0" class="empty mono">Nothing resolved yet</div>
      </template>
    </draggable>
  </section>
</template>

<style scoped>
.column.resolved {
  flex: 0 0 280px;
  display: flex;
  flex-direction: column;
  border-right: var(--hairline) solid var(--line-soft);
  border-left: 2px solid var(--accent, #ff4d2e);
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
/* Accent dot in the header — mirrors CatDot sizing */
.dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--accent, #ff4d2e);
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

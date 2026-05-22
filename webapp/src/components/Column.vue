<!-- Column. Per tasks.md T032 / T034.
     Header with cat dot + name + count, body with TicketCards inside a
     vuedraggable list so drag-to-override works between columns. -->
<script setup lang="ts">
import draggable from 'vuedraggable';
import CatDot from './CatDot.vue';
import Mono from './Mono.vue';
import TicketCard from './TicketCard.vue';
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

const tickets = useTicketsStore();
const emit = defineEmits<{
  (e: 'select', ticket: Ticket): void;
}>();

function onChange(event: { added?: { element: Ticket } }) {
  // vuedraggable fires `added` on the destination list when an item moves in.
  if (event.added) {
    void tickets.applyOverride(event.added.element.id, props.column.id);
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
          :overridden="element.user_override || !!tickets.pendingOverrides[element.id]"
          @click="emit('select', element)"
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

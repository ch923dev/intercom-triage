<!-- Board — horizontal scroll of columns. Per tasks.md T032. -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import Column from './Column.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useTicketsStore } from '@/stores/tickets';
import type { Ticket } from '@/types/api';

const categories = useCategoriesStore();
const tickets = useTicketsStore();

const selected = ref<Ticket | null>(null);
const selectedId = computed(() => selected.value?.id ?? null);

function ticketsForColumn(col: { kind: 'category' | 'proposal'; id: number }) {
  if (col.kind === 'category') return tickets.byCategory.get(col.id) ?? [];
  return tickets.byProposal.get(col.id) ?? [];
}

function onSelect(t: Ticket) {
  selected.value = t;
}
</script>

<template>
  <div class="board">
    <Column
      v-for="col in categories.columns"
      :key="col.key"
      :column="col"
      :tickets="ticketsForColumn(col)"
      :selected-id="selectedId"
      @select="onSelect"
    />
    <div class="board-tail" />
  </div>
</template>

<style scoped>
.board {
  flex: 1;
  display: flex;
  overflow-x: auto;
  overflow-y: hidden;
}
.board-tail {
  flex: 1;
  min-width: 40px;
}
</style>

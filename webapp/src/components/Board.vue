<!-- Board — horizontal scroll of columns. Per tasks.md T032, T050. -->
<script setup lang="ts">
import { computed } from 'vue';
import Column from './Column.vue';
import ResolvedColumn from './ResolvedColumn.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import type { Ticket } from '@/types/api';

const categories = useCategoriesStore();
const tickets = useTicketsStore();
const followups = useFollowupsStore();
const settings = useSettingsStore();
const view = useViewStore();

const selectedId = computed(() => view.selectedTicketId);

/** Tickets for a column, with due follow-ups pinned to the top (T050). The
 *  source list is already `updated_at`-sorted; `sort` is stable so the rest
 *  keeps that order. */
function ticketsForColumn(col: { kind: 'category' | 'proposal'; id: number }) {
  const list =
    col.kind === 'category'
      ? (tickets.byCategory.get(col.id) ?? [])
      : (tickets.byProposal.get(col.id) ?? []);
  return [...list].sort((a, b) => Number(followups.isDue(b.id)) - Number(followups.isDue(a.id)));
}

function onSelect(t: Ticket) {
  view.selectTicket(t.id);
}

/** When hide_empty_categories is on, drop columns whose ticket list is empty.
 *  Proposal columns are pending operator review — keep them visible so the
 *  operator can curate them. */
const visibleColumns = computed(() => {
  if (!settings.hideEmptyCategories) return categories.columns;
  return categories.columns.filter((col) => {
    if (col.kind === 'proposal') return true;
    return ticketsForColumn(col).length > 0;
  });
});
</script>

<template>
  <div class="board">
    <Column
      v-for="col in visibleColumns"
      :key="col.key"
      :column="col"
      :tickets="ticketsForColumn(col)"
      :selected-id="selectedId"
      @select="onSelect"
    />
    <ResolvedColumn />
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

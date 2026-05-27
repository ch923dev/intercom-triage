<!-- Board — horizontal scroll of columns. Per tasks.md T032, T050. -->
<script setup lang="ts">
import { computed } from 'vue';
import Column from './Column.vue';
import NonActionableColumn from './NonActionableColumn.vue';
import ResolvedColumn from './ResolvedColumn.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useTweaksStore } from '@/stores/tweaks';
import { useViewStore } from '@/stores/view';
import type { Ticket } from '@/types/api';
import { byPriorityDesc } from '@/utils/priority';

const categories = useCategoriesStore();
const tickets = useTicketsStore();
const followups = useFollowupsStore();
const settings = useSettingsStore();
const tweaks = useTweaksStore();
const view = useViewStore();

const emit = defineEmits<{
  (e: 'board-click', ev: MouseEvent): void;
}>();

const selectedId = computed(() => view.selectedTicketId);
// Keyboard-triage cursor (NFR-007) — separate from the flyout selection.
const focusedId = computed(() => view.focusedTicketId);

/** Tickets for a column, with due follow-ups pinned to the top (T050). The
 *  source list is already `updated_at`-sorted; `sort` is stable so the rest
 *  keeps that order.
 *
 *  Roadmap 1.2 — when the operator turns on "Sort by priority", a second stable
 *  sort by `ai_priority` (urgent → low) runs on top. Sort keys compose by
 *  precedence: priority first, then follow-up-due, then recency. So an urgent
 *  card floats above a due follow-up, but within one priority tier the
 *  follow-up pinning and recency order are preserved unchanged. The toggle is
 *  off by default, leaving the existing follow-up/recency order as the
 *  baseline. */
function ticketsForColumn(col: { kind: 'category' | 'proposal'; id: number }) {
  const list =
    col.kind === 'category'
      ? (tickets.byCategory.get(col.id) ?? [])
      : (tickets.byProposal.get(col.id) ?? []);
  const sorted = [...list].sort(
    (a, b) => Number(followups.isDue(b.id)) - Number(followups.isDue(a.id)),
  );
  if (tweaks.sortByPriority) sorted.sort(byPriorityDesc);
  return sorted;
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
  <div class="board" @click="(e: MouseEvent) => emit('board-click', e)">
    <Column
      v-for="col in visibleColumns"
      :key="col.key"
      :column="col"
      :tickets="ticketsForColumn(col)"
      :selected-id="selectedId"
      :focused-id="focusedId"
      @select="onSelect"
    />
    <ResolvedColumn />
    <NonActionableColumn />
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

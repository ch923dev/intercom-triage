<!-- ResolutionChip — advisory chip on cards where the backend computed
     `resolution_chip_state` (ai_resolved / ai_reopened / new_reply).
     Clicking applies the action; the × dismisses it.
     Also renders a static kind label for non-actionable tickets (T107). -->
<script setup lang="ts">
import { computed } from 'vue';
import { useTicketsStore } from '@/stores/tickets';
import type { NonActionableKind, Ticket } from '@/types/api';

const props = defineProps<{ ticket: Ticket }>();
const tickets = useTicketsStore();

const KIND_LABELS: Record<NonActionableKind, string> = {
  auto_reply: 'Auto-reply',
  thanks: 'Thanks',
  spam: 'Spam',
  out_of_office: 'Out of office',
  other: 'Other',
};

const advisoryLabel = computed(() => {
  switch (props.ticket.resolution_chip_state) {
    case 'ai_resolved':
      return `AI: resolved? · ${(props.ticket.ai_resolution_confidence ?? 0).toFixed(2)}`;
    case 'ai_reopened':
      return `AI: reopened? · ${(props.ticket.ai_resolution_confidence ?? 0).toFixed(2)}`;
    case 'new_reply':
      return 'new reply';
    default:
      return '';
  }
});

const nonActionableLabel = computed(() => {
  if (props.ticket.resolved_source !== 'non_actionable') return '';
  const kind = props.ticket.non_actionable_kind;
  return kind ? `Non-actionable · ${KIND_LABELS[kind]}` : 'Non-actionable';
});

async function onApplyAdvisory() {
  const chipState = props.ticket.resolution_chip_state;
  if (chipState === 'ai_resolved') {
    await tickets.markResolved(props.ticket.id);
  } else if (chipState === 'ai_reopened' || chipState === 'new_reply') {
    await tickets.reopen(props.ticket.id);
  }
}

async function onDismiss(e: Event) {
  e.stopPropagation();
  await tickets.dismissChip(props.ticket.id);
}
</script>

<template>
  <button
    v-if="ticket.resolution_chip_state"
    class="resolution-chip advisory"
    :title="ticket.ai_resolution_reason ?? ''"
    @click.stop="onApplyAdvisory"
  >
    {{ advisoryLabel }}
    <span class="dismiss" aria-label="Dismiss suggestion" @click="onDismiss">×</span>
  </button>
  <span
    v-else-if="ticket.resolved_source === 'non_actionable'"
    class="resolution-chip non-actionable"
  >
    {{ nonActionableLabel }}
  </span>
</template>

<style scoped>
.resolution-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--chip-bg);
  color: var(--ink-2);
}
.advisory {
  cursor: pointer;
}
.advisory:hover {
  background: var(--hover);
}
.dismiss {
  font-size: 12px;
  line-height: 1;
  opacity: 0.6;
  cursor: pointer;
}
.dismiss:hover {
  opacity: 1;
}
</style>

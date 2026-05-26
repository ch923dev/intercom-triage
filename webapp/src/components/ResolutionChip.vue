<!-- ResolutionChip — two roles in one component:
     1. Advisory chip on cards where the backend computed `resolution_chip_state`
        (ai_resolved / ai_reopened / new_reply). Clicking applies the action;
        the × dismisses it.
     2. Static sub-state badge on resolved cards. resolved_source = 'non_actionable'
        renders as a muted gray "Non-actionable" badge; other sources render
        nothing here (the column itself communicates "resolved"). -->
<script setup lang="ts">
import { computed } from 'vue';
import { useTicketsStore } from '@/stores/tickets';
import type { Ticket } from '@/types/api';

const props = defineProps<{ ticket: Ticket }>();
const tickets = useTicketsStore();

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

const isNonActionable = computed(
  () =>
    props.ticket.resolved_at !== null && props.ticket.resolved_source === 'non_actionable',
);

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
  <span v-else-if="isNonActionable" class="resolution-chip non-actionable">
    Non-actionable
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
.non-actionable {
  /* Muted gray — same family as the fallback "Other" category swatch. */
  background: oklch(0.65 0 0 / 0.12);
  color: var(--ink-3);
  border-color: var(--line);
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

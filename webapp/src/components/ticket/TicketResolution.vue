<script setup lang="ts">
import { computed } from 'vue';
import type { Ticket } from '@/types/api';
import { useTicketsStore } from '@/stores/tickets';
import { formatShortDateTime } from '@/utils/time';

const { ticket } = defineProps<{ ticket: Ticket }>();
const tickets = useTicketsStore();

const statusLabel = computed(() => {
  switch (ticket.resolved_source) {
    case 'manual':
      return 'Resolved · manual';
    case 'intercom_closed':
      return 'Resolved · intercom';
    case 'non_actionable':
      return 'Non-actionable';
    default:
      return 'Resolved';
  }
});

async function onResolve() {
  await tickets.markResolved(ticket.id);
}

async function onReopen() {
  await tickets.reopen(ticket.id);
}

async function onMarkNonActionable() {
  await tickets.markNonActionable(ticket.id);
}

async function setAi(v: boolean | null) {
  await tickets.setAiResolve(ticket.id, v);
}
</script>

<template>
  <section class="block">
    <div class="mono label">Resolution</div>
    <div class="status-row">
      <span v-if="ticket.resolved_at" class="status-pill mono">
        {{ statusLabel }} · {{ formatShortDateTime(ticket.resolved_at) }}
      </span>
      <span v-else class="status-pill mono">Open</span>
    </div>
    <div class="presets">
      <button v-if="ticket.resolved_at" class="chip" @click="onReopen">Reopen</button>
      <template v-else>
        <button class="chip" @click="onResolve">Mark resolved</button>
        <button class="chip" @click="onMarkNonActionable">Mark non-actionable</button>
      </template>
    </div>
    <div class="ai-tristate">
      <span class="mono tristate-label">AI</span>
      <div class="seg">
        <button
          :class="{ active: ticket.ai_resolve_override === null }"
          @click="setAi(null)"
        >default</button>
        <button
          :class="{ active: ticket.ai_resolve_override === true }"
          @click="setAi(true)"
        >on</button>
        <button
          :class="{ active: ticket.ai_resolve_override === false }"
          @click="setAi(false)"
        >off</button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.block {
  border-top: var(--hairline) solid var(--line);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.label {
  color: var(--ink-3);
}
.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.chip {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.03em;
  padding: 3px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  color: var(--ink);
  cursor: pointer;
}
.chip:hover {
  background: var(--hover);
}
.status-row {
  display: flex;
  align-items: center;
}
.status-pill {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-2);
  padding: 3px 7px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--chip-bg);
}
.ai-tristate {
  display: flex;
  align-items: center;
  gap: 8px;
}
.tristate-label {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--ink-3);
}
.seg {
  display: inline-flex;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  overflow: hidden;
}
.seg button {
  padding: 4px 10px;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.03em;
}
.seg button.active {
  background: var(--ink);
  color: var(--bg);
}
.seg button:hover:not(.active) {
  background: var(--hover);
  color: var(--ink);
}
</style>

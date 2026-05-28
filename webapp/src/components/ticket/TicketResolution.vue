<script setup lang="ts">
import { computed, ref } from 'vue';
import type { NonActionableKind, ParkedReason, Ticket } from '@/types/api';
import CollapsibleSection from './CollapsibleSection.vue';
import ParkMenu from '@/components/ParkMenu.vue';
import { useTicketsStore } from '@/stores/tickets';
import { formatShortDateTime } from '@/utils/time';

const { ticket } = defineProps<{ ticket: Ticket }>();
const tickets = useTicketsStore();

const KIND_LABELS: Record<NonActionableKind, string> = {
  auto_reply: 'Auto-reply',
  thanks: 'Thanks',
  spam: 'Spam',
  out_of_office: 'Out of office',
  other: 'Other',
};

const statusLabel = computed(() => {
  switch (ticket.resolved_source) {
    case 'manual':
      return 'Resolved · manual';
    case 'intercom_closed':
      return 'Resolved · intercom';
    case 'non_actionable': {
      const kind = ticket.non_actionable_kind;
      return kind ? `Non-actionable · ${KIND_LABELS[kind]}` : 'Non-actionable';
    }
    case 'ai_resolved':
      return 'Resolved · ai';
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

const PARK_REASON_LABELS: Record<ParkedReason, string> = {
  waiting_on_customer: 'waiting on customer',
  waiting_on_third_party: 'waiting on third party',
  waiting_internal: 'waiting (internal)',
  other: 'parked',
};

const parkOpen = ref(false);
const parkBtnEl = ref<HTMLElement | null>(null);

const isReady = computed(
  () => !!ticket.parked_until && Date.parse(ticket.parked_until) <= Date.now(),
);

const parkedLabel = computed(() => {
  if (!ticket.parked_at || !ticket.parked_until) return '';
  const reasonText =
    ticket.parked_reason === 'other' && ticket.parked_note
      ? ticket.parked_note
      : ticket.parked_reason
        ? PARK_REASON_LABELS[ticket.parked_reason]
        : 'parked';
  return isReady.value
    ? `★ Ready · ${reasonText}`
    : `Parked · ${reasonText} · until ${formatShortDateTime(ticket.parked_until)}`;
});

async function onPark(untilAt: string, reason: ParkedReason, note: string | null) {
  parkOpen.value = false;
  await tickets.parkTicket(ticket.id, untilAt, reason, note);
}

async function onUnpark() {
  await tickets.unparkTicket(ticket.id);
}
</script>

<template>
  <CollapsibleSection title="Resolution" storage-key="resolution">
    <div class="status-row">
      <span v-if="ticket.resolved_at" class="status-pill mono">
        {{ statusLabel }} · {{ formatShortDateTime(ticket.resolved_at) }}
      </span>
      <span v-else-if="ticket.parked_at" class="status-pill mono" :class="{ ready: isReady }">
        {{ parkedLabel }}
      </span>
      <span v-else class="status-pill mono">Open</span>
    </div>
    <div class="presets">
      <button v-if="ticket.resolved_at" class="chip" @click="onReopen">Reopen</button>
      <button v-else-if="ticket.parked_at" class="chip" @click="onUnpark">Unpark</button>
      <template v-else>
        <button class="chip" @click="onResolve">Mark resolved</button>
        <button class="chip" @click="onMarkNonActionable">Mark non-actionable</button>
        <div class="park-anchor">
          <button
            ref="parkBtnEl"
            class="chip"
            :class="{ active: parkOpen }"
            @click="parkOpen = !parkOpen"
          >
            Park ▾
          </button>
          <ParkMenu v-if="parkOpen" :anchor="parkBtnEl" @park="onPark" @close="parkOpen = false" />
        </div>
      </template>
    </div>
    <div class="ai-tristate">
      <span class="mono tristate-label">AI</span>
      <div class="seg">
        <button :class="{ active: ticket.ai_resolve_override === null }" @click="setAi(null)">
          default
        </button>
        <button :class="{ active: ticket.ai_resolve_override === true }" @click="setAi(true)">
          on
        </button>
        <button :class="{ active: ticket.ai_resolve_override === false }" @click="setAi(false)">
          off
        </button>
      </div>
    </div>
  </CollapsibleSection>
</template>

<style scoped>
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
.status-pill.ready {
  color: var(--accent);
  border-color: var(--accent);
}
.park-anchor {
  position: relative;
  display: inline-flex;
}
.chip.active {
  border-color: var(--accent);
  color: var(--accent);
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

<!-- One follow-up on the follow-up board. Shows the ticket id, its resolved
     title (when the ticket is loaded), the reason, a live countdown, and the
     Open / Snooze / Done actions. -->
<script setup lang="ts">
import { computed } from 'vue';
import Mono from './Mono.vue';
import { useFollowupsStore } from '@/stores/followups';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import { formatCountdown } from '@/utils/time';
import type { Followup } from '@/types/api';

interface Props {
  followup: Followup;
}
const props = defineProps<Props>();

const followups = useFollowupsStore();
const tickets = useTicketsStore();
const view = useViewStore();

/** Ticket title, or null when the ticket is not loaded (filtered out / not
 *  yet synced) — the card then shows id + reason only. */
const title = computed(() => tickets.byId.get(props.followup.ticket_id)?.title ?? null);
const countdown = computed(() =>
  formatCountdown(Date.parse(props.followup.due_at) - followups.now),
);

function open() {
  view.selectTicket(props.followup.ticket_id);
}
function snooze(minutes: number) {
  void followups.snooze(props.followup.ticket_id, minutes);
}
function done() {
  void followups.clearFollowup(props.followup.ticket_id);
}
</script>

<template>
  <article class="fu-card">
    <header>
      <Mono>{{ props.followup.ticket_id }}</Mono>
      <Mono class="countdown">{{ countdown }}</Mono>
    </header>
    <h3 v-if="title" class="title">{{ title }}</h3>
    <p v-if="props.followup.reason" class="reason">{{ props.followup.reason }}</p>
    <div class="actions">
      <button class="act primary" @click="open">Open</button>
      <button class="act" @click="snooze(15)">15m</button>
      <button class="act" @click="snooze(60)">1h</button>
      <button class="act" @click="done">Done</button>
    </div>
  </article>
</template>

<style scoped>
.fu-card {
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-card);
  padding: 11px 12px 12px;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.countdown {
  color: var(--ink-3);
}
.title {
  margin: 0 0 6px;
  font-size: 13px;
  line-height: 1.35;
  color: var(--ink);
  font-weight: 500;
  letter-spacing: -0.005em;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.reason {
  margin: 0 0 8px;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--ink-2);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.act {
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
.act:hover {
  background: var(--hover);
}
.act.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
</style>

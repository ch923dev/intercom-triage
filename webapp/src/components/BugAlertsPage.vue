<!-- Bug-alert review page. Reference: tasks.md T182/T186 — US-045, US-046,
     FR-080..FR-083, FR-084/FR-087.
     Lists AI-detected product bugs worst-first, with the customer's own words as
     evidence. Two mutations: acknowledge ("I own this", which also rewrites the
     Slack announcement) and dismiss ("this is finished"). Detection stays the
     AI's job, and the backend owns every Slack call. -->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import Mono from './Mono.vue';
import { useBugAlertsStore } from '@/stores/bugAlerts';
import { formatAgoFromDate, formatShortDateTime } from '@/utils/time';
import type { BugAlert, BugSeverity } from '@/types/api';

const store = useBugAlertsStore();

type StateFilter = 'all' | 'pending' | 'announced' | 'acknowledged' | 'dismissed';
const severityFilter = ref<BugSeverity | 'all'>('all');
const stateFilter = ref<StateFilter>('all');

onMounted(() => {
  void store.load().catch(() => undefined); // the error surfaces from the store
});

/** Where an alert sits in its lifecycle, most-final first. Dismissal outranks
 *  acknowledgement, which outranks delivery: a dismissed alert is finished
 *  whether or not it was owned, and an owned alert is past "just announced".
 *  Backing state is independent (an alert can be both acked and dismissed) —
 *  this collapses it to the one label worth showing on a row. */
function stateOf(a: BugAlert): Exclude<StateFilter, 'all'> {
  if (a.dismissed_at) return 'dismissed';
  if (a.acked_at) return 'acknowledged';
  return a.posted_at ? 'announced' : 'pending';
}

/** True while the model's verdict is worse than what Slack was told — the next
 *  delivery pass will post a threaded escalation. */
const RANK: Record<BugSeverity, number> = { low: 1, medium: 2, high: 3 };
function isEscalating(a: BugAlert): boolean {
  return !!a.posted_severity && RANK[a.severity] > RANK[a.posted_severity];
}

/** The one-line status shown on a row. In script rather than a template ternary
 *  because four states nested inline stopped being readable. */
function stateLabel(a: BugAlert): string {
  switch (stateOf(a)) {
    case 'dismissed':
      return 'dismissed';
    case 'acknowledged':
      return `owned by ${a.acked_by?.name ?? 'an operator'}`;
    case 'announced':
      return isEscalating(a)
        ? `announced as ${a.posted_severity} · escalation pending`
        : 'announced';
    default:
      return 'awaiting announcement';
  }
}

/** Filtering is client-side: the endpoint already returns the full calibration
 *  set worst-first, and re-fetching per filter would lose that ordering work. */
const visible = computed(() =>
  store.alerts.filter(
    (a) =>
      (severityFilter.value === 'all' || a.severity === severityFilter.value) &&
      (stateFilter.value === 'all' || stateOf(a) === stateFilter.value),
  ),
);

/** Slack permalink from the stored pair. Both halves or nothing — a half-built
 *  archives URL 404s, which is worse than no link at all. */
function slackLink(a: BugAlert): string | null {
  if (!a.slack_channel || !a.slack_ts) return null;
  return `https://slack.com/archives/${a.slack_channel}/p${a.slack_ts.replace('.', '')}`;
}

function dismiss(ticketId: string) {
  void store.dismiss(ticketId).catch(() => undefined);
}

function ack(ticketId: string) {
  void store.ack(ticketId).catch(() => undefined);
}
</script>

<template>
  <div class="page">
    <div class="head">
      <Mono :size="11">AI bug alerts</Mono>
      <Mono>{{ store.pendingCount }} awaiting review</Mono>
      <div class="filters">
        <select v-model="severityFilter" class="filter" aria-label="Filter by severity">
          <option value="all">All severities</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <select v-model="stateFilter" class="filter" aria-label="Filter by state">
          <option value="all">All states</option>
          <option value="pending">Awaiting announcement</option>
          <option value="announced">Announced</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="dismissed">Dismissed</option>
        </select>
      </div>
    </div>

    <p v-if="store.error" class="error mono">{{ store.error }}</p>

    <div v-if="store.loading" class="empty mono">Loading…</div>
    <div v-else-if="store.alerts.length === 0" class="empty mono">
      No bug alerts recorded — the AI has not judged any conversation to be a product defect.
    </div>
    <div v-else-if="visible.length === 0" class="empty mono">No alerts match these filters.</div>

    <ul v-else class="rows">
      <li
        v-for="a in visible"
        :key="a.ticket_id"
        class="card"
        :class="[`sev-${a.severity}`, { dismissed: !!a.dismissed_at }]"
      >
        <div class="info">
          <div class="title-row">
            <span class="sev-chip" :class="`sev-chip-${a.severity}`">{{ a.severity }}</span>
            <a v-if="a.url" class="name" :href="a.url" target="_blank" rel="noopener">{{
              a.title || a.ticket_id
            }}</a>
            <span v-else class="name">{{ a.title || a.ticket_id }}</span>
          </div>

          <blockquote v-if="a.evidence" class="evidence">{{ a.evidence }}</blockquote>

          <div class="meta">
            <Mono :size="9">{{ Math.round(a.confidence * 100) }}% confident</Mono>
            <Mono :size="9">seen {{ a.occurrences }}×</Mono>
            <Mono :size="9" :title="formatShortDateTime(a.last_detected_at)">
              last {{ formatAgoFromDate(a.last_detected_at) }}
            </Mono>
            <Mono :size="9" class="state" :class="`state-${stateOf(a)}`">
              {{ stateLabel(a) }}
            </Mono>
            <!-- Acknowledged AND dismissed is a real combination; the row's
                 single state label can only show the latter, so name the owner
                 separately rather than losing it. -->
            <Mono v-if="a.acked_at && a.dismissed_at" :size="9" class="acked-by">
              acked by {{ a.acked_by?.name ?? 'an operator' }}
            </Mono>
            <Mono v-if="store.mirrorFailed.has(a.ticket_id)" :size="9" class="warn">
              Slack message not updated
            </Mono>
            <a
              v-if="slackLink(a)"
              class="slack mono"
              :href="slackLink(a) as string"
              target="_blank"
              rel="noopener"
              >open in Slack</a
            >
            <Mono :size="9" class="tid">{{ a.ticket_id }}</Mono>
          </div>
        </div>

        <div class="actions">
          <!-- Ack stays available on a dismissed row only if it was never acked —
               claiming something already closed out is not a useful action. -->
          <button
            v-if="!a.acked_at && !a.dismissed_at"
            class="ack"
            :disabled="store.acking.has(a.ticket_id)"
            :title="'Mark as owned and update the Slack message'"
            @click="ack(a.ticket_id)"
          >
            Acknowledge
          </button>
          <Mono v-else-if="a.acked_at && !a.dismissed_at" :size="9" class="done"
            >✓ acknowledged</Mono
          >
          <button
            v-if="!a.dismissed_at"
            class="dismiss"
            :disabled="store.dismissing.has(a.ticket_id)"
            @click="dismiss(a.ticket_id)"
          >
            Dismiss
          </button>
          <Mono v-else :size="9" class="done">✓ dismissed</Mono>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.page {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 40px;
}
.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 14px;
}
.filters {
  margin-left: auto;
  display: flex;
  gap: 8px;
}
.filter {
  font-family: var(--font-mono);
  font-size: 10.5px;
  padding: 5px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink-2);
  cursor: pointer;
}
.error {
  color: var(--accent);
  margin: 0 0 12px;
}
.empty {
  padding: 40px 8px;
  text-align: center;
  color: var(--ink-3);
  border: var(--hairline) dashed var(--line);
  border-radius: var(--radius-card);
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 14px 16px;
  border: var(--hairline) solid var(--line);
  border-left: 2px solid var(--line);
  border-radius: var(--radius-card);
  background: var(--panel);
}
/* Severity reads as the left rail before any text does — same cue as the Slack
   card's coloured attachment bar. */
.card.sev-high {
  border-left-color: oklch(0.72 0.12 25);
}
.card.sev-medium {
  border-left-color: oklch(0.74 0.1 50);
}
.card.dismissed {
  opacity: 0.5;
}
.info {
  flex: 1;
  min-width: 0;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
  text-decoration: none;
}
a.name:hover {
  text-decoration: underline;
}
/* Mirrors the card priority chip (roadmap 0.2) so severity reads the same way
   everywhere in the product. */
.sev-chip {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 1px 5px;
  border-radius: var(--radius-chip);
  border: var(--hairline) solid var(--line);
  color: var(--ink-2);
  background: var(--chip-bg);
  flex: 0 0 auto;
}
.sev-chip-high {
  color: oklch(0.45 0.18 25);
  background: oklch(0.95 0.05 25);
  border-color: oklch(0.72 0.12 25);
}
.sev-chip-medium {
  color: oklch(0.48 0.14 50);
  background: oklch(0.95 0.05 50);
  border-color: oklch(0.74 0.1 50);
}
.sev-chip-low {
  color: var(--ink-3);
  border-style: dashed;
}
.evidence {
  margin: 8px 0;
  padding-left: 10px;
  border-left: 2px solid var(--line);
  font-size: 12px;
  color: var(--ink-2);
  line-height: 1.45;
}
.meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  color: var(--ink-3);
}
.state-pending {
  color: var(--ink-2);
}
.tid {
  opacity: 0.6;
}
.slack {
  font-size: 9px;
  color: var(--ink-2);
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex: 0 0 auto;
}
.dismiss,
.ack {
  font-family: var(--font-mono);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 6px 12px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink-2);
  cursor: pointer;
}
.dismiss:not(:disabled):hover,
.ack:not(:disabled):hover {
  border-color: var(--accent);
  color: var(--accent);
}
.dismiss:disabled,
.ack:disabled {
  opacity: 0.4;
  cursor: default;
}
/* Acknowledge is the more common action of the two — it reads first without
   becoming a filled button, which would outrank the severity chip. */
.ack {
  color: var(--ink-1);
  border-color: var(--ink-3);
}
.done {
  color: var(--ink-3);
}
.acked-by {
  color: var(--ink-3);
}
/* The ack succeeded and only its mirror failed, so this is a caveat, not an
   error: same weight as the other meta, tinted to be noticed once. */
.warn {
  color: var(--accent);
}
html[data-theme='dark'] .sev-chip-high {
  color: oklch(0.85 0.13 25);
  background: oklch(0.28 0.06 25);
  border-color: oklch(0.45 0.1 25);
}
html[data-theme='dark'] .sev-chip-medium {
  color: oklch(0.85 0.12 50);
  background: oklch(0.28 0.06 50);
  border-color: oklch(0.45 0.09 50);
}
</style>

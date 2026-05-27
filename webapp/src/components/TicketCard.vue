<!-- TicketCard. Reference: tasks.md T033, plan §8b.
     Renders id mono · ago, title (line-clamped), summary, meta row, optional
     follow-up + notes row. -->
<script setup lang="ts">
import { computed } from 'vue';
import Mono from './Mono.vue';
import ResolutionChip from './ResolutionChip.vue';
import { useFollowupsStore } from '@/stores/followups';
import { useNoteEntriesStore } from '@/stores/noteEntries';
import { countNoteLines, useNotesStore } from '@/stores/notes';
import { useTicketsStore } from '@/stores/tickets';
import { useTweaksStore } from '@/stores/tweaks';
import { formatAgoFromDate } from '@/utils/time';
import type { Ticket } from '@/types/api';

interface Props {
  ticket: Ticket;
  overridden?: boolean;
  /** Flyout-focused card (single-click open). */
  selected?: boolean;
  /** Member of the bulk-selection set (Cmd/Ctrl/Shift+click). Renders the
   *  accent ring used by Phase 12 bulk actions; distinct from `selected`. */
  multiSelected?: boolean;
  /** Keyboard-triage cursor (NFR-007). Additive: a dashed outline distinct
   *  from `selected`/`multiSelected`; the j/k cursor sits here without opening
   *  the flyout. */
  focused?: boolean;
}
const props = withDefaults(defineProps<Props>(), {
  overridden: false,
  selected: false,
  multiSelected: false,
  focused: false,
});

const tweaks = useTweaksStore();
const followups = useFollowupsStore();
const notes = useNotesStore();
const noteEntries = useNoteEntriesStore();
const tickets = useTicketsStore();

async function onResolveClick(e: Event) {
  e.stopPropagation();
  if (props.ticket.resolved_at) {
    await tickets.reopen(props.ticket.id);
  } else {
    await tickets.markResolved(props.ticket.id);
  }
}

const dense = computed(() => tweaks.density === 'compact');
const rich = computed(() => tweaks.density === 'comfy');
const showSummary = computed(() => tweaks.showSummary && !dense.value);
const confColor = computed(() => (props.ticket.ai_confidence < 0.5 ? '#c34a2b' : 'var(--ink-3)'));
const updatedAgo = computed(() => formatAgoFromDate(props.ticket.updated_at));

// Follow-up chip (T050): `F/U in 15m` while pending, `due now` once due.
const followupDue = computed(() => followups.isDue(props.ticket.id));
const followupLabel = computed(() => {
  const f = followups.get(props.ticket.id);
  if (!f) return null;
  if (followupDue.value) return 'Follow up · due now';
  const mins = Math.round((Date.parse(f.due_at) - followups.now) / 60_000);
  return mins < 60 ? `F/U in ${mins}m` : `F/U in ${Math.round(mins / 60)}h`;
});

// Notes chip: legacy line count + time-tabled entries count.
const noteLines = computed(
  () => countNoteLines(notes.bodyOf(props.ticket.id)) + noteEntries.countOf(props.ticket.id),
);

// Reply state — derived from the Intercom-visible thread.
const adminReplyCount = computed(() => props.ticket.parts.filter((p) => p.is_admin).length);
const lastPart = computed(() => props.ticket.parts[props.ticket.parts.length - 1]);
/** True when the most-recent visible message is from us — i.e. the ball is
 *  in the customer's court. Useful triage hint: skip vs follow-up. */
const awaitingCustomer = computed(() => adminReplyCount.value > 0 && !!lastPart.value?.is_admin);

// Intercom team notes (separate from the operator's local `note`).
const teamNoteCount = computed(() => props.ticket.internal_notes.length);

const isClosed = computed(() => props.ticket.state === 'closed');
</script>

<template>
  <article
    class="card"
    :class="{
      dense,
      rich,
      selected: props.selected,
      'multi-selected': props.multiSelected,
      focused: props.focused,
      overridden: props.overridden,
    }"
    :data-selected="props.multiSelected ? 'true' : undefined"
    draggable="true"
  >
    <div v-if="props.overridden" class="override-marker" title="Manually moved" />

    <header>
      <Mono>{{ props.ticket.id }}</Mono>
      <Mono>{{ updatedAgo }}</Mono>
      <button
        class="resolve-icon"
        :title="props.ticket.resolved_at ? 'Reopen' : 'Mark resolved'"
        @click="onResolveClick"
      >
        {{ props.ticket.resolved_at ? '↺' : '✓' }}
      </button>
    </header>

    <h3 class="title">{{ props.ticket.title }}</h3>

    <p v-if="showSummary" class="summary">{{ props.ticket.summary }}</p>

    <div class="meta">
      <span class="customer">{{ props.ticket.author.name ?? '—' }}</span>
      <Mono v-if="props.ticket.parts.length > 1" :color="'var(--ink-3)'" :size="9.5">
        {{ props.ticket.parts.length }} msgs
      </Mono>
      <Mono v-if="tweaks.showConfidence" :color="confColor" :size="9.5" class="conf">
        {{ Math.round(props.ticket.ai_confidence * 100) }}%
      </Mono>
    </div>

    <div
      v-if="
        followupLabel ||
        noteLines ||
        adminReplyCount ||
        teamNoteCount ||
        awaitingCustomer ||
        isClosed ||
        props.ticket.resolution_chip_state
      "
      class="tags"
    >
      <span v-if="isClosed" class="tag closed">Closed</span>
      <span v-if="awaitingCustomer" class="tag awaiting">Awaiting customer</span>
      <span v-else-if="adminReplyCount" class="tag replied">
        Replied{{ adminReplyCount > 1 ? ` (${adminReplyCount})` : '' }}
      </span>
      <span v-if="teamNoteCount" class="tag team-note">
        Team {{ teamNoteCount === 1 ? 'note' : `notes (${teamNoteCount})` }}
      </span>
      <span v-if="followupLabel" class="tag fu" :class="{ due: followupDue }">
        {{ followupLabel }}
      </span>
      <span v-if="noteLines" class="tag note">Notes ({{ noteLines }})</span>
      <ResolutionChip :ticket="props.ticket" />
    </div>
  </article>
</template>

<style scoped>
.card {
  position: relative;
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-card);
  padding: 11px 12px 12px;
  cursor: grab;
  transition:
    border-color 0.12s,
    background 0.12s,
    box-shadow 0.25s;
}
.card.dense {
  padding: 8px 10px;
}
.card:hover {
  background: var(--hover);
}
.card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
/* Bulk-selection ring (plan §8d). Outer 2 px ring + accent border so it reads
 * distinct from the flyout-focus ring without clashing with .selected. */
.card.multi-selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 2px var(--accent);
}
/* Keyboard-triage cursor (NFR-007). Dashed outline so it reads as "cursor is
 * here" distinct from the solid flyout/bulk rings; outline doesn't shift
 * layout and stacks harmlessly with the selection box-shadows. */
.card.focused {
  outline: 2px dashed var(--accent);
  outline-offset: 1px;
}
.override-marker {
  position: absolute;
  left: -3px;
  top: 14px;
  width: 5px;
  height: 5px;
  background: var(--accent);
  transform: rotate(45deg);
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.resolve-icon {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 11px;
  padding: 2px 4px;
  border-radius: 4px;
  line-height: 1;
  margin-left: 4px;
  flex-shrink: 0;
}
.resolve-icon:hover {
  color: var(--accent);
  background: var(--hover);
}
.card.dense header {
  margin-bottom: 4px;
}
.title {
  margin: 0 0 8px;
  font-size: 13.5px;
  line-height: 1.35;
  color: var(--ink);
  font-weight: 500;
  letter-spacing: -0.005em;
  text-wrap: pretty;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card.dense .title {
  font-size: 12.5px;
  -webkit-line-clamp: 2;
}
.summary {
  margin: 0 0 9px;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card.rich .summary {
  -webkit-line-clamp: 4;
}
.meta {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.customer {
  font-size: 11px;
  color: var(--ink-2);
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conf {
  margin-left: auto;
}
.tags {
  display: flex;
  gap: 5px;
  flex-wrap: wrap;
  margin-top: 8px;
}
.card.dense .tags {
  margin-top: 6px;
}
.tag {
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  padding: 2px 6px;
  border-radius: var(--radius-chip);
  border: var(--hairline) solid var(--line);
  color: var(--ink-2);
  background: var(--chip-bg);
}
.tag.fu.due {
  color: #fff;
  background: var(--accent);
  border-color: var(--accent);
  animation: triagePulse 1.6s ease-in-out infinite;
}
.tag.note {
  color: var(--ink-3);
}
.tag.replied {
  color: oklch(0.45 0.13 145);
  background: oklch(0.95 0.04 145);
  border-color: oklch(0.75 0.08 145);
}
.tag.awaiting {
  color: oklch(0.45 0.13 235);
  background: oklch(0.95 0.04 235);
  border-color: oklch(0.75 0.08 235);
}
.tag.team-note {
  color: oklch(0.45 0.13 285);
  background: oklch(0.95 0.04 285);
  border-color: oklch(0.75 0.08 285);
}
.tag.closed {
  color: var(--ink-3);
  background: transparent;
  border-style: dashed;
}
html[data-theme='dark'] .tag.replied {
  color: oklch(0.85 0.12 145);
  background: oklch(0.25 0.05 145);
  border-color: oklch(0.4 0.08 145);
}
html[data-theme='dark'] .tag.awaiting {
  color: oklch(0.85 0.12 235);
  background: oklch(0.25 0.05 235);
  border-color: oklch(0.4 0.08 235);
}
html[data-theme='dark'] .tag.team-note {
  color: oklch(0.85 0.12 285);
  background: oklch(0.25 0.05 285);
  border-color: oklch(0.4 0.08 285);
}
</style>

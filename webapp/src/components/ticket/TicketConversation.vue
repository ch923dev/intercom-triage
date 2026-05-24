<script setup lang="ts">
import type { Ticket } from '@/types/api';
import { computed } from 'vue';


// ── Conversation timeline ────────────────────────────────────────────────────
// One chronological stream: customer messages, teammate replies, and Intercom
// internal notes — merged + sorted by `created_at`. Customer messages sit left,
// teammate replies right; internal notes (Intercom renderable_type 3) render as
// centred insets so they read as side-channel context, not customer-facing
// messages.

type TimelineKind = 'customer' | 'admin' | 'note';
interface TimelineItem {
  kind: TimelineKind;
  author: { name: string | null };
  body: string;
  created_at: string;
}

const { ticket } = defineProps<{
  ticket: Ticket
}>()

const messageCount = computed(() => ticket.parts.length ?? 0);
const noteCount = computed(() => ticket.internal_notes.length ?? 0);

const timeline = computed<TimelineItem[]>(() => {
  const t = ticket;

  if (!t) return [];

  const items: TimelineItem[] = [
    ...t.parts.map((p) => ({
      kind: (p.is_admin ? 'admin' : 'customer') as TimelineKind,
      author: p.author,
      body: p.body,
      created_at: p.created_at,
    })),
    ...t.internal_notes.map((n) => ({
      kind: 'note' as TimelineKind,
      author: n.author,
      body: n.body,
      created_at: n.created_at,
    })),
  ];

  return items.sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
});

/** Render a single timestamp the way it's read on a card. */
function partTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

/** Up-to-two-letter initials for an avatar; `?` when the name is missing. */
function initials(name: string | null): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((w) => w[0]?.toUpperCase() ?? '').join('') || '?';
}

</script>

<template>
  <div class="convo-pane">
    <div class="convo-head mono">
      <span>Conversation</span>
      <span class="convo-count">
        {{ messageCount }} message{{ messageCount === 1 ? '' : 's' }}
        <template v-if="noteCount">
          · {{ noteCount }} note{{ noteCount === 1 ? '' : 's' }}</template>
      </span>
    </div>

    <p v-if="!timeline.length" class="convo-empty mono">
      No conversation messages yet
    </p>
    <div v-else class="chat">
      <template v-for="(m, i) in timeline" :key="i">
        <!-- Internal note — centred inset, side-channel context. -->
        <div v-if="m.kind === 'note'" class="note-item">
          <div class="note-head">
            <span class="note-tag">Internal note</span>
            <span class="note-author">{{ m.author.name ?? 'Teammate' }}</span>
            <span class="note-time">{{ partTime(m.created_at) }}</span>
          </div>
          <p class="note-body">{{ m.body }}</p>
        </div>

        <!-- Chat message — customer (left) or teammate reply (right). -->
        <div v-else class="chat-row" :class="m.kind">
          <div class="avatar" :class="m.kind">{{ initials(m.author.name) }}</div>
          <div class="bubble-wrap">
            <div class="bubble-head">
              <span class="bubble-author">
                {{ m.author.name ?? (m.kind === 'admin' ? 'Teammate' : 'Customer') }}
              </span>
              <span class="bubble-time">{{ partTime(m.created_at) }}</span>
            </div>
            <div class="bubble" :class="m.kind">{{ m.body }}</div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
/* Conversation pane — its message list scrolls independently. */
.convo-pane {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}
.convo-head {
  flex: 0 0 auto;
  display: flex;
  align-items: baseline;
  gap: 8px;
  padding: 12px 20px;
  border-bottom: var(--hairline) solid var(--line);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--ink-2);
}
.convo-count {
  color: var(--ink-3);
  font-weight: 500;
  letter-spacing: 0;
  text-transform: none;
}
.convo-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-3);
}

@media (max-width: 760px) {
  .convo-pane {
    min-height: 220px;
  }
}


/* ── Conversation timeline — modern chat ──────────────────────────────────── */
.chat {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 11px;
  padding: 16px 20px;
}
.chat-row {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  max-width: 88%;
}
.chat-row.customer {
  align-self: flex-start;
}
.chat-row.admin {
  flex-direction: row-reverse;
  align-self: flex-end;
}
.avatar {
  flex: 0 0 26px;
  width: 26px;
  height: 26px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-mono);
  font-size: 9.5px;
  font-weight: 600;
  color: #fff;
  user-select: none;
}
.avatar.customer {
  background: oklch(0.6 0.04 255);
}
.avatar.admin {
  background: oklch(0.56 0.13 145);
}
.bubble-wrap {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.bubble-head {
  display: flex;
  gap: 6px;
  align-items: baseline;
  padding: 0 2px;
}
.chat-row.admin .bubble-head {
  flex-direction: row-reverse;
}
.bubble-author {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink);
}
.bubble-time {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--ink-3);
}
.bubble {
  font-size: 12.5px;
  line-height: 1.5;
  padding: 8px 11px;
  border-radius: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}
.bubble.customer {
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  color: var(--ink);
  border-top-left-radius: 3px;
}
.bubble.admin {
  background: oklch(0.95 0.04 145);
  border: var(--hairline) solid oklch(0.82 0.06 145);
  color: oklch(0.32 0.07 145);
  border-top-right-radius: 3px;
}
html[data-theme='dark'] .bubble.admin {
  background: oklch(0.3 0.05 145);
  border-color: oklch(0.42 0.07 145);
  color: oklch(0.9 0.07 145);
}

/* Internal note — centred inset, dashed amber, side-channel context. */
.note-item {
  align-self: center;
  width: 88%;
  background: oklch(0.96 0.035 95);
  border: var(--hairline) dashed oklch(0.78 0.09 95);
  border-radius: 8px;
  padding: 7px 10px;
}
html[data-theme='dark'] .note-item {
  background: oklch(0.3 0.035 95);
  border-color: oklch(0.46 0.07 95);
}
.note-head {
  display: flex;
  gap: 6px;
  align-items: baseline;
  margin-bottom: 3px;
}
.note-tag {
  font-family: var(--font-mono);
  font-size: 8.5px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 600;
  color: oklch(0.52 0.12 75);
}
html[data-theme='dark'] .note-tag {
  color: oklch(0.82 0.1 90);
}
.note-author {
  font-size: 11px;
  font-weight: 500;
  color: var(--ink-2);
}
.note-time {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--ink-3);
  margin-left: auto;
}
.note-body {
  margin: 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--ink-2);
  white-space: pre-wrap;
  word-break: break-word;
}
</style>

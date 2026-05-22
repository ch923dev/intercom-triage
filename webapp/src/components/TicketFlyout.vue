<!-- Ticket detail flyout. Reference: tasks.md T050 (follow-up controls),
     T052 (notes section). Right-side panel opened by selecting a card or an
     alarm banner's "Open" action. -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import CatDot from './CatDot.vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useNotesStore } from '@/stores/notes';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import { formatAgoFromDate } from '@/utils/time';

const view = useViewStore();
const tickets = useTicketsStore();
const categories = useCategoriesStore();
const followups = useFollowupsStore();
const notes = useNotesStore();

const ticket = computed(() => tickets.tickets.find((t) => t.id === view.selectedTicketId) ?? null);

const category = computed(() => {
  const id = ticket.value?.category_id;
  return id == null ? null : (categories.categories.find((c) => c.id === id) ?? null);
});

// ── Follow-up ─────────────────────────────────────────────────────────────────

const FU_PRESETS: { label: string; minutes: number | 'eod' }[] = [
  { label: '+15m', minutes: 15 },
  { label: '+1h', minutes: 60 },
  { label: '+4h', minutes: 240 },
  { label: '+EOD', minutes: 'eod' },
  { label: '+24h', minutes: 1440 },
];

const reason = ref('');
const fuBusy = ref(false);
const fuError = ref<string | null>(null);

const followup = computed(() => {
  const id = ticket.value?.id;
  return id ? (followups.get(id) ?? null) : null;
});
const followupDue = computed(() => {
  const id = ticket.value?.id;
  return id ? followups.isDue(id) : false;
});

/** Resolve a preset to an absolute due date. `eod` = today 18:00 local
 *  (rolls to tomorrow if already past). */
function presetDate(minutes: number | 'eod'): Date {
  if (minutes !== 'eod') return new Date(Date.now() + minutes * 60_000);
  const d = new Date();
  d.setHours(18, 0, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  return d;
}

async function setFollowup(minutes: number | 'eod') {
  const id = ticket.value?.id;
  if (!id) return;
  fuBusy.value = true;
  fuError.value = null;
  try {
    await followups.setFollowup(id, presetDate(minutes), reason.value.trim() || null);
  } catch (e) {
    fuError.value = (e as Error).message;
  } finally {
    fuBusy.value = false;
  }
}

async function clearFollowup() {
  const id = ticket.value?.id;
  if (!id) return;
  fuBusy.value = true;
  fuError.value = null;
  try {
    await followups.clearFollowup(id);
  } catch (e) {
    fuError.value = (e as Error).message;
  } finally {
    fuBusy.value = false;
  }
}

async function snooze(mins: number) {
  const id = ticket.value?.id;
  if (!id) return;
  fuBusy.value = true;
  try {
    await followups.snooze(id, mins);
  } catch (e) {
    fuError.value = (e as Error).message;
  } finally {
    fuBusy.value = false;
  }
}

// ── Notes ─────────────────────────────────────────────────────────────────────

const NOTE_PRESETS = [
  'Reply to customer',
  'Escalate to engineering',
  'Waiting on customer',
  'Refund / credit issued',
  'Bug ticket filed',
  'Docs updated',
  'Ready to close',
];

const draft = ref('');
const noteSaving = ref(false);
let saveTimer: ReturnType<typeof setTimeout> | undefined;

/** Debounced write — persists 400 ms after the last keystroke (T052). */
function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => void flushNote(), 400);
}

async function flushNote() {
  const id = ticket.value?.id;
  if (!id) return;
  noteSaving.value = true;
  try {
    await notes.setNote(id, draft.value);
  } finally {
    noteSaving.value = false;
  }
}

function appendPreset(text: string) {
  draft.value = draft.value ? `${draft.value}\n• ${text}` : `• ${text}`;
  scheduleSave();
}

// Re-seed the editable fields whenever the open ticket changes.
watch(
  () => ticket.value?.id,
  (id) => {
    if (saveTimer) clearTimeout(saveTimer);
    reason.value = id ? (followups.get(id)?.reason ?? '') : '';
    draft.value = id ? notes.bodyOf(id) : '';
    fuError.value = null;
  },
  { immediate: true },
);

function close() {
  if (saveTimer) clearTimeout(saveTimer);
  view.closeFlyout();
}

const dueLabel = computed(() => {
  const f = followup.value;
  if (!f) return null;
  const d = new Date(f.due_at);
  return d.toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
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

const messageCount = computed(() => ticket.value?.parts.length ?? 0);
const noteCount = computed(() => ticket.value?.internal_notes.length ?? 0);

const timeline = computed<TimelineItem[]>(() => {
  const t = ticket.value;
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

/** Up-to-two-letter initials for an avatar; `?` when the name is missing. */
function initials(name: string | null): string {
  if (!name) return '?';
  const parts = name.trim().split(/\s+/).slice(0, 2);
  return parts.map((w) => w[0]?.toUpperCase() ?? '').join('') || '?';
}

// ── Title + summary editing ──────────────────────────────────────────────────
// Both fields are AI-generated by default but operator-editable. Edits are
// optimistic via the store; a small "edited" pill + reset button surfaces the
// override. Empty string on PATCH clears it server-side (next sync regenerates).

const titleDraft = ref('');
const summaryDraft = ref('');
const titleEditing = ref(false);
const summaryEditing = ref(false);
const titleSaving = ref(false);
const summarySaving = ref(false);
const editError = ref<string | null>(null);

watch(
  () => ticket.value?.id,
  () => {
    titleDraft.value = ticket.value?.title ?? '';
    summaryDraft.value = ticket.value?.summary ?? '';
    titleEditing.value = false;
    summaryEditing.value = false;
    editError.value = null;
  },
  { immediate: true },
);

async function saveTitle() {
  const id = ticket.value?.id;
  if (!id) return;
  const next = titleDraft.value.trim();
  if (next === (ticket.value?.title ?? '')) {
    titleEditing.value = false;
    return;
  }
  titleSaving.value = true;
  editError.value = null;
  try {
    await tickets.editTicket(id, { title: next });
    titleEditing.value = false;
  } catch (e) {
    editError.value = (e as Error).message;
  } finally {
    titleSaving.value = false;
  }
}

async function saveSummary() {
  const id = ticket.value?.id;
  if (!id) return;
  const next = summaryDraft.value.trim();
  if (next === (ticket.value?.summary ?? '')) {
    summaryEditing.value = false;
    return;
  }
  summarySaving.value = true;
  editError.value = null;
  try {
    await tickets.editTicket(id, { summary: next });
    summaryEditing.value = false;
  } catch (e) {
    editError.value = (e as Error).message;
  } finally {
    summarySaving.value = false;
  }
}

/** Clear the operator override server-side; next sync restores AI value. */
async function resetField(field: 'title' | 'summary') {
  const id = ticket.value?.id;
  if (!id) return;
  editError.value = null;
  try {
    await tickets.editTicket(id, { [field]: '' });
    if (field === 'title') {
      titleDraft.value = ticket.value?.title ?? '';
      titleEditing.value = false;
    } else {
      summaryDraft.value = ticket.value?.summary ?? '';
      summaryEditing.value = false;
    }
  } catch (e) {
    editError.value = (e as Error).message;
  }
}
</script>

<template>
  <Teleport to="body">
    <div v-if="ticket" class="scrim" @click.self="close">
      <div class="modal">
        <header>
          <Mono :size="11">{{ ticket.id }}</Mono>
          <button class="x" title="Close" @click="close">✕</button>
        </header>

        <div class="panes">
          <!-- Conversation — centre pane, scrolls on its own. -->
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

          <!-- Ticket controls — side pane, scrolls on its own. -->
          <aside class="detail-pane">
            <!-- Editable subject. Click to edit; Enter saves, Esc cancels. -->
          <div class="title-row">
            <input
              v-if="titleEditing"
              v-model="titleDraft"
              class="title-input"
              type="text"
              maxlength="200"
              placeholder="Subject…"
              :disabled="titleSaving"
              @keydown.enter.prevent="saveTitle"
              @keydown.esc.prevent="
                () => {
                  titleDraft = ticket?.title ?? '';
                  titleEditing = false;
                }
              "
              @blur="saveTitle"
            />
            <h2 v-else class="title" :class="{ placeholder: !ticket.title }" @click="titleEditing = true">
              {{ ticket.title || 'Add subject…' }}
            </h2>
            <span v-if="ticket.title_user_edited && !titleEditing" class="edited-pill" title="Operator-edited">edited</span>
            <button
              v-if="ticket.title_user_edited && !titleEditing"
              class="reset"
              title="Reset to AI-generated subject"
              @click="resetField('title')"
            >
              ↺
            </button>
          </div>

          <div class="row">
            <CatDot v-if="category" :color="category.color" :size="9" />
            <span class="mono cat">{{ category?.name ?? 'Uncategorized' }}</span>
            <span class="mono dim">{{ formatAgoFromDate(ticket.updated_at) }}</span>
          </div>

          <!-- Editable summary. Click to expand to textarea. -->
          <div class="summary-row">
            <textarea
              v-if="summaryEditing"
              v-model="summaryDraft"
              class="summary-input"
              maxlength="600"
              rows="4"
              placeholder="Add a description…"
              :disabled="summarySaving"
              @keydown.esc.prevent="
                () => {
                  summaryDraft = ticket?.summary ?? '';
                  summaryEditing = false;
                }
              "
              @blur="saveSummary"
            />
            <p
              v-else
              class="summary"
              :class="{ placeholder: !ticket.summary }"
              @click="summaryEditing = true"
            >
              {{ ticket.summary || 'Add a description…' }}
            </p>
            <div v-if="ticket.summary_user_edited && !summaryEditing" class="edit-meta">
              <span class="edited-pill" title="Operator-edited">edited</span>
              <button
                class="reset"
                title="Reset to AI-generated summary"
                @click="resetField('summary')"
              >
                ↺
              </button>
            </div>
          </div>

          <div v-if="editError" class="mono err">{{ editError }}</div>

          <div class="row">
            <span class="customer">{{ ticket.author.name ?? '—' }}</span>
            <a
              v-if="ticket.url"
              class="mono link"
              :href="ticket.url"
              target="_blank"
              rel="noopener"
            >
              Open in Intercom ↗
            </a>
          </div>

          <!-- Follow-up (T050) -->
          <section class="block">
            <div class="mono label">Follow-up</div>

            <div v-if="followup" class="fu-active" :class="{ due: followupDue }">
              <span class="mono">{{ followupDue ? 'Due now' : `Due ${dueLabel}` }}</span>
              <span v-if="followup.reason" class="fu-reason">{{ followup.reason }}</span>
            </div>

            <div v-if="followup && followupDue" class="presets">
              <button class="chip" :disabled="fuBusy" @click="snooze(15)">Snooze 15m</button>
              <button class="chip" :disabled="fuBusy" @click="snooze(60)">Snooze 1h</button>
            </div>

            <input
              v-model="reason"
              class="reason"
              type="text"
              maxlength="80"
              placeholder="Reason (optional, ≤ 80 chars)"
            />
            <div class="presets">
              <button
                v-for="p in FU_PRESETS"
                :key="p.label"
                class="chip"
                :disabled="fuBusy"
                @click="setFollowup(p.minutes)"
              >
                {{ p.label }}
              </button>
              <button v-if="followup" class="chip danger" :disabled="fuBusy" @click="clearFollowup">
                Clear
              </button>
            </div>
            <div v-if="fuError" class="mono err">{{ fuError }}</div>
          </section>

          <!-- Notes (T052) -->
          <section class="block">
            <div class="mono label">
              Next-step notes
              <span v-if="noteSaving" class="dim">· saving…</span>
            </div>
            <textarea
              v-model="draft"
              class="notes"
              rows="5"
              placeholder="How to proceed on this ticket…"
              @input="scheduleSave"
              @blur="flushNote"
            />
            <div class="presets">
              <button v-for="p in NOTE_PRESETS" :key="p" class="chip" @click="appendPreset(p)">
                + {{ p }}
              </button>
            </div>
          </section>
          </aside>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.42);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 40;
}
/* Centred modal: a conversation pane (centre) + a controls pane (side). */
.modal {
  width: min(980px, 95vw);
  height: min(86vh, 820px);
  background: var(--bg);
  border: var(--hairline) solid var(--line);
  border-radius: 14px;
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  animation: triagePop 0.16s ease-out;
}
@keyframes triagePop {
  from {
    opacity: 0;
    transform: scale(0.985);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}
.panes {
  display: flex;
  flex: 1;
  min-height: 0;
}
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
/* Controls pane — title, summary, follow-up, notes; scrolls independently. */
.detail-pane {
  flex: 0 0 320px;
  overflow-y: auto;
  padding: 16px;
  border-left: var(--hairline) solid var(--line);
  background: var(--panel);
  display: flex;
  flex-direction: column;
  gap: 12px;
}
@media (max-width: 760px) {
  .modal {
    width: 96vw;
    height: 92vh;
  }
  .panes {
    flex-direction: column;
  }
  .convo-pane {
    min-height: 220px;
  }
  .detail-pane {
    flex: 0 0 auto;
    border-left: 0;
    border-top: var(--hairline) solid var(--line);
  }
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: var(--hairline) solid var(--line);
}
.x {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 14px;
}
.title-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  color: var(--ink);
  cursor: text;
  flex: 1;
  min-width: 0;
}
.title.placeholder {
  color: var(--ink-3);
  font-weight: 500;
  font-style: italic;
}
.title:hover {
  background: var(--hover);
  border-radius: 4px;
  margin: -2px -4px;
  padding: 2px 4px;
}
.title-input {
  flex: 1;
  font-family: var(--font-sans);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  color: var(--ink);
  padding: 2px 4px;
  border: var(--hairline) solid var(--accent);
  border-radius: 4px;
  background: var(--panel);
}
.summary-row {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.summary-input {
  flex: 1;
  font-family: var(--font-sans);
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink);
  padding: 6px 8px;
  border: var(--hairline) solid var(--accent);
  border-radius: var(--radius-chip);
  background: var(--panel);
  resize: vertical;
}
.summary.placeholder {
  color: var(--ink-3);
  font-style: italic;
}
.edit-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
}
.edited-pill {
  font-family: var(--font-mono);
  font-size: 8.5px;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  color: var(--ink-3);
  background: var(--chip-bg);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 1px 5px;
  white-space: nowrap;
  align-self: flex-start;
}
.reset {
  font-family: var(--font-mono);
  font-size: 11px;
  background: transparent;
  border: 0;
  color: var(--ink-3);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
}
.reset:hover {
  color: var(--accent);
  background: var(--hover);
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.cat {
  color: var(--ink-2);
}
.dim {
  color: var(--ink-3);
}
.summary {
  margin: 0;
  font-size: 12.5px;
  line-height: 1.5;
  color: var(--ink-2);
}
.customer {
  font-size: 12px;
  color: var(--ink);
}
.link {
  margin-left: auto;
  color: var(--accent);
  text-decoration: none;
}
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
.fu-active {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 6px 9px;
  border-radius: var(--radius-chip);
  background: var(--chip-bg);
  border: var(--hairline) solid var(--line);
}
.fu-active.due {
  background: var(--accent-soft-2);
  border-color: var(--accent);
}
.fu-reason {
  font-size: 11.5px;
  color: var(--ink-2);
}
.reason {
  font-family: var(--font-sans);
  font-size: 12px;
  padding: 6px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  color: var(--ink);
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
.chip:disabled {
  opacity: 0.5;
  cursor: default;
}
.chip.danger {
  color: var(--accent);
  border-color: var(--accent);
}
.notes {
  font-family: var(--font-sans);
  font-size: 12px;
  line-height: 1.5;
  padding: 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  color: var(--ink);
  resize: vertical;
}
.err {
  color: var(--accent);
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

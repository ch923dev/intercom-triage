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
</script>

<template>
  <Teleport to="body">
    <div v-if="ticket" class="scrim" @click.self="close">
      <aside class="flyout">
        <header>
          <Mono :size="11">{{ ticket.id }}</Mono>
          <button class="x" title="Close" @click="close">✕</button>
        </header>

        <div class="body">
          <h2 class="title">{{ ticket.title ?? '—' }}</h2>

          <div class="row">
            <CatDot v-if="category" :color="category.color" :size="9" />
            <span class="mono cat">{{ category?.name ?? 'Uncategorized' }}</span>
            <span class="mono dim">{{ formatAgoFromDate(ticket.updated_at) }}</span>
          </div>

          <p class="summary">{{ ticket.summary }}</p>

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
        </div>
      </aside>
    </div>
  </Teleport>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.28);
  display: flex;
  justify-content: flex-end;
  z-index: 40;
}
.flyout {
  width: 420px;
  max-width: 92vw;
  height: 100%;
  background: var(--bg);
  border-left: var(--hairline) solid var(--line);
  box-shadow: var(--shadow);
  display: flex;
  flex-direction: column;
  animation: triageSlide 0.16s ease-out;
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
.body {
  padding: 16px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.title {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  color: var(--ink);
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
</style>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';
import { useNotesStore } from '@/stores/notes';

const { ticketId } = defineProps<{ ticketId: string }>();
const notes = useNotesStore();

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
const saving = ref(false);
const open = ref(false);
let saveTimer: ReturnType<typeof setTimeout> | undefined;

const hasLegacyNote = computed(() => notes.bodyOf(ticketId).length > 0);

watch(
  () => ticketId,
  (id) => {
    if (saveTimer) clearTimeout(saveTimer);
    draft.value = id ? notes.bodyOf(id) : '';
    open.value = false;
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  if (saveTimer) clearTimeout(saveTimer);
});

function scheduleSave() {
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = setTimeout(() => void flushNote(), 400);
}

async function flushNote() {
  saving.value = true;
  try {
    await notes.setNote(ticketId, draft.value);
  } finally {
    saving.value = false;
  }
}

function appendPreset(text: string) {
  draft.value = draft.value ? `${draft.value}\n• ${text}` : `• ${text}`;
  scheduleSave();
}
</script>

<template>
  <details v-if="hasLegacyNote" :open="open" class="legacy-note">
    <summary class="mono dim" @click.prevent="open = !open">
      Legacy note {{ open ? '▾' : '▸' }}
      <span v-if="saving" class="dim">· saving…</span>
    </summary>
    <textarea v-model="draft" class="notes" rows="3" @input="scheduleSave" @blur="flushNote" />
    <div class="presets">
      <button v-for="p in NOTE_PRESETS" :key="p" class="chip" @click="appendPreset(p)">
        + {{ p }}
      </button>
    </div>
  </details>
</template>

<style scoped>
.legacy-note {
  margin-bottom: 10px;
}
.legacy-note summary {
  cursor: pointer;
  padding: 4px 0;
}
.dim {
  color: var(--ink-3);
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
</style>

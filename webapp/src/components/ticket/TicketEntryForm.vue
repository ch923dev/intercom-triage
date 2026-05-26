<script setup lang="ts">
import { ref, watch } from 'vue';
import { useAttachmentsStore } from '@/stores/attachments';
import { useFollowupsStore } from '@/stores/followups';
import { useNoteEntriesStore } from '@/stores/noteEntries';

const { ticketId } = defineProps<{ ticketId: string }>();
const noteEntries = useNoteEntriesStore();
const attachments = useAttachmentsStore();
const followups = useFollowupsStore();

const TIMER_PRESETS: { label: string; minutes: number | null }[] = [
  { label: 'off', minutes: null },
  { label: '5m', minutes: 5 },
  { label: '15m', minutes: 15 },
  { label: '30m', minutes: 30 },
  { label: '1h', minutes: 60 },
];

const draft = ref('');
const timer = ref<number | null>(null);
const reason = ref('');
const saving = ref(false);
const error = ref<string | null>(null);
const pendingFiles = ref<File[]>([]);

watch(
  () => ticketId,
  () => {
    draft.value = '';
    reason.value = '';
    timer.value = null;
    error.value = null;
    pendingFiles.value = [];
  },
);

function removePending(idx: number) {
  pendingFiles.value = pendingFiles.value.filter((_, i) => i !== idx);
}

function onTextareaPaste(e: ClipboardEvent) {
  const files = e.clipboardData?.files;
  if (!files || files.length === 0) return;
  pendingFiles.value = [...pendingFiles.value, ...Array.from(files)];
}

function onTextareaDrop(e: DragEvent) {
  e.preventDefault();
  const files = e.dataTransfer?.files;
  if (!files || files.length === 0) return;
  pendingFiles.value = [...pendingFiles.value, ...Array.from(files)];
}

function pendingSizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

async function addEntry() {
  const body = draft.value.trim();
  if (body.length === 0) return;
  saving.value = true;
  error.value = null;
  const armedTimer = timer.value !== null;
  const filesToUpload = pendingFiles.value;
  try {
    const saved = await noteEntries.addEntry(
      ticketId,
      body,
      timer.value,
      reason.value.trim() || null,
    );
    if (filesToUpload.length > 0) {
      await Promise.all(
        filesToUpload.map((f) => attachments.upload(f, 'entry', String(saved.id), ticketId)),
      );
    }
    draft.value = '';
    reason.value = '';
    timer.value = null;
    pendingFiles.value = [];
    if (armedTimer) {
      await followups.load();
    }
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="entry-form">
    <textarea
      v-model="draft"
      class="notes"
      rows="3"
      placeholder="What's the next step? (paste or drop files to attach to this entry)"
      @paste="onTextareaPaste"
      @drop="onTextareaDrop"
      @dragover.prevent
    />
    <div v-if="pendingFiles.length" class="pending-files">
      <span v-for="(f, i) in pendingFiles" :key="i" class="att-pill pending-pill" :title="f.name">
        <span>📎 {{ f.name }} · {{ pendingSizeLabel(f.size) }}</span>
        <button class="att-x att-x-inline" title="Remove" @click="removePending(i)">×</button>
      </span>
    </div>
    <div class="presets timer-row">
      <span class="mono dim timer-label">Timer:</span>
      <button
        v-for="p in TIMER_PRESETS"
        :key="p.label"
        class="chip"
        :class="{ active: timer === p.minutes }"
        @click="timer = p.minutes"
      >
        {{ p.label }}
      </button>
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
        class="chip primary"
        :disabled="saving || draft.trim().length === 0"
        @click="addEntry"
      >
        {{ saving ? 'Adding…' : 'Add entry' }}
      </button>
    </div>
    <div v-if="error" class="mono err">{{ error }}</div>
  </div>
</template>

<style scoped>
.entry-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
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
.chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.chip.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.dim {
  color: var(--ink-3);
}
.err {
  color: var(--accent);
}
.pending-files {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.pending-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px 8px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  font-family: var(--font-mono);
  font-size: 10px;
}
.att-x {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: var(--hairline) solid var(--line);
  background: var(--panel);
  color: var(--ink);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}
.att-x:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.att-x-inline {
  margin-left: 4px;
}
.timer-row {
  align-items: center;
}
.timer-label {
  margin-right: 4px;
}
</style>

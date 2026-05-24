<script setup lang="ts">
import { computed, ref } from 'vue';
import AttachmentList from '../AttachmentList.vue';
import { useAttachmentsStore } from '@/stores/attachments';
import { useNoteEntriesStore } from '@/stores/noteEntries';

const { ticketId } = defineProps<{ ticketId: string }>();
const noteEntries = useNoteEntriesStore();
const attachments = useAttachmentsStore();

const error = ref<string | null>(null);
const entries = computed(() => noteEntries.entriesOf(ticketId));

async function removeEntry(entryId: number) {
  try {
    await noteEntries.deleteEntry(entryId);
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function onRemoveAttachment(id: number) {
  try {
    await attachments.remove(id);
  } catch (e) {
    error.value = (e as Error).message;
  }
}

function entryTimeLabel(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
</script>

<template>
  <div>
    <ul v-if="entries.length" class="entry-timeline">
      <li v-for="e in entries" :key="e.id" class="entry-row">
        <div class="entry-head">
          <span class="mono dim">{{ entryTimeLabel(e.created_at) }}</span>
          <button class="entry-x" title="Delete entry" @click="removeEntry(e.id)">×</button>
        </div>
        <p class="entry-body">{{ e.body }}</p>
        <div v-if="e.timer_min !== null" class="entry-timer mono dim">
          ⏱ {{ e.timer_min }}m<span v-if="e.reason"> · "{{ e.reason }}"</span>
        </div>
        <AttachmentList :items="attachments.byEntry(e.id)" @remove="onRemoveAttachment" />
      </li>
    </ul>
    <p v-else class="dim entry-empty">No entries yet — add the first one below.</p>
    <div v-if="error" class="mono err">{{ error }}</div>
  </div>
</template>

<style scoped>
.entry-timeline {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.entry-row {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-card);
  padding: 6px 8px;
  background: var(--panel);
}
.entry-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 2px;
}
.entry-x {
  border: none;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.entry-x:hover {
  color: var(--accent);
}
.entry-body {
  margin: 2px 0;
  white-space: pre-wrap;
  font-size: 13px;
}
.entry-timer {
  margin-top: 2px;
  font-size: 11px;
}
.entry-empty {
  margin: 0 0 12px;
  font-size: 12px;
}
.dim {
  color: var(--ink-3);
}
.err {
  color: var(--accent);
}
</style>

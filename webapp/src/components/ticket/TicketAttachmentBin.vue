<script setup lang="ts">
import { ref } from 'vue';
import AttachmentDropzone from '../AttachmentDropzone.vue';
import AttachmentList from '../AttachmentList.vue';
import { useAttachmentsStore } from '@/stores/attachments';

const { ticketId } = defineProps<{ ticketId: string }>();
const attachments = useAttachmentsStore();
const error = ref<string | null>(null);

async function onFiles(files: File[]) {
  try {
    await Promise.all(
      files.map((f) => attachments.upload(f, 'ticket', ticketId, ticketId)),
    );
  } catch (e) {
    error.value = (e as Error).message;
  }
}

async function onRemove(id: number) {
  try {
    await attachments.remove(id);
  } catch (e) {
    error.value = (e as Error).message;
  }
}
</script>

<template>
  <div class="ticket-bin">
    <div class="mono dim ticket-bin-label">Ticket files</div>
    <AttachmentDropzone @files="onFiles" />
    <AttachmentList :items="attachments.byTicket(ticketId)" @remove="onRemove" />
    <div v-if="error" class="mono err">{{ error }}</div>
  </div>
</template>

<style scoped>
.ticket-bin {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}
.ticket-bin-label {
  margin-top: 4px;
}
.dim {
  color: var(--ink-3);
}
.err {
  color: var(--accent);
}
</style>

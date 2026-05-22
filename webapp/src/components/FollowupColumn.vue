<!-- One column of the follow-up board. Drop target for drag-to-reschedule —
     dropping a card here computes a new due_at per the bucket's rules (or
     calls markFired for the `fired` column). Header shows label + count;
     body is a scrollable stack of FollowupCards. -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import FollowupCard from './FollowupCard.vue';
import Mono from './Mono.vue';
import { useFollowupsStore, type Bucket } from '@/stores/followups';
import type { Followup } from '@/types/api';

interface Props {
  label: string;
  followups: Followup[];
  bucket: Bucket;
}
const props = defineProps<Props>();

const followupsStore = useFollowupsStore();

/** dragenter/dragleave fire on every child element, so we ref-count entries
 *  to know when the cursor has actually left the column (count back to 0). */
const dragCounter = ref(0);
const isDragover = computed(() => dragCounter.value > 0);

function onDragEnter() {
  dragCounter.value++;
}
function onDragLeave() {
  dragCounter.value = Math.max(0, dragCounter.value - 1);
}
async function onDrop(e: DragEvent) {
  dragCounter.value = 0;
  const ticketId = e.dataTransfer?.getData('text/plain') ?? '';
  if (ticketId === '') return;
  await followupsStore.rescheduleToBucket(ticketId, props.bucket);
}
</script>

<template>
  <section
    class="column"
    :class="{ dragover: isDragover }"
    @dragover.prevent
    @dragenter.prevent="onDragEnter"
    @dragleave="onDragLeave"
    @drop.prevent="onDrop"
  >
    <header>
      <div class="name">{{ props.label }}</div>
      <Mono class="count">{{ props.followups.length }}</Mono>
    </header>
    <div class="cards">
      <FollowupCard v-for="f in props.followups" :key="f.ticket_id" :followup="f" />
      <div v-if="props.followups.length === 0" class="empty mono">empty</div>
    </div>
  </section>
</template>

<style scoped>
.column {
  flex: 0 0 280px;
  display: flex;
  flex-direction: column;
  border-right: var(--hairline) solid var(--line-soft);
  transition: background 80ms ease;
}
.column.dragover {
  background: var(--hover);
}
header {
  padding: 14px 14px 10px;
  border-bottom: var(--hairline) solid var(--line);
  display: flex;
  align-items: center;
  gap: 8px;
  position: sticky;
  top: 0;
  background: var(--bg);
  z-index: 1;
}
.name {
  font-size: 12.5px;
  color: var(--ink);
  font-weight: 500;
  letter-spacing: -0.005em;
}
.count {
  margin-left: auto;
}
.cards {
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  flex: 1;
}
.empty {
  text-align: center;
  padding: 24px 8px;
  border: var(--hairline) dashed var(--line);
  border-radius: 3px;
  color: var(--ink-3);
}
</style>

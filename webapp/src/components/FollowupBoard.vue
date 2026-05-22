<!-- Follow-up board — five time-bucketed columns. Reuses the horizontal-scroll
     layout of the main Board. Read of `followups.buckets` re-evaluates every
     alarm tick, so cards re-bucket live. -->
<script setup lang="ts">
import FollowupColumn from './FollowupColumn.vue';
import { BUCKET_LABEL, BUCKET_ORDER, useFollowupsStore } from '@/stores/followups';

const followups = useFollowupsStore();
</script>

<template>
  <div class="board">
    <FollowupColumn
      v-for="b in BUCKET_ORDER"
      :key="b"
      :label="BUCKET_LABEL[b]"
      :followups="followups.buckets[b]"
    />
    <div class="board-tail" />
  </div>
</template>

<style scoped>
.board {
  flex: 1;
  display: flex;
  overflow-x: auto;
  overflow-y: hidden;
}
.board-tail {
  flex: 1;
  min-width: 40px;
}
</style>

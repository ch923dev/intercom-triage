<!-- One column of the follow-up board. Static (no drag) — header with label +
     count, body is a scrollable stack of FollowupCards. -->
<script setup lang="ts">
import FollowupCard from './FollowupCard.vue';
import Mono from './Mono.vue';
import type { Followup } from '@/types/api';

interface Props {
  label: string;
  followups: Followup[];
}
const props = defineProps<Props>();
</script>

<template>
  <section class="column">
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

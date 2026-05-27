<!-- Cost meter (roadmap 1.4). Shows today's estimated OpenRouter spend plus a
     per-model breakdown. Counters live in the backend process and reset on
     restart, so this is "spend since the backend last started". -->
<script setup lang="ts">
import { computed, onMounted } from 'vue';
import Mono from '../Mono.vue';
import { useCostStore } from '@/stores/cost';

const cost = useCostStore();

onMounted(() => {
  void cost.refresh();
});

/** Format a USD figure with enough precision for sub-cent estimates. */
function usd(n: number): string {
  if (n === 0) return '$0.00';
  if (n < 0.01) return `$${n.toFixed(4)}`;
  return `$${n.toFixed(2)}`;
}

const today = computed(() => new Date().toISOString().slice(0, 10));
const todayBuckets = computed(() => cost.usage.filter((b) => b.date === today.value));
</script>

<template>
  <section>
    <Mono>OpenRouter spend</Mono>
    <div class="headline">
      <span class="amount">{{ usd(cost.todayCostUsd) }}</span>
      <span class="mono label">today (est.)</span>
    </div>

    <ul v-if="todayBuckets.length" class="models">
      <li v-for="b in todayBuckets" :key="b.model" class="model-row">
        <span class="mono model">{{ b.model }}</span>
        <span class="mono cost">{{ usd(b.estimated_cost_usd) }}</span>
        <span class="mono toks">{{ b.total_tokens.toLocaleString() }} tok</span>
      </li>
    </ul>
    <p v-else-if="cost.loaded" class="hint">No AI calls yet today.</p>

    <p class="hint">
      Estimated from token usage × per-model pricing. Counters reset when the backend restarts.
    </p>
  </section>
</template>

<style scoped>
section {
  padding: 16px 0;
  border-bottom: var(--hairline) solid var(--line-soft);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.headline {
  display: flex;
  align-items: baseline;
  gap: 8px;
}
.amount {
  font-family: var(--font-mono);
  font-size: 20px;
  color: var(--ink);
  font-weight: 600;
}
.label {
  font-size: 11px;
  color: var(--ink-3);
}
.models {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.model-row {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 11px;
}
.model {
  flex: 1;
  color: var(--ink-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cost {
  color: var(--ink);
}
.toks {
  color: var(--ink-3);
  min-width: 64px;
  text-align: right;
}
.hint {
  margin: 0;
  font-size: 11px;
  color: var(--ink-3);
}
</style>

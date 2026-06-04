<script setup lang="ts">
import Mono from '../Mono.vue';
import { useTweaksStore } from '@/stores/tweaks';

const tweaks = useTweaksStore();

function onAutoSyncChange(event: Event) {
  const raw = Number((event.target as HTMLSelectElement).value) as 0 | 30 | 60 | 300;
  tweaks.setAutoSyncSeconds(raw);
}
</script>

<template>
  <section>
    <Mono>Background sync</Mono>
    <div class="row">
      <select class="sync-select" :value="tweaks.autoSyncSeconds" @change="onAutoSyncChange">
        <option :value="0">Off</option>
        <option :value="30">30s</option>
        <option :value="60">1m</option>
        <option :value="300">5m</option>
      </select>
    </div>
    <p class="hint">Refreshes the board silently when the backend poller ingests new tickets.</p>
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
.row {
  display: flex;
  gap: 8px;
  align-items: center;
}
.hint {
  margin: 0;
  font-size: 11px;
  color: var(--ink-3);
}
.sync-select {
  padding: 5px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink);
  font-family: var(--font-mono);
  font-size: 12px;
  cursor: pointer;
}
</style>

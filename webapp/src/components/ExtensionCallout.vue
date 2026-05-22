<!-- Extension discovery callout. Reference: tasks.md T039 — plan §2.
     A persistent but dismissible banner pointing the operator at the Chrome
     extension. Dismissal is remembered in localStorage. -->
<script setup lang="ts">
import { ref } from 'vue';
import Mono from './Mono.vue';

const STORAGE_KEY = 'triage-callout-dismissed-v1';

const dismissed = ref(localStorage.getItem(STORAGE_KEY) === '1');

function dismiss() {
  dismissed.value = true;
  localStorage.setItem(STORAGE_KEY, '1');
}
</script>

<template>
  <div v-if="!dismissed" class="callout">
    <span class="dot" />
    <div class="text">
      <Mono :size="10">Chrome extension</Mono>
      <span>
        Triage also runs as a toolbar popup. Load <code>extension/</code> via
        <code>chrome://extensions</code> → enable Developer mode → "Load unpacked".
      </span>
    </div>
    <button class="x" aria-label="Dismiss" @click="dismiss">✕</button>
  </div>
</template>

<style scoped>
.callout {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 20px;
  background: var(--accent-soft);
  border-bottom: var(--hairline) solid var(--line);
  flex: 0 0 auto;
}
.dot {
  width: 6px;
  height: 6px;
  background: var(--accent);
  border-radius: 50%;
  flex: 0 0 auto;
}
.text {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 11.5px;
  color: var(--ink-2);
}
code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--chip-bg);
  padding: 1px 4px;
  border-radius: 2px;
  color: var(--ink);
}
.x {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 12px;
  flex: 0 0 auto;
}
</style>

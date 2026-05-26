<!-- Collapsible detail-pane section. Wraps the flyout's `.block` pattern with a
     clickable mono-label header; collapsed state is sticky per `storageKey`
     (localStorage), shared across tickets. -->
<script setup lang="ts">
import { ref } from 'vue';

const { title, storageKey } = defineProps<{
  title: string;
  storageKey: string;
}>();

const LS_PREFIX = 'triage.flyout.collapse.';

function readCollapsed(key: string): boolean {
  try {
    return localStorage.getItem(LS_PREFIX + key) === '1';
  } catch {
    return false;
  }
}

const collapsed = ref(readCollapsed(storageKey));

function toggle() {
  collapsed.value = !collapsed.value;
  try {
    localStorage.setItem(LS_PREFIX + storageKey, collapsed.value ? '1' : '0');
  } catch {
    /* storage disabled / quota — collapse still works for the session */
  }
}
</script>

<template>
  <section class="block">
    <button class="head" type="button" :aria-expanded="!collapsed" @click="toggle">
      <span class="mono label">{{ title }}</span>
      <span class="chev" :class="{ collapsed }" aria-hidden="true">▾</span>
    </button>
    <div v-show="!collapsed" class="body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.block {
  border-top: var(--hairline) solid var(--line);
  padding-top: 12px;
}
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  padding: 0;
  background: transparent;
  border: 0;
  cursor: pointer;
}
.label {
  color: var(--ink-3);
}
.head:hover .label {
  color: var(--ink-2);
}
.chev {
  color: var(--ink-3);
  font-size: 10px;
  line-height: 1;
  transition: transform 0.14s ease;
}
.chev.collapsed {
  transform: rotate(-90deg);
}
.body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 8px;
}
</style>

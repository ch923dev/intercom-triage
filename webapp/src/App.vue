<!-- App shell. Loads categories + tickets on mount and renders top bar + board.
     Flyout, filter drawer, settings drawer, keyboard nav land in later tasks. -->
<script setup lang="ts">
import { onMounted } from 'vue';
import Board from '@/components/Board.vue';
import Topbar from '@/components/Topbar.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';

const categories = useCategoriesStore();
const settings = useSettingsStore();
const tickets = useTicketsStore();

onMounted(async () => {
  await categories.load();
  await tickets.refresh(settings.filter);
});
</script>

<template>
  <div class="app">
    <Topbar />
    <div v-if="categories.loading" class="status mono">Loading…</div>
    <div v-else-if="categories.error" class="status error mono">
      Backend unreachable — {{ categories.error }}
    </div>
    <Board v-else />
    <footer>
      <span class="mono">
        Last {{ settings.lookbackValue }} {{ settings.lookbackUnit }} · auto-categorized · drag to override
      </span>
      <span class="mono">●</span>
    </footer>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.status {
  padding: 40px 20px;
  text-align: center;
  color: var(--ink-3);
}
.status.error {
  color: var(--accent);
}
footer {
  padding: 8px 20px;
  border-top: var(--hairline) solid var(--line);
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
  color: var(--ink-3);
}
</style>

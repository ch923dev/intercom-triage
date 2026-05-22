<!-- App shell. Loads settings + categories + tickets on mount, renders the top
     bar and the active page (board / categories / proposals), and owns the
     global keyboard shortcuts (T036) and the settings drawer (T035). -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue';
import Board from '@/components/Board.vue';
import CategoriesPage from '@/components/CategoriesPage.vue';
import ExtensionCallout from '@/components/ExtensionCallout.vue';
import ProposalsPage from '@/components/ProposalsPage.vue';
import SettingsDrawer from '@/components/SettingsDrawer.vue';
import Topbar from '@/components/Topbar.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';

const categories = useCategoriesStore();
const settings = useSettingsStore();
const tickets = useTicketsStore();
const view = useViewStore();

const COLUMN_STEP = 296; // column width (280) + gutter

onMounted(async () => {
  await settings.load();
  await categories.load();
  // A degraded backend (no Intercom token) makes `/tickets/fetch` throw — the
  // board just stays empty in that case, so swallow it here.
  await tickets.refresh(settings.filter).catch(() => undefined);
});

/** Global shortcuts (T036): `r` refreshes, ←/→ scroll the board columns. */
function onKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement | null;
  if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;

  if (e.key === 'r') {
    e.preventDefault();
    void tickets.refresh(settings.filter);
    return;
  }
  if (view.view !== 'board') return;
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    const board = document.querySelector<HTMLElement>('.board');
    if (!board) return;
    e.preventDefault();
    board.scrollBy({
      left: e.key === 'ArrowRight' ? COLUMN_STEP : -COLUMN_STEP,
      behavior: 'smooth',
    });
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown));
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown));
</script>

<template>
  <div class="app">
    <Topbar />
    <ExtensionCallout />

    <div v-if="categories.loading" class="status mono">Loading…</div>
    <div v-else-if="categories.error" class="status error mono">
      Backend unreachable — {{ categories.error }}
    </div>
    <template v-else>
      <Board v-if="view.view === 'board'" />
      <CategoriesPage v-else-if="view.view === 'categories'" />
      <ProposalsPage v-else />
    </template>

    <footer>
      <span class="mono">
        Last {{ settings.lookbackValue }} {{ settings.lookbackUnit }} · auto-categorized · drag to
        override
      </span>
      <span class="mono">r refresh · ←/→ columns</span>
    </footer>

    <SettingsDrawer />
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

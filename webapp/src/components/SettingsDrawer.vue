<!-- Settings drawer. Right-side panel with display tweaks, board filters,
     AI settings, desktop notifications, and background sync. Each section
     is a focused child component under ./settings/. -->
<script setup lang="ts">
import Mono from './Mono.vue';
import { useViewStore } from '@/stores/view';
import DrawerAiSection from './settings/DrawerAiSection.vue';
import DrawerDisplaySection from './settings/DrawerDisplaySection.vue';
import DrawerFiltersSection from './settings/DrawerFiltersSection.vue';
import DrawerNotificationsSection from './settings/DrawerNotificationsSection.vue';
import DrawerSyncSection from './settings/DrawerSyncSection.vue';

const view = useViewStore();
</script>

<template>
  <div v-if="view.drawerOpen" class="scrim" @click="view.closeDrawer()">
    <aside class="drawer" @click.stop>
      <header>
        <Mono :size="11">Filter settings</Mono>
        <button class="x" aria-label="Close" @click="view.closeDrawer()">✕</button>
      </header>

      <div class="body">
        <DrawerDisplaySection />
        <DrawerFiltersSection />
        <DrawerAiSection />
        <DrawerNotificationsSection />
        <DrawerSyncSection />
      </div>
    </aside>
  </div>
</template>

<style scoped>
.scrim {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.25);
  display: flex;
  justify-content: flex-end;
  z-index: 50;
}
.drawer {
  width: 320px;
  background: var(--panel);
  border-left: var(--hairline) solid var(--line);
  display: flex;
  flex-direction: column;
  animation: triageSlide 0.16s ease-out;
}
header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: var(--hairline) solid var(--line);
}
.x {
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 13px;
}
.body {
  padding: 8px 16px 24px;
  overflow-y: auto;
}
</style>

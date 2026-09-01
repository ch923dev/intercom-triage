<!-- Settings drawer. Right-side panel with display tweaks, board filters,
     AI settings, desktop notifications, and background sync. Each section
     is a focused child component under ./settings/. -->
<script setup lang="ts">
import Mono from './Mono.vue';
import { useSettingsStore } from '@/stores/settings';
import { useViewStore } from '@/stores/view';
import DrawerAiSection from './settings/DrawerAiSection.vue';
import DrawerCostSection from './settings/DrawerCostSection.vue';
import DrawerDisplaySection from './settings/DrawerDisplaySection.vue';
import DrawerFiltersSection from './settings/DrawerFiltersSection.vue';
import DrawerNotificationsSection from './settings/DrawerNotificationsSection.vue';
import DrawerSavedViewsSection from './settings/DrawerSavedViewsSection.vue';
import DrawerSyncSection from './settings/DrawerSyncSection.vue';

const view = useViewStore();
const settings = useSettingsStore();
</script>

<template>
  <div v-if="view.drawerOpen" class="scrim" @click="view.closeDrawer()">
    <aside class="drawer" @click.stop>
      <header>
        <Mono :size="11">Filter settings</Mono>
        <button class="x" aria-label="Close" @click="view.closeDrawer()">✕</button>
      </header>

      <div class="body">
        <!-- These settings are team-wide (invariant #18). If the row was never
             read, a toggle would PUT client defaults over everyone's filters,
             so `update()` refuses — say why rather than failing silently. -->
        <p v-if="!settings.loaded" class="load-error" role="status">
          Settings couldn't be loaded, so the values below are defaults, not yours. Changes are
          disabled until the backend answers — reload to retry.
        </p>
        <DrawerDisplaySection />
        <DrawerFiltersSection />
        <DrawerSavedViewsSection />
        <DrawerAiSection />
        <DrawerCostSection />
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
.load-error {
  margin: 0 0 4px;
  padding: 10px 12px;
  background: var(--accent-soft-2);
  border: var(--hairline) solid var(--accent);
  border-radius: var(--radius-card);
  color: var(--ink-2);
  font-size: 12px;
  line-height: 1.45;
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

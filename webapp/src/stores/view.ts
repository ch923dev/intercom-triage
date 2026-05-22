// App navigation state. Per tasks.md T035–T038.
// A lightweight in-memory router — this is a single-window local tool, so a
// reactive `view` ref beats pulling in vue-router. Tracks the active page and
// whether the settings drawer is open.

import { defineStore } from 'pinia';
import { ref } from 'vue';

export type View = 'board' | 'categories' | 'proposals';

export const useViewStore = defineStore('view', () => {
  const view = ref<View>('board');
  const drawerOpen = ref(false);

  function go(next: View) {
    view.value = next;
  }
  function openDrawer() {
    drawerOpen.value = true;
  }
  function closeDrawer() {
    drawerOpen.value = false;
  }
  function toggleDrawer() {
    drawerOpen.value = !drawerOpen.value;
  }

  return { view, drawerOpen, go, openDrawer, closeDrawer, toggleDrawer };
});

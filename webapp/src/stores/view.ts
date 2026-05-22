// App navigation state. Per tasks.md T035–T038, T052.
// A lightweight in-memory router — this is a single-window local tool, so a
// reactive `view` ref beats pulling in vue-router. Tracks the active page,
// whether the settings drawer is open, and the ticket open in the flyout.

import { defineStore } from 'pinia';
import { ref } from 'vue';

export type View = 'board' | 'categories' | 'proposals';

export const useViewStore = defineStore('view', () => {
  const view = ref<View>('board');
  const drawerOpen = ref(false);
  /** Ticket id open in the detail flyout, or null when closed. */
  const selectedTicketId = ref<string | null>(null);

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
  /** Open the flyout for a ticket — also jumps to the board so it's visible. */
  function selectTicket(id: string) {
    selectedTicketId.value = id;
    view.value = 'board';
  }
  function closeFlyout() {
    selectedTicketId.value = null;
  }

  return {
    view,
    drawerOpen,
    selectedTicketId,
    go,
    openDrawer,
    closeDrawer,
    toggleDrawer,
    selectTicket,
    closeFlyout,
  };
});

// App navigation state. Per tasks.md T035–T038, T052.
// A lightweight in-memory router — this is a single-window local tool, so a
// reactive `view` ref beats pulling in vue-router. Tracks the active page,
// whether the settings drawer is open, and the ticket open in the flyout.

import { defineStore } from 'pinia';
import { ref } from 'vue';

export type View =
  | 'board'
  | 'categories'
  | 'proposals'
  | 'followups'
  | 'playbooks'
  | 'snippets'
  | 'stats';

export const useViewStore = defineStore('view', () => {
  const view = ref<View>('board');
  const drawerOpen = ref(false);
  /** Ticket id open in the detail flyout, or null when closed. */
  const selectedTicketId = ref<string | null>(null);
  /** Keyboard-triage cursor (NFR-007). The card the j/k cursor sits on, kept
   *  distinct from `selectedTicketId` (flyout): navigating with j/k highlights
   *  a card without opening the modal, so the global key handler keeps firing.
   *  null = no cursor yet. */
  const focusedTicketId = ref<string | null>(null);

  function go(next: View) {
    view.value = next;
  }
  function openDrawer() {
    drawerOpen.value = true;
  }
  function closeDrawer() {
    drawerOpen.value = false;
  }
  /** Open the flyout for a ticket — also jumps to the board so it's visible. */
  function selectTicket(id: string) {
    selectedTicketId.value = id;
    view.value = 'board';
  }
  function closeFlyout() {
    selectedTicketId.value = null;
  }
  /** Move the keyboard-triage cursor (NFR-007). */
  function setFocus(id: string | null) {
    focusedTicketId.value = id;
  }

  return {
    view,
    drawerOpen,
    selectedTicketId,
    focusedTicketId,
    go,
    openDrawer,
    closeDrawer,
    selectTicket,
    closeFlyout,
    setFocus,
  };
});

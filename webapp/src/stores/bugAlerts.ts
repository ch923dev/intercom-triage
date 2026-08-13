// Bug-alert review store (US-045 · plan §21).
//
// Read + dismiss only. Alerts are produced by the backend ingest pipeline and
// consumed by the Slack delivery loop; this surface never creates one, and
// dismissal is the single mutation it performs.
//
// Loaded lazily by the page rather than in App.vue's bootstrap: the board does
// not need bug alerts to render, and bootstrap is already four round-trips.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { BugAlert } from '@/types/api';

export const useBugAlertsStore = defineStore('bugAlerts', () => {
  /** Worst severity first, then most recently detected. Server-ordered. */
  const alerts = ref<BugAlert[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  /** Ticket ids with a dismiss request in flight — disables the row's button. */
  const dismissing = ref<Set<string>>(new Set());

  /** Recorded and not yet dismissed: what still awaits an operator decision. */
  const pendingCount = computed(() => alerts.value.filter((a) => !a.dismissed_at).length);

  async function load(): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      alerts.value = await api.listBugAlerts();
    } catch (e) {
      error.value = (e as Error).message;
      throw e;
    } finally {
      loading.value = false;
    }
  }

  /**
   * Dismiss one alert and splice the server's row back in place.
   *
   * Deliberately not a refetch: the list would flicker, and a detection landing
   * between the dismiss and the reload would be silently clobbered by a stale
   * response. The endpoint returns the updated row, so one row is all we replace.
   */
  async function dismiss(ticketId: string): Promise<void> {
    dismissing.value = new Set(dismissing.value).add(ticketId);
    error.value = null;
    try {
      const updated = await api.dismissBugAlert(ticketId);
      alerts.value = alerts.value.map((a) => (a.ticket_id === ticketId ? updated : a));
    } catch (e) {
      // The row is left exactly as it was — a failed dismiss must not look like
      // a successful one.
      error.value = (e as Error).message;
      throw e;
    } finally {
      const next = new Set(dismissing.value);
      next.delete(ticketId);
      dismissing.value = next;
    }
  }

  return { alerts, loading, error, dismissing, pendingCount, load, dismiss };
});

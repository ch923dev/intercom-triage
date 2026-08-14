// Bug-alert review store (US-045 · plan §21; ack US-046 · plan §22).
//
// Read, acknowledge, dismiss. Alerts are produced by the backend ingest pipeline
// and consumed by the Slack delivery loop; this surface never creates one.
//
// Loaded lazily by the page rather than in App.vue's bootstrap: the board does
// not need bug alerts to render, and bootstrap is already four round-trips.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { BugAlert, SimilarBug } from '@/types/api';

export const useBugAlertsStore = defineStore('bugAlerts', () => {
  /** Worst severity first, then most recently detected. Server-ordered. */
  const alerts = ref<BugAlert[]>([]);
  const loading = ref(false);
  const error = ref<string | null>(null);
  /** Ticket ids with a dismiss request in flight — disables the row's button. */
  const dismissing = ref<Set<string>>(new Set());
  /** Ticket ids with an ack request in flight. Separate from `dismissing`: both
   *  buttons live on one row and only the clicked one should go quiet. */
  const acking = ref<Set<string>>(new Set());
  /** Ticket ids with a note save in flight. */
  const savingNote = ref<Set<string>>(new Set());
  /** `{ticket_id: matches}` — "seen before" results, cached per alert. An empty
   *  array is a loaded answer meaning "no precedent", NOT "not fetched yet". */
  const similar = ref<Record<string, SimilarBug[]>>({});
  /** Ticket ids acknowledged locally whose Slack message could NOT be updated.
   *  Surfaced on the row so the operator knows the channel is out of date —
   *  the ack itself succeeded, so this is a caveat, not an error. */
  const mirrorFailed = ref<Set<string>>(new Set());

  /** Recorded and not yet dismissed: what still awaits an operator decision.
   *  Acknowledged-but-open alerts still count — someone owns them, but they are
   *  not finished. */
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

  /**
   * Acknowledge one alert — "I own this" — and splice the server's row back in.
   *
   * Same single-row splice as `dismiss`, for the same reason. The response also
   * says whether the Slack message was updated; a false there is recorded in
   * `mirrorFailed` rather than thrown, because the acknowledgement itself
   * succeeded and treating it as an error would tell the operator to click
   * again — which the backend deliberately makes a no-op.
   */
  async function ack(ticketId: string): Promise<void> {
    acking.value = new Set(acking.value).add(ticketId);
    error.value = null;
    try {
      const { alert, slack_updated } = await api.ackBugAlert(ticketId);
      alerts.value = alerts.value.map((a) => (a.ticket_id === ticketId ? alert : a));
      const next = new Set(mirrorFailed.value);
      // Only flag when there WAS a message to update; a never-announced alert
      // reports false and has nothing to be out of date.
      if (!slack_updated && alert.slack_ts) next.add(ticketId);
      else next.delete(ticketId);
      mirrorFailed.value = next;
    } catch (e) {
      error.value = (e as Error).message;
      throw e;
    } finally {
      const next = new Set(acking.value);
      next.delete(ticketId);
      acking.value = next;
    }
  }

  /**
   * Write or clear the incident record. Same single-row splice as the others.
   *
   * A saved note can change what `similar` returns for OTHER alerts, so any
   * cached matches are dropped — recomputing on next open is cheaper than
   * reasoning about which cached entries a new note invalidated.
   */
  async function saveNote(ticketId: string, note: string): Promise<void> {
    savingNote.value = new Set(savingNote.value).add(ticketId);
    error.value = null;
    try {
      const updated = await api.setBugNote(ticketId, note);
      alerts.value = alerts.value.map((a) => (a.ticket_id === ticketId ? updated : a));
      similar.value = {};
    } catch (e) {
      error.value = (e as Error).message;
      throw e;
    } finally {
      const next = new Set(savingNote.value);
      next.delete(ticketId);
      savingNote.value = next;
    }
  }

  /**
   * Load "seen before" matches for one alert, if not already loaded.
   *
   * An empty array is a real answer (no precedent, or semantic matching is off),
   * so it is stored as such — without this the page would refetch forever on
   * every alert that has no match, which is most of them.
   */
  async function loadSimilar(ticketId: string): Promise<void> {
    if (ticketId in similar.value) return;
    try {
      const matches = await api.getSimilarBugs(ticketId);
      similar.value = { ...similar.value, [ticketId]: matches };
    } catch {
      // A failed lookup is not worth a page-level error: the alert itself is
      // intact and the hint is an enrichment. Cache the miss so it settles.
      similar.value = { ...similar.value, [ticketId]: [] };
    }
  }

  return {
    alerts,
    loading,
    error,
    dismissing,
    acking,
    savingNote,
    mirrorFailed,
    similar,
    pendingCount,
    load,
    dismiss,
    ack,
    saveNote,
    loadSimilar,
  };
});

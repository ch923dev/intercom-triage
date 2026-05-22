// Follow-up store + client-side alarm loop. Reference: tasks.md T050, T051;
// plan §8a. The backend is a passive store — due-ness is evaluated here on a
// once-per-second tick (App.vue drives `tick()`).

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { Followup } from '@/types/api';

/** A banner raised when a follow-up transitions pending → due. */
export interface AlarmBanner {
  ticketId: string;
  dueAt: string;
  reason: string | null;
}

/** A follow-up board column. */
export type Bucket = 'overdue' | 'within1h' | 'today' | 'later' | 'fired';

/** Board columns, left → right by urgency. */
export const BUCKET_ORDER: Bucket[] = ['overdue', 'within1h', 'today', 'later', 'fired'];

/** Column header label per bucket. */
export const BUCKET_LABEL: Record<Bucket, string> = {
  overdue: 'Overdue',
  within1h: 'Within 1h',
  today: 'Today',
  later: 'Later',
  fired: 'Fired',
};

/**
 * The board column a follow-up belongs to at instant `nowMs`. A fired
 * follow-up (alarm already rang) sits in `fired` until cleared or re-snoozed;
 * an un-fired one is bucketed by how soon its `due_at` falls. "Today" ends at
 * local 23:59:59.999.
 */
export function bucketOf(f: Followup, nowMs: number): Bucket {
  if (f.fired) return 'fired';
  const due = Date.parse(f.due_at);
  if (due <= nowMs) return 'overdue';
  if (due <= nowMs + 3_600_000) return 'within1h';
  const endOfDay = new Date(nowMs);
  endOfDay.setHours(23, 59, 59, 999);
  if (due <= endOfDay.getTime()) return 'today';
  return 'later';
}

export const useFollowupsStore = defineStore('followups', () => {
  /** ticket_id → follow-up record. */
  const map = ref<Record<string, Followup>>({});
  /** Active alarm banners, oldest first. */
  const banners = ref<AlarmBanner[]>([]);
  /** Epoch ms, refreshed every tick so chips + sorters stay reactive. */
  const now = ref(Date.now());

  const all = computed(() => Object.values(map.value));
  /** Pending count for the top-bar status pill. */
  const pendingCount = computed(() => all.value.length);
  /** True while at least one alarm banner is showing — pill goes accent-pulse. */
  const firing = computed(() => banners.value.length > 0);

  /** Follow-ups grouped into board columns, each column sorted by due_at
   *  ascending (most urgent first). Re-evaluates every tick via `now`. */
  const buckets = computed<Record<Bucket, Followup[]>>(() => {
    const grouped: Record<Bucket, Followup[]> = {
      overdue: [],
      within1h: [],
      today: [],
      later: [],
      fired: [],
    };
    for (const f of Object.values(map.value)) {
      grouped[bucketOf(f, now.value)].push(f);
    }
    for (const key of BUCKET_ORDER) {
      grouped[key].sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at));
    }
    return grouped;
  });

  function get(ticketId: string): Followup | undefined {
    return map.value[ticketId];
  }

  /** A follow-up is due once its `due_at` has passed. */
  function isDue(ticketId: string): boolean {
    const f = map.value[ticketId];
    return f !== undefined && Date.parse(f.due_at) <= now.value;
  }

  /** Load every active follow-up. Falls back to empty on a backend error. */
  async function load() {
    try {
      const rows = await api.listFollowups();
      map.value = Object.fromEntries(rows.map((r) => [r.ticket_id, r]));
    } catch {
      map.value = {};
    }
  }

  /** Upsert a follow-up. Optimistic — the card chip updates immediately. */
  async function setFollowup(ticketId: string, dueAt: Date, reason: string | null) {
    const previous = map.value[ticketId];
    const iso = dueAt.toISOString();
    const nowIso = new Date().toISOString();
    map.value = {
      ...map.value,
      [ticketId]: {
        ticket_id: ticketId,
        due_at: iso,
        reason,
        fired: false,
        created_at: previous?.created_at ?? nowIso,
        updated_at: nowIso,
      },
    };
    try {
      const saved = await api.setFollowup(ticketId, { due_at: iso, reason });
      map.value = { ...map.value, [ticketId]: saved };
    } catch (e) {
      rollback(ticketId, previous);
      throw e;
    }
  }

  /** Clear a follow-up. Optimistic — also drops any banner for the ticket. */
  async function clearFollowup(ticketId: string) {
    const previous = map.value[ticketId];
    removeFromMap(ticketId);
    dismissBanner(ticketId);
    try {
      await api.clearFollowup(ticketId);
    } catch (e) {
      rollback(ticketId, previous);
      throw e;
    }
  }

  /** Reschedule by `minutes` and clear `fired` (FR-022). Drops the banner. */
  async function snooze(ticketId: string, minutes: number) {
    dismissBanner(ticketId);
    const saved = await api.snoozeFollowup(ticketId, minutes);
    map.value = { ...map.value, [ticketId]: saved };
  }

  /** Flag the alarm as rung so reloads don't re-ring it (FR-021). */
  async function markFired(ticketId: string) {
    const f = map.value[ticketId];
    if (f === undefined) return;
    map.value = { ...map.value, [ticketId]: { ...f, fired: true } };
    try {
      await api.markFollowupFired(ticketId);
    } catch {
      // Non-fatal: the local `fired` flag still suppresses a re-ring this session.
    }
  }

  /** Drop a banner without touching the follow-up record (FR-022 dismiss). */
  function dismissBanner(ticketId: string) {
    banners.value = banners.value.filter((b) => b.ticketId !== ticketId);
  }

  /**
   * Once-per-second tick (T051). Advances `now`, then for every follow-up that
   * has just transitioned pending → due: raises a banner and marks it fired.
   * Returns the ticket ids that newly fired so the caller can play audio.
   */
  function tick(): string[] {
    now.value = Date.now();
    const newlyFired: string[] = [];
    for (const f of Object.values(map.value)) {
      if (f.fired) continue;
      if (Date.parse(f.due_at) > now.value) continue;
      banners.value = [
        ...banners.value,
        { ticketId: f.ticket_id, dueAt: f.due_at, reason: f.reason },
      ];
      newlyFired.push(f.ticket_id);
      void markFired(f.ticket_id);
    }
    return newlyFired;
  }

  function removeFromMap(ticketId: string) {
    const next = { ...map.value };
    delete next[ticketId];
    map.value = next;
  }

  function rollback(ticketId: string, previous: Followup | undefined) {
    if (previous === undefined) removeFromMap(ticketId);
    else map.value = { ...map.value, [ticketId]: previous };
  }

  return {
    map,
    banners,
    now,
    all,
    pendingCount,
    firing,
    buckets,
    get,
    isDue,
    load,
    setFollowup,
    clearFollowup,
    snooze,
    markFired,
    dismissBanner,
    tick,
  };
});

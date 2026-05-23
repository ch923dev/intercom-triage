// Follow-up store + client-side alarm loop. Reference: tasks.md T050, T051;
// plan §8a. The backend is a passive store — due-ness is evaluated here on a
// once-per-second tick (App.vue drives `tick()`).

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api } from '@/api/client';
import type { BulkResult, Followup } from '@/types/api';

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

/**
 * Compute the due_at for a card dropped into `bucket`. Returns `null` for
 * `fired` — that path uses `markFired` instead of `setFollowup`.
 *
 * `today` is capped at end-of-day local; `later` is tomorrow 09:00 local.
 * Pure — `nowMs` is passed in so the caller controls the clock (and tests
 * can pin it).
 */
export function dueAtForBucket(bucket: Bucket, nowMs: number): Date | null {
  if (bucket === 'fired') return null;
  if (bucket === 'overdue') return new Date(nowMs);
  if (bucket === 'within1h') return new Date(nowMs + 30 * 60_000);
  if (bucket === 'today') {
    const endOfDay = new Date(nowMs);
    endOfDay.setHours(23, 59, 59, 999);
    const fourHours = nowMs + 4 * 3_600_000;
    return new Date(Math.min(fourHours, endOfDay.getTime()));
  }
  // 'later' → tomorrow 09:00 local.
  const tomorrow = new Date(nowMs);
  tomorrow.setDate(tomorrow.getDate() + 1);
  tomorrow.setHours(9, 0, 0, 0);
  return tomorrow;
}

export const useFollowupsStore = defineStore('followups', () => {
  /** ticket_id → follow-up record. */
  const map = ref<Record<string, Followup>>({});
  /** Active alarm banners, oldest first. */
  const banners = ref<AlarmBanner[]>([]);
  /** Epoch ms, refreshed every tick so chips + sorters stay reactive. */
  const now = ref(Date.now());

  /** Pending count for the top-bar status pill. */
  const pendingCount = computed(() => Object.keys(map.value).length);
  /** True while at least one alarm banner is showing — pill goes accent-pulse. */
  const firing = computed(() => banners.value.length > 0);

  /** Follow-ups pre-sorted by due_at. Recomputed only when map changes, not
   *  on every tick — due_at is immutable between ticks (snooze mutates map). */
  const _sortedByDueAt = computed(() =>
    Object.values(map.value).sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at)),
  );

  /** Follow-ups grouped into board columns, each column already in due_at
   *  ascending order (most urgent first). Reuses the pre-sorted list so no
   *  per-column sort is needed on each tick. */
  const buckets = computed<Record<Bucket, Followup[]>>(() => {
    const grouped: Record<Bucket, Followup[]> = {
      overdue: [],
      within1h: [],
      today: [],
      later: [],
      fired: [],
    };
    for (const f of _sortedByDueAt.value) {
      grouped[bucketOf(f, now.value)].push(f);
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

  /** Move a card to a new bucket via drag-and-drop.
   *  - Same bucket → no-op.
   *  - `fired` → call markFired (no due_at change).
   *  - Others → setFollowup(ticketId, dueAtForBucket(bucket, Date.now())!, currentReason).
   *  Optimistic: setFollowup/markFired already do their own optimistic updates,
   *  but we early-out before calling them when bucket is unchanged.
   */
  async function rescheduleToBucket(ticketId: string, bucket: Bucket): Promise<void> {
    const f = map.value[ticketId];
    if (f === undefined) return;
    if (bucketOf(f, now.value) === bucket) return;
    if (bucket === 'fired') {
      await markFired(ticketId);
      return;
    }
    const dueAt = dueAtForBucket(bucket, Date.now());
    if (dueAt === null) return;
    const reason = map.value[ticketId]?.reason ?? null;
    await setFollowup(ticketId, dueAt, reason);
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

  /** Apply the same follow-up to N tickets. Optimistic; rolls back per-id
   *  failures from the server response. */
  async function bulkSet(
    ticketIds: string[],
    dueAt: Date,
    reason: string | null,
  ): Promise<BulkResult> {
    const iso = dueAt.toISOString();
    const nowIso = new Date().toISOString();
    const snapshot: Record<string, Followup | undefined> = {};
    const next = { ...map.value };
    for (const id of ticketIds) {
      snapshot[id] = map.value[id];
      next[id] = {
        ticket_id: id,
        due_at: iso,
        reason,
        fired: false,
        created_at: map.value[id]?.created_at ?? nowIso,
        updated_at: nowIso,
      };
    }
    map.value = next;
    try {
      const result = await api.bulkSetFollowup(ticketIds, { due_at: iso, reason });
      // Roll back per-id failures.
      if (result.failed.length > 0) {
        const reverted = { ...map.value };
        for (const { id } of result.failed) {
          const prev = snapshot[id];
          if (prev === undefined) delete reverted[id];
          else reverted[id] = prev;
        }
        map.value = reverted;
      }
      return result;
    } catch (e) {
      // Whole-batch failure — restore every snapshot.
      const reverted = { ...map.value };
      for (const id of ticketIds) {
        const prev = snapshot[id];
        if (prev === undefined) delete reverted[id];
        else reverted[id] = prev;
      }
      map.value = reverted;
      throw e;
    }
  }

  /** Clear N follow-ups. Idempotent — ids without a row report ok server-side. */
  async function bulkClear(ticketIds: string[]): Promise<BulkResult> {
    const snapshot: Record<string, Followup | undefined> = {};
    const next = { ...map.value };
    for (const id of ticketIds) {
      snapshot[id] = map.value[id];
      delete next[id];
      banners.value = banners.value.filter((b) => b.ticketId !== id);
    }
    map.value = next;
    try {
      const result = await api.bulkClearFollowup(ticketIds);
      if (result.failed.length > 0) {
        const reverted = { ...map.value };
        for (const { id } of result.failed) {
          const prev = snapshot[id];
          if (prev !== undefined) reverted[id] = prev;
        }
        map.value = reverted;
      }
      return result;
    } catch (e) {
      const reverted = { ...map.value };
      for (const id of ticketIds) {
        const prev = snapshot[id];
        if (prev !== undefined) reverted[id] = prev;
      }
      map.value = reverted;
      throw e;
    }
  }

  return {
    banners,
    now,
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
    rescheduleToBucket,
    tick,
    // Bulk (Phase 12)
    bulkSet,
    bulkClear,
  };
});

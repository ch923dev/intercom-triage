// Selection store — transient multi-select set used by Phase 12 bulk actions.
//
// Plan §8d. The set is intentionally short-lived: it is cleared on view
// change, on Escape, on an empty-background click, and after every successful
// bulk action. No persistence (server or local) — multi-select state belongs
// to the in-progress operator gesture, not to the document.
//
// Range-select scopes to a single column: `addRange` requires the from/to
// anchors to share the column id stored in `lastAnchor`. Cross-column shift
// clicks are downgraded to plain toggles by the caller — this store does not
// silently expand a range across columns.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';

export interface SelectionAnchor {
  columnId: string;
  id: string;
}

export const useSelectionStore = defineStore('selection', () => {
  const selected = ref<Set<string>>(new Set());
  const lastAnchor = ref<SelectionAnchor | null>(null);

  const count = computed(() => selected.value.size);
  const isEmpty = computed(() => selected.value.size === 0);

  function has(id: string): boolean {
    return selected.value.has(id);
  }

  function asArray(): string[] {
    return Array.from(selected.value);
  }

  /** Toggle a single id. Updates `lastAnchor` to the clicked id (the next
   *  shift-click extends from here). */
  function toggle(id: string, columnId: string): void {
    const next = new Set(selected.value);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selected.value = next;
    lastAnchor.value = { columnId, id };
  }

  /** Extend the selection across a contiguous slice of ids in display order.
   *  Requires `lastAnchor` to be in the same column — otherwise the caller
   *  should fall back to `toggle`. `orderedIds` is the column's currently-
   *  displayed sort order (the source of truth for "contiguous").
   *
   *  If `orderedIds` doesn't contain both `fromId` and `toId`, this is a
   *  no-op rather than throwing — keeps the UI robust against a race where
   *  the column re-sorts between the anchor click and the shift click. */
  function addRange(columnId: string, fromId: string, toId: string, orderedIds: string[]): void {
    const fromIdx = orderedIds.indexOf(fromId);
    const toIdx = orderedIds.indexOf(toId);
    if (fromIdx === -1 || toIdx === -1) return;
    const [lo, hi] = fromIdx <= toIdx ? [fromIdx, toIdx] : [toIdx, fromIdx];
    const next = new Set(selected.value);
    for (let i = lo; i <= hi; i++) {
      const id = orderedIds[i];
      if (id !== undefined) next.add(id);
    }
    selected.value = next;
    lastAnchor.value = { columnId, id: toId };
  }

  /** Add every id in a column to the selection. The anchor moves to the
   *  last id in the array (so a follow-up shift-click extends from there). */
  function addAll(ids: string[], columnId: string): void {
    if (ids.length === 0) return;
    const next = new Set(selected.value);
    for (const id of ids) next.add(id);
    selected.value = next;
    const last = ids[ids.length - 1];
    if (last !== undefined) lastAnchor.value = { columnId, id: last };
  }

  /** Remove an id from the selection without touching `lastAnchor`. */
  function remove(id: string): void {
    if (!selected.value.has(id)) return;
    const next = new Set(selected.value);
    next.delete(id);
    selected.value = next;
  }

  /** Empty the selection and forget the anchor. */
  function clear(): void {
    if (selected.value.size === 0 && lastAnchor.value === null) return;
    selected.value = new Set();
    lastAnchor.value = null;
  }

  return {
    selected,
    lastAnchor,
    count,
    isEmpty,
    has,
    asArray,
    toggle,
    addRange,
    addAll,
    remove,
    clear,
  };
});

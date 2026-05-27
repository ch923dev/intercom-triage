// Keyboard-driven triage (NFR-007). A single composable that turns bare
// keystrokes into board navigation + triage actions so the operator never
// needs the mouse. Wired into the one global keydown listener in App.vue —
// this file owns *what each key does*, App.vue owns *when keys are eligible*
// (form-control / modal guards).
//
// Key scheme (documented for the operator footer + spec):
//   j / k      move the focus cursor to the next / previous ticket, in board
//              reading order (column by column left→right, top→bottom within a
//              column, then the Resolved column, then Non-actionable).
//   e          resolve the focused ticket (reuses tickets.markResolved — the
//              same action the card's ✓ button calls).
//   1..9       recategorize the focused ticket into the Nth *active category*
//              column in board (sort_order) order — 1 = leftmost category.
//              Pending-proposal columns are intentionally excluded: you can
//              override into a real category, not a proposal. Out-of-range
//              digits are a no-op. Reuses tickets.applyOverride.
//
// The dispatch logic is deliberately split into a pure `dispatchTriageKey`
// function (key + context → action descriptor) so it can be unit-tested with
// no DOM/store mounting. `useKeyboardTriage` is the thin reactive shell that
// builds the context from the stores and runs the resulting action.

import { computed } from 'vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';

/** An action the dispatcher resolved a key into. `none` means the key was not
 *  a triage key (or had nothing to act on) and the caller should not
 *  preventDefault. */
export type TriageAction =
  | { type: 'none' }
  | { type: 'navigate'; id: string }
  | { type: 'resolve'; id: string }
  | { type: 'recategorize'; id: string; categoryId: number };

/** The minimal, serialisable snapshot the dispatcher needs. Built fresh on
 *  every keystroke from the reactive stores in `useKeyboardTriage`. */
export interface TriageContext {
  /** Ticket ids in board reading order (the navigation ring). */
  orderedIds: string[];
  /** Currently focused ticket id, or null when the cursor is unset. */
  focusedId: string | null;
  /** Active category ids in board (sort_order) display order — index 0 is the
   *  category mapped to the `1` key. Excludes pending proposals. */
  categoryIds: number[];
}

/** Pure key → action mapping. No side effects; safe to unit-test. */
export function dispatchTriageKey(key: string, ctx: TriageContext): TriageAction {
  const { orderedIds, focusedId, categoryIds } = ctx;

  if (key === 'j' || key === 'k') {
    if (orderedIds.length === 0) return { type: 'none' };
    const cur = focusedId === null ? -1 : orderedIds.indexOf(focusedId);
    let next: number;
    if (key === 'j') {
      // First press (or focus fell off the board) lands on the first card;
      // otherwise step forward and clamp at the last card.
      next = cur < 0 ? 0 : Math.min(cur + 1, orderedIds.length - 1);
    } else {
      next = cur < 0 ? 0 : Math.max(cur - 1, 0);
    }
    const id = orderedIds[next];
    if (id === undefined) return { type: 'none' };
    return { type: 'navigate', id };
  }

  if (key === 'e') {
    if (focusedId === null || !orderedIds.includes(focusedId)) return { type: 'none' };
    return { type: 'resolve', id: focusedId };
  }

  // Digit keys 1..9 → Nth active category.
  if (key >= '1' && key <= '9') {
    if (focusedId === null || !orderedIds.includes(focusedId)) return { type: 'none' };
    const idx = Number(key) - 1;
    const categoryId = categoryIds[idx];
    if (categoryId === undefined) return { type: 'none' };
    return { type: 'recategorize', id: focusedId, categoryId };
  }

  return { type: 'none' };
}

export function useKeyboardTriage() {
  const tickets = useTicketsStore();
  const categories = useCategoriesStore();
  const followups = useFollowupsStore();
  const settings = useSettingsStore();
  const view = useViewStore();

  /** Active category ids in board column order (the digit-key map source). */
  const categoryIds = computed(() => categories.categories.map((c) => c.id));

  /** Ticket ids in board reading order. Mirrors what Board.vue renders:
   *  category/proposal columns (respecting hide-empty), each column's tickets
   *  with due follow-ups pinned to the top, then Resolved, then Non-actionable.
   *  Built here (not imported from Board.vue) to keep the cursor independent of
   *  the component tree and unit-testable. */
  const orderedIds = computed(() => {
    const ids: string[] = [];
    const sortDueFirst = (list: { id: string }[]) =>
      [...list].sort((a, b) => Number(followups.isDue(b.id)) - Number(followups.isDue(a.id)));

    for (const col of categories.columns) {
      const list =
        col.kind === 'category'
          ? (tickets.byCategory.get(col.id) ?? [])
          : (tickets.byProposal.get(col.id) ?? []);
      if (settings.hideEmptyCategories && col.kind === 'category' && list.length === 0) continue;
      for (const t of sortDueFirst(list)) ids.push(t.id);
    }
    for (const t of tickets.pureResolvedTickets) ids.push(t.id);
    for (const t of tickets.nonActionableTickets) ids.push(t.id);
    return ids;
  });

  /** Run the action a key resolves to. Returns true if it handled the key
   *  (caller should preventDefault), false otherwise. */
  function runTriageKey(key: string): boolean {
    const action = dispatchTriageKey(key, {
      orderedIds: orderedIds.value,
      focusedId: view.focusedTicketId,
      categoryIds: categoryIds.value,
    });
    switch (action.type) {
      case 'navigate':
        view.setFocus(action.id);
        return true;
      case 'resolve':
        void tickets.markResolved(action.id);
        // The resolved card leaves the open list; move the cursor to whatever
        // now occupies its slot so the operator keeps flowing.
        advanceAfterRemoval(action.id);
        return true;
      case 'recategorize':
        void tickets.applyOverride(action.id, action.categoryId);
        return true;
      case 'none':
      default:
        return false;
    }
  }

  /** After a card leaves the board (resolve), nudge the cursor to a sane
   *  neighbour. Recompute happens on the next tick once the store mutates;
   *  here we just remember the prior index and clamp. */
  function advanceAfterRemoval(removedId: string) {
    const before = orderedIds.value;
    const idx = before.indexOf(removedId);
    if (idx === -1) {
      view.setFocus(null);
      return;
    }
    // Prefer the next card, else the previous, else clear.
    const next = before[idx + 1] ?? before[idx - 1] ?? null;
    view.setFocus(next === removedId ? null : next);
  }

  return { orderedIds, categoryIds, runTriageKey };
}

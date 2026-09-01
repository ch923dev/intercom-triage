// Terminal-lane drop predicate. Reference: tasks.md T199, invariant #10.

import { describe, expect, it } from 'vitest';
import { TERMINAL_LANE, acceptsDropFromOpenLane } from './dragLanes';

/** Minimal stand-in for Sortable's `from` argument (only `el` is read). */
function sourceList(lane?: string): { el: HTMLElement } {
  const el = document.createElement('div');
  if (lane !== undefined) el.dataset.lane = lane;
  return { el };
}

describe('acceptsDropFromOpenLane', () => {
  it('accepts a drop from an unmarked (open category) column', () => {
    expect(acceptsDropFromOpenLane(null, sourceList())).toBe(true);
  });

  it('refuses a drop originating in a terminal lane', () => {
    // Resolved → Non-actionable (and the reverse). The endpoints 409 on an
    // already-resolved row, and the store's handlers walk the open list only,
    // so accepting this moved the DOM node and changed nothing.
    expect(acceptsDropFromOpenLane(null, sourceList(TERMINAL_LANE))).toBe(false);
  });

  it('accepts a drop from a lane marked with some other value', () => {
    // Only the terminal marker is special — a future `data-lane` on category
    // columns must not start silently refusing drag-in.
    expect(acceptsDropFromOpenLane(null, sourceList('category'))).toBe(true);
  });
});

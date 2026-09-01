// Terminal-lane drag rules. Reference: tasks.md T199, invariant #10.
//
// Resolved and Non-actionable are two *views* of one storage state
// (`resolved_source`), not a legal transition pair. Both columns joined the
// drag group with `put: true`, so Sortable accepted a card dragged from one
// into the other — but `markResolved` / `markNonActionable` search only the
// OPEN list, so they returned immediately: no API call, no state change, and
// therefore no reactive dependency changed, so Vue never re-rendered and never
// restored the node Sortable had already physically moved. The card sat under
// the wrong heading, both counts were wrong, and the board lied until the next
// refresh replaced the arrays.
//
// The move is unexecutable anyway — `resolution.apply_resolve` and
// `apply_mark_non_actionable` both 409 on an already-resolved row — so the
// honest fix is to refuse the drop. The drop predicate is the only place that
// can stop the DOM move; a guard in the store runs after Sortable has committed.
//
// Category columns are deliberately NOT marked: they must keep accepting drops
// from both terminal lanes, which is drag-out reopen.

/** `data-lane` value marking a list whose cards are already resolved. */
export const TERMINAL_LANE = 'terminal';

/**
 * vuedraggable `group.put` predicate — reject drops originating in a terminal
 * lane. `from.el` is the source list element, so this reads the marker off the
 * DOM rather than threading column identity through props.
 */
export function acceptsDropFromOpenLane(_to: unknown, from: { el: HTMLElement }): boolean {
  return from.el?.dataset?.lane !== TERMINAL_LANE;
}

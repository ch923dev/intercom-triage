# Phase 12 — Bulk actions

Back to [tasks.md](../../tasks.md).

### T074 ✓ — Pydantic bulk schemas
**Depends on:** T055
**Implements:** FR-033, FR-036, plan §8d
**Description:** Add `BulkTicketIds`, `BulkCategoryUpdate`, `BulkFollowupSet`, and `BulkResult` to `backend/app/schemas.py`. All envelopes enforce `min_length=1, max_length=MAX_BULK_IDS` on `ticket_ids` via `Field`. Add `MAX_BULK_IDS` (default 200) to `config.py`. Treat duplicate ids in the request as a single id (deduplicate server-side before processing).
**Acceptance:**
- [ ] `BulkTicketIds` rejects an empty array (422).
- [ ] `BulkTicketIds` rejects > 200 ids (422).
- [ ] `BulkResult` accepts mixed `ok_ids` + `failed[]` with `{id, reason}`.
- [ ] `BulkCategoryUpdate` requires `category_id` and validates the same id bounds.

### T075 ✓ — Bulk resolve + reopen endpoints
**Depends on:** T074, T060
**Implements:** FR-033, US-018, US-015
**Description:** Add `POST /tickets/bulk/resolve` and `POST /tickets/bulk/reopen` to `backend/app/routers/tickets.py`. Each loops the existing `resolution_svc.resolve` / `reopen` per id inside one session; `HTTPException` per id → `{id, reason}` in `failed[]`. Single commit at end. Add a small helper `bulk_loop(ticket_ids, per_id)` in `services/resolution.py` (or a new `services/bulk.py`) to centralize the loop pattern.
**Acceptance:**
- [ ] Bulk resolve with 3 valid ids → `ok_ids` length 3, `failed` empty.
- [ ] Bulk resolve where 1 id is already resolved → 2 in `ok_ids`, 1 in `failed`.
- [ ] Bulk reopen on an open ticket records 409 in `failed[]` and does not abort the rest.
- [ ] Duplicate ids in the request are processed once.

### T076 ✓ — Bulk recategorize endpoint
**Depends on:** T074, T026
**Implements:** FR-033, US-018, FR-009
**Description:** Add `PATCH /tickets/bulk/category` that loops `services.tickets.set_override` per id with the same `category_id`. A resolved ticket in the batch follows existing `set_override` behavior (clears resolution). Reuse the bulk loop helper from T075.
**Acceptance:**
- [ ] Bulk recategorize 5 ids → all rows show `user_override=true` and the new category id.
- [ ] Unknown ticket id in the batch records 404 in `failed[]`, the others succeed.
- [ ] Unknown `category_id` returns 422 before any DB work.

### T077 ✓ — Bulk dismiss-chip endpoint
**Depends on:** T074, T060
**Implements:** FR-033, US-018, FR-027
**Description:** Add `POST /tickets/bulk/dismiss-chip` looping `resolution_svc.dismiss_chip` per id.
**Acceptance:**
- [ ] Bulk dismiss across 3 ids stamps each row's `resolution_chip_dismissed_at` = its `updated_at`.
- [ ] Unknown id records 404 in `failed[]`.

### T078 ✓ — Bulk follow-up set + clear endpoints
**Depends on:** T074, T046
**Implements:** FR-033, US-018, FR-019, FR-022
**Description:** Add `PUT /followups/bulk` (sets the same `due_at` + `reason` on every id) and `DELETE /followups/bulk` (clears for every id). Reuse the bulk loop helper.
**Acceptance:**
- [ ] Bulk set with 4 ids inserts/updates 4 rows with identical `due_at`.
- [ ] Bulk clear is idempotent: ids without a follow-up record `{id, reason: "no follow-up"}` in `failed[]` but the rest succeed. (Optional: treat as ok — confirm in PR.)
- [ ] Reason longer than 80 chars fails validation up-front (422).

### T079 ✓ — Backend tests for T075–T078
**Depends on:** T075, T076, T077, T078
**Implements:** plan §8d
**Description:** Add `tests/test_bulk_api.py` covering each endpoint's happy path, partial failure, cap-exceeded (422), empty array (422), unknown id (`failed[]`), and the `MAX_BULK_IDS` config knob. Plus `/metrics` counter assertions once T084 lands.
**Acceptance:**
- [ ] `pytest` passes with the new file.
- [ ] Coverage on `services/bulk.py` ≥ 90 %.

### T080 ✓ — Vitest harness + selection store
**Depends on:** T029
**Implements:** plan §8d
**Description:** Add Vitest + Vue Test Utils + happy-dom to `webapp/`. Wire `npm run test`. Implement `webapp/src/stores/selection.ts` exposing `selected: Set<string>`, `lastAnchor: {columnId, id} | null`, getters `count`, `has(id)`, `asArray()`, actions `toggle(id, columnId)`, `addRange(columnId, fromId, toId, orderedIds)`, `addAll(ids, columnId)`, `clear()`. Range-select scopes to the same column; cross-column shift+click downgrades to `toggle()`. Write the selection store unit tests first (TDD).
**Acceptance:**
- [ ] `npm run test` runs and Vitest reports green.
- [ ] Toggle adds/removes an id.
- [ ] `addRange` selects the contiguous slice between two anchors in sort order.
- [ ] Cross-column shift behaves as a toggle.
- [ ] `clear()` empties the set and resets `lastAnchor`.

### T081 ✓ — Card + column selection wiring
**Depends on:** T080
**Implements:** US-018, FR-032, FR-034
**Description:** Update `TicketCard.vue` and `Column.vue`:
- Cmd/Ctrl+click → `selection.toggle(id, columnId)`; suppress the flyout open.
- Shift+click → `selection.addRange(columnId, lastAnchor.id, id, columnOrderedIds)` when last anchor is in the same column; else `toggle`.
- Selected cards render `data-selected="true"` with the accent ring per design tokens.
- Column header gains a `Select all (N)` mono chip when the header is hovered OR `selection.count > 0` for that column; click → `selection.addAll(columnTicketIds, columnId)`.
- App-level `Escape` and empty-background click clear the selection (extend the existing keydown handler in `App.vue`).
**Acceptance:**
- [ ] Cmd-clicking three cards toggles them on; clicking again toggles them off.
- [ ] Shift+click selects the contiguous in-column range.
- [ ] Escape clears the selection.
- [ ] Plain click on a card still opens the flyout (no regression).

### T082 ✓ — `BulkActionBar` + tickets-store bulk actions
**Depends on:** T075, T076, T077, T078, T081
**Implements:** US-018, FR-033
**Description:** Add `webapp/src/components/BulkActionBar.vue`, sticky bottom-center, slides in when `selection.count > 0`. Buttons: Resolve, Reopen, Move to ▾ (reuse the category picker chip row from the flyout), Follow-up ▾ (reuse preset chips), Clear F/U, Dismiss chip. Disabled states per spec. Add tickets-store actions: `bulkResolve`, `bulkReopen`, `bulkRecategorize`, `bulkSetFollowup`, `bulkClearFollowup`, `bulkDismissChip` — each snapshots affected rows, mutates locally, calls the matching endpoint, and rolls back per id reported in `failed[]`. Surface a single summary toast per action. Clear `selection` on success.
**Acceptance:**
- [ ] Bar appears when ≥ 1 card selected and disappears when count drops to 0.
- [ ] Resolve button optimistically moves selected cards into the Resolved column; on a mocked `failed[]` entry the affected card snaps back.
- [ ] Reopen button is disabled unless every selected card is resolved.
- [ ] Move-to disables when no category is reachable (e.g. selection spans only the fallback).
- [ ] Summary toast counts ok + failed correctly.

### T083 ✓ — Bulk drag through Board + ResolvedColumn
**Depends on:** T082
**Implements:** US-018, FR-035
**Description:** Switch `vuedraggable` to multi-drag mode and gate the multi-payload on `selection.has(draggedId)`. When dragging a selected card:
- Drop into a category column → call `tickets.bulkRecategorize(selection.asArray(), targetCategoryId)`.
- Drop into the Resolved column → call `tickets.bulkResolve(selection.asArray())`.
- Drop a resolved selection into a category column → call `bulkRecategorize` (which clears resolution server-side).
- Drag of a non-selected card behaves exactly as today.
**Acceptance:**
- [ ] Selecting 3 cards and dragging one moves all 3 to the dropped column.
- [ ] Dragging a non-selected card behaves identically to the pre-T083 single-item override.
- [ ] Dropping a 50-card selection into Resolved produces a single network call.

### T084 ✓ — `/metrics` bulk counters + docs refresh
**Depends on:** T082, T083, T079
**Implements:** plan §11, plan §8d
**Description:** Add `bulk_actions_total{op, result}` and `bulk_action_ids_total{op}` to `app/metrics.py`; wire incr calls from each bulk service path (`ok` when `failed[]` empty, `partial` when both, `fail` when all failed). Update README's API surface table, add a "Bulk actions" subsection, and bump `spec.md` / `plan.md` / `tasks.md` version headers to v1.5 if not already done in this phase.
**Acceptance:**
- [ ] `GET /metrics` returns the new counters and they increment under tests.
- [ ] README shows the six bulk endpoints.
- [ ] Version headers in all three docs read v1.5.
- [ ] `pytest` + `npm run test` + `npm run typecheck` + `npm run build` all green.

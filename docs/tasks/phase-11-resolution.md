# Phase 11 — Ticket resolution

Back to [tasks.md](../../tasks.md).

### T054 ✓ — Alembic migration + SQLAlchemy model additions
**Depends on:** T006, T045
**Implements:** FR-025, FR-027, FR-029, FR-030, plan §8c
**Description:** Alembic migration `0006_add_ticket_resolution.py` adds `resolved_at`, `resolved_source`, `ai_resolve_enabled`, `resolution_chip_dismissed_at` to `tickets`; `ai_resolution_verdict`, `ai_resolution_confidence`, `ai_resolution_reason` to `ai_cache`; `ai_resolve_default`, `ai_resolve_confidence_threshold` to `settings`. SQLAlchemy models updated with the new mapped columns and check constraints.
**Acceptance:**
- [ ] Fresh DB has all new columns with correct defaults.
- [ ] Check constraint rejects `resolved_at` non-null with `resolved_source` null (and vice versa).
- [ ] Existing DB upgraded via migration retains prior data.

### T055 ✓ — Pydantic schemas: resolution fields + new request bodies
**Depends on:** T054
**Implements:** FR-025, FR-026, FR-027, FR-028, FR-029, FR-030
**Description:** Add `ResolvedSource`, `ResolutionVerdict`, `ResolutionChipState` literals. Extend `TicketSchema` with seven resolution fields. Add `AIResolveSet`, `ResolveResponse`, `ReopenResponse`. Extend `FilterSettings` with `ai_resolve_default` + `ai_resolve_confidence_threshold`.
**Acceptance:**
- [ ] `TicketSchema` validates with all resolution fields present or absent.
- [ ] `AIResolveSet` accepts `true`, `false`, and `null`.
- [ ] `FilterSettings` rejects `ai_resolve_confidence_threshold` outside `[0, 1]`.

### T056 ✓ — AI prompt + parser carry resolution verdict
**Depends on:** T013, T055
**Implements:** FR-027, plan §7
**Description:** Extend `SYSTEM_PROMPT` with RESOLUTION rules and add the three resolution fields to all three JSON response shapes (existing, pending_proposal, new_proposal). Extend `ParsedAssignment` and `parse_response` to extract, validate, and clamp `resolution_verdict`, `resolution_confidence`, `resolution_reason`.
**Acceptance:**
- [ ] System prompt contains all three resolution field names.
- [ ] Parser correctly extracts verdict + confidence + reason from a complete response.
- [ ] Missing resolution fields parse to `None` without error.
- [ ] Invalid verdict (e.g. `"maybe"`) clamps to `None`.
- [ ] Reason longer than 120 chars is truncated to 120.

### T057 ✓ — `CategorizationResult` + resolver carry resolution
**Depends on:** T056
**Implements:** FR-027, plan §7
**Description:** Add three resolution fields to `CategorizationResult`. Thread them from `ParsedAssignment` through every branch of `resolve()`. `_fallback()` leaves them `None` by default.
**Acceptance:**
- [ ] `resolve()` propagates all three fields from `ParsedAssignment` to `CategorizationResult`.
- [ ] Fallback path returns `None` for all three resolution fields.

### T058 ✓ — AI cache reads/writes resolution fields
**Depends on:** T054, T057
**Implements:** FR-027, FR-008
**Description:** Update `set_cached` to persist the three resolution fields; update `get_cached` to return them. Legacy rows with null fields round-trip without crashing.
**Acceptance:**
- [ ] Cache write + read preserves verdict, confidence, and reason.
- [ ] A row inserted without resolution fields returns `None` for all three on read.

### T059 ✓ — `_upsert_ticket` auto-resolves on Intercom open→closed transition
**Depends on:** T054, T057
**Implements:** FR-026, US-017
**Description:** Modify `_upsert_ticket` in `services/tickets.py` so that when a stored ticket with `resolved_at IS NULL` arrives with `state='closed'`, it stamps `resolved_at = now()` and `resolved_source = 'intercom_closed'`. Second and subsequent closed-state syncs do not re-stamp `resolved_at`.
**Acceptance:**
- [ ] First sync open → second sync closed stamps `resolved_at` + `resolved_source`.
- [ ] Already-resolved ticket's `resolved_at` is unchanged on a subsequent closed sync.
- [ ] No AI call is triggered by the closure event.

### T060 ✓ — `services/resolution.py` — manual resolve / reopen / AI toggle / dismiss
**Depends on:** T054
**Implements:** FR-025, FR-026, FR-028, FR-029
**Description:** Create `backend/app/services/resolution.py` with four async functions: `resolve` (stamps `resolved_at + source='manual'`, 409 if already resolved), `reopen` (clears both fields, 409 if not resolved), `set_ai_resolve` (writes nullable tri-state), `dismiss_chip` (sets `resolution_chip_dismissed_at = row.updated_at`). All raise 404 for unknown ticket ids.
**Acceptance:**
- [ ] `resolve` sets correct fields; 409 on double-resolve.
- [ ] `reopen` clears fields; 409 on open ticket.
- [ ] `set_ai_resolve` persists `True`, `False`, and `None`.
- [ ] `dismiss_chip` stamps `resolution_chip_dismissed_at` equal to `updated_at`.
- [ ] All four raise 404 for unknown ticket ids.

### T061 ✓ — Resolution endpoints + router wiring
**Depends on:** T055, T060
**Implements:** FR-028, US-015, US-016
**Description:** Add four routes to `backend/app/routers/tickets.py`: `POST /{id}/resolve`, `POST /{id}/reopen`, `PATCH /{id}/ai-resolve`, `POST /{id}/dismiss-chip`. Wire to `resolution_svc`.
**Acceptance:**
- [ ] `POST /tickets/t1/resolve` returns 200 with `resolved_source='manual'`.
- [ ] 404 for unknown id on all four routes.
- [ ] 409 on double-resolve and on reopening an open ticket.

### T062 ✓ — `GET /tickets` resolved filter + chip-state computation + drag-out reopen
**Depends on:** T055, T058, T060, T061
**Implements:** FR-025, FR-027, FR-028, US-015, US-016
**Description:** Extend `services/tickets.get_tickets` with a `resolved` parameter (`False` = exclude resolved [default], `True` = only resolved, `None` = both). Compute `resolution_chip_state` server-side using the `_chip_state` helper per §8c. Extend `set_override` to atomically clear resolution when dragging a resolved ticket into a category column.
**Acceptance:**
- [ ] Default `GET /tickets` excludes resolved tickets.
- [ ] `GET /tickets?resolved=true` returns only resolved tickets, sorted by `resolved_at` desc.
- [ ] Chip state is `ai_resolved` when verdict='resolved', confidence ≥ threshold, ticket is open, and chip not dismissed.
- [ ] `PATCH /tickets/{id}/category` on a resolved ticket clears `resolved_at` + `resolved_source`.

### T063 ✓ — Settings endpoint carries `ai_resolve_default` + threshold
**Depends on:** T055, T062
**Implements:** FR-030, US-016
**Description:** Update `services/settings.py` and `routers/settings.py` so `GET /settings` returns `ai_resolve_default` and `ai_resolve_confidence_threshold`, and `PUT /settings` persists them.
**Acceptance:**
- [ ] `GET /settings` fresh DB returns `ai_resolve_default=false`, threshold `0.7`.
- [ ] `PUT /settings` with valid payload persists both fields.
- [ ] `PUT /settings` with threshold `> 1.0` returns 422.

### T064 ✓ — TypeScript types + API client
**Depends on:** T063
**Implements:** FR-025, FR-027, FR-028, FR-029, FR-030
**Description:** Extend `webapp/src/types/api.ts` with `ResolvedSource`, `ResolutionVerdict`, `ResolutionChipState` types and the seven new `Ticket` fields and two new `FilterSettings` fields. Add `resolveTicket`, `reopenTicket`, `setAiResolve`, `dismissChip`, and updated `listTickets` to `webapp/src/api/client.ts`.
**Acceptance:**
- [ ] TypeScript compilation passes with no new `any`s.
- [ ] `listTickets({ resolved: true })` appends `?resolved=true` to the request.

### T065 ✓ — Tickets store — `resolvedTickets` + actions
**Depends on:** T064
**Implements:** US-015, US-016, FR-025, FR-028
**Description:** Add `resolvedTickets` ref to `ticketsStore`. Add `refreshResolved`, `markResolved`, `reopen`, `setAiResolve`, `dismissChip` actions with optimistic updates and rollback on failure. Extend `refresh` + `silentRefresh` to fetch both lists in parallel. Extend `applyOverride` to move resolved tickets back to open when overriding.
**Acceptance:**
- [ ] `markResolved` moves ticket from `tickets` to `resolvedTickets` optimistically; rolls back on API failure.
- [ ] `reopen` moves ticket from `resolvedTickets` to `tickets` optimistically; rolls back on API failure.
- [ ] `dismissChip` sets `resolution_chip_state` to `null` locally.

### T066 ✓ — `ResolvedColumn` + Board integration
**Depends on:** T065
**Implements:** US-015, FR-025, FR-028
**Description:** Create `webapp/src/components/ResolvedColumn.vue` — always-visible column sourced from `resolvedTickets`, accepts drops from category columns (calls `markResolved`), allows drag-out to category columns (handled by receiving column's `applyOverride`). Integrate into `Board.vue` as the rightmost column.
**Acceptance:**
- [ ] Resolved column renders regardless of `include_category_ids` setting.
- [ ] Dragging an open ticket into the Resolved column resolves it immediately.
- [ ] Dragging a resolved ticket into a category column reopens + overrides it.

### T067 ✓ — `TicketCard` — resolve icon + `ResolutionChip`
**Depends on:** T065, T066
**Implements:** US-015, US-016, FR-027
**Description:** Add a ✓ icon to `TicketCard` that calls `markResolved` / `reopen` depending on current state. Create `ResolutionChip.vue` — advisory chip rendered on a card when `resolution_chip_state` is non-null. Clicking the chip applies the suggestion; a dismiss (×) button hides it.
**Acceptance:**
- [ ] ✓ icon resolves open tickets; on resolved cards the icon reopens.
- [ ] Chip renders only when `resolution_chip_state` is set; click applies suggestion; dismiss calls `dismissChip`.

### T068 ✓ — Flyout — resolution section + AI tri-state toggle
**Depends on:** T065
**Implements:** US-015, US-016, FR-029
**Description:** Add a *Resolution* section to `TicketFlyout.vue` with a "Mark resolved" / "Reopen" button and an AI tri-state toggle (`Auto` / `On` / `Off`) that calls `setAiResolve`.
**Acceptance:**
- [ ] "Mark resolved" button resolves the ticket; changes to "Reopen" on resolved tickets.
- [ ] AI toggle cycles through `null` / `true` / `false` and persists via `PATCH /tickets/{id}/ai-resolve`.

### T069 ✓ — Settings drawer — Auto-resolve section
**Depends on:** T063, T064
**Implements:** FR-030, US-016
**Description:** Add an *Auto-resolve* section to `SettingsDrawer.vue` with a global enable toggle (`ai_resolve_default`) and a confidence threshold slider / input (`ai_resolve_confidence_threshold`). Reads/writes via `PUT /settings`.
**Acceptance:**
- [ ] Toggle and slider persist after page reload.
- [ ] Threshold input rejects values outside `[0, 1]` before submitting.

### T070 ✓ — Extension closure pass
**Depends on:** T059
**Implements:** US-017, FR-031
**Description:** Extend the extension sync flow with a closure pass: diff tracked ticket ids against the open list; for any ids no longer present, fetch them from Intercom's closed-conversation list and POST them to `POST /tickets/ingest` so `_upsert_ticket` stamps `resolved_at`. Modify `extension/api.js`, `extension/intercom.js`, and `extension/background.js`.
**Acceptance:**
- [ ] A ticket tracked as open that Intercom now reports as closed appears as resolved after the next sync.
- [ ] The closure pass does not trigger an AI categorization call.

### T071 ✓ — Extension popup — Resolved tab + resolve action
**Depends on:** T070
**Implements:** US-015, US-017
**Description:** Add a *Resolved* tab to the extension popup that renders resolved tickets from `GET /tickets?resolved=true`. Add a resolve/reopen action button per card. Modify `extension/popup.js` and `extension/popup.css`.
**Acceptance:**
- [ ] Resolved tab lists resolved tickets sorted most-recently-resolved first.
- [ ] Resolve action on an open card moves it to the Resolved tab immediately.

### T072 ✓ — Docs — `spec.md`, `plan.md`, `tasks.md`
**Depends on:** T054
**Implements:** US-015, US-016, US-017, FR-025..FR-031
**Description:** Add US-015/016/017 and FR-025..FR-031 to `spec.md`; add §8c and schema additions to `plan.md`; add Phase 11 entries to `tasks.md`. Update version headers and traceability matrix.
**Acceptance:**
- [ ] Every new FR is referenced by at least one task in the traceability matrix.
- [ ] Version headers in all three docs advance to v1.4.

### T073 ✓ — Quality gates pass on main
**Depends on:** T054, T055, T056, T057, T058, T059, T060, T061, T062, T063, T064, T065, T066, T067, T068, T069, T070, T071, T072
**Implements:** NFR-001, NFR-002, NFR-003
**Description:** All backend tests pass (`pytest`). Webapp typechecks clean (`tsc --noEmit`). Vitest suite green. Extension loads without warnings in Chrome. End-to-end smoke: resolve a ticket manually, verify it appears in Resolved column on both webapp and popup, reopen it, verify it returns to its category column.
**Acceptance:**
- [ ] `pytest` exits 0.
- [ ] `npm run typecheck` exits 0 in `webapp/`.
- [ ] Extension side-loads without manifest errors.
- [ ] Manual smoke test passes for all three resolution paths (manual, AI chip, Intercom-closed).

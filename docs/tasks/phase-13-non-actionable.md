# Phase 13 — Non-actionable tickets

Back to [tasks.md](../../tasks.md).

Spec: [`docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md`](../superpowers/specs/2026-05-25-non-actionable-tickets-design.md).
Plan: [`docs/superpowers/plans/2026-05-25-non-actionable-tickets.md`](../superpowers/plans/2026-05-25-non-actionable-tickets.md).

### T085 — Migration 0010
**Depends on:** T054
**Implements:** FR-037, plan §6
**Description:** Widen `tickets.resolved_source` and `ai_cache.ai_resolution_verdict` CHECK constraints to include `'non_actionable'`. No new columns.
**Acceptance:**
- [x] In-memory smoke + pytest pass.
- [x] `alembic upgrade head` → `downgrade -1` round-trip clean.

### T086 — AI prompt + parser carry non_actionable
**Depends on:** T056, T085
**Implements:** FR-037, US-019
**Description:** SYSTEM_PROMPT documents the 3-way verdict and the canonical kind tags. Parser accepts all three values; rejects others as `None` (existing fallback path).
**Acceptance:**
- [x] `tests/test_resolution_prompt.py` passes for non_actionable cases.
- [x] Out-of-set verdict still clamps to `None`.

### T087 — Ingest auto-applies non_actionable
**Depends on:** T086
**Implements:** FR-037, plan §6
**Description:** `_upsert_ticket` stamps `resolved_source = result.ai_resolution_verdict` when verdict ∈ {resolved, non_actionable}, confidence ≥ threshold, effective `ai_resolve_enabled` is true, and the row isn't already resolved.
**Acceptance:**
- [x] `tests/test_resolution_ingest.py` covers happy path + threshold gate + auto-resolve-disabled gate.
- [x] Intercom-closed transitions still take precedence.

### T088 — Resolution service: mark_non_actionable
**Depends on:** T085
**Implements:** FR-037, US-019
**Description:** Add `apply_mark_non_actionable` + `mark_non_actionable` to `services/resolution.py`. Add `bulk_mark_non_actionable` to `services/bulk.py`. 409 if already resolved, 404 if unknown.
**Acceptance:**
- [x] `tests/test_resolution_service.py` covers happy + 404 + 409.
- [x] Bulk loop reuses `_run_per_id`.

### T089 — Endpoints: single + bulk
**Depends on:** T088
**Implements:** FR-037, US-019
**Description:** `POST /tickets/{id}/non-actionable` + `POST /tickets/bulk/non-actionable`. Schema literal widening for `ResolvedSource` + `ResolutionVerdict`.
**Acceptance:**
- [x] `tests/test_resolution_api.py` + `tests/test_bulk_api.py` cover happy, 404, 409, cap, empty.
- [x] Reopen clears `'non_actionable'` source.

### T090 — Webapp types + API client + tickets store
**Depends on:** T089
**Implements:** FR-037
**Description:** Widen `ResolvedSource` + `ResolutionVerdict` TS unions. Add `markNonActionable` + `bulkMarkNonActionable` to client + tickets store, mirroring `markResolved` / `bulkResolve`.
**Acceptance:**
- [x] `npm run typecheck` clean.

### T091 — ResolutionChip non-actionable badge variant
**Depends on:** T090
**Implements:** FR-037
**Description:** Chip renders muted "Non-actionable" badge on resolved cards whose `resolved_source === 'non_actionable'`.
**Acceptance:**
- [ ] Manual smoke: chip renders on a seeded non-actionable ticket.

### T092 — Flyout: Mark non-actionable button
**Depends on:** T090
**Implements:** FR-037, US-019
**Description:** Add "Mark non-actionable" sibling button. Update status-pill copy to discriminate by source.
**Acceptance:**
- [ ] Manual smoke: button moves ticket to Resolved column; Reopen returns it.

### T093 — BulkActionBar: Non-actionable button
**Depends on:** T090
**Implements:** FR-037, US-019
**Description:** Add "Non-actionable" button between Resolve + Reopen. Disabled when any selected card is already resolved.
**Acceptance:**
- [ ] Manual smoke: 3-card selection → button → 3 cards move + toast.

### T094 — Extension popup
**Depends on:** T089
**Implements:** FR-037, US-019
**Description:** Add `markNonActionable` helper, ⊘ button on open-tab cards, "Non-actionable" badge on resolved-tab cards.
**Acceptance:**
- [ ] Manual smoke after reloading unpacked extension.

### T095 — Docs
**Depends on:** T094
**Implements:** plan §13
**Description:** Widen CLAUDE.md invariant #10, add Phase 13 to tasks.md index + traceability matrix, add T106/T107 backlog stubs, refresh spec.md + plan.md version headers if appropriate.
**Acceptance:**
- [x] Repo-wide green path passes per CLAUDE.md table.

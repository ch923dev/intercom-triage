# Phase 4 — Category management API

Back to [tasks.md](../../tasks.md).

### T018 ✓ — `POST /categories`, `PATCH /categories/{id}`, `POST /categories/{id}/archive`
**Depends on:** T006, T007
**Implements:** FR-017
**Description:** CRUD on active categories. Archive sets `is_active=false, archived_at=now()`. Fallback category cannot be archived (409).
**Acceptance:** Create returns the new row; patch updates fields without changing id; archive of fallback returns 409.

### T019 ✓ — Archive sweeper
**Depends on:** T018, T017
**Implements:** FR-017
**Description:** On archive, repoint `ai_cache.category_id` and `overrides.category_id` from the archived id to the fallback. Run inline in the same transaction as the archive update.
**Acceptance:** After archive, no `ai_cache` or `overrides` row references the archived id.

### T020 ✓ — `POST /categories/{src}/merge-into/{dst}`
**Depends on:** T018
**Implements:** FR-017
**Description:** Single transaction: update `ai_cache.category_id` and `overrides.category_id` from src to dst, archive src.
**Acceptance:** After merge, no rows reference src; transaction is atomic (failure mid-merge leaves no partial state).

### T021 ✓ — `GET /proposals`
**Depends on:** T006
**Implements:** US-010, FR-016
**Description:** Returns pending proposals with up to 5 example ticket ids each.
**Acceptance:** Pending proposals listed; resolved ones excluded.

### T022 ✓ — `POST /proposals/{id}/approve`
**Depends on:** T017, T021
**Implements:** FR-016
**Description:** Transaction: create a new active `categories` row with `source=ai_proposed`. Update proposal `status=approved`, `resolved_category_id=<new>`. Rewrite cache rows pointing at the proposal to point at the new category.
**Acceptance:** Approving moves the proposal's tickets to a new active column on the next fetch.

### T023 ✓ — `POST /proposals/{id}/merge-into/{category_id}`
**Depends on:** T022
**Implements:** FR-016
**Description:** Like approve, but no new category created; cache rows repoint to the target.
**Acceptance:** Merging reassigns all proposal tickets to the target.

### T024 ✓ — `POST /proposals/{id}/reject`
**Depends on:** T022, T006
**Implements:** FR-016
**Description:** Update proposal `status=rejected, resolved_category_id=<fallback>`. Repoint cache rows to fallback. Insert normalized signature into `rejected_proposal_signatures`.
**Acceptance:**
- Rejected proposal's tickets move to fallback.
- A subsequent AI proposal with the same normalized name does not re-create a pending row (T015 path validated).

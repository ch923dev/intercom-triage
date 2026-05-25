# Phase 3 — AI pipeline

Back to [tasks.md](../../tasks.md).

### T012 ✓ — OpenRouter client
**Depends on:** T004
**Implements:** plan §7
**Description:** Authenticated async client. Headers: `Authorization`, `HTTP-Referer`, `X-Title`. Method returns raw model output string.
**Acceptance:** Mocked test confirms request shape per plan §7.

### T013 ✓ — Dynamic prompt builder
**Depends on:** T012, T006
**Implements:** plan §7
**Description:** Build the dynamic user prompt against the production models. Given active categories, pending proposals, and rejected names, assemble the user message. Build transcript with `[type:name] body`, ≤ 6000 chars middle-truncated.
**Acceptance:** Active categories, pending proposals, and rejected names all appear in the user prompt; a 10 000-char transcript is middle-truncated with marker.

### T014 ✓ — AI response parser
**Depends on:** T013
**Implements:** FR-004, FR-005, FR-006, FR-015
**Description:** Tolerant JSON parser (strip ` ``` ` fences, brace extraction). Validate `assignment ∈ {existing, pending_proposal, new_proposal}`. For `existing`/`pending_proposal`, verify id exists in the expected state. Normalize `proposed_name` (trim, title-case, lowercase-hash).
**Acceptance:** Each of the three assignments parses correctly; invalid id → fallback path triggered; normalized signature deterministic across whitespace/case differences.

### T015 ✓ — Output resolver
**Depends on:** T014, T006
**Implements:** FR-015, plan §7 output resolution
**Description:** Resolve the parsed response into a final `(category_id | proposal_id)`. For `new_proposal`: if signature exists in `rejected_proposal_signatures` → fallback; if a pending proposal with the same signature exists → reuse it; otherwise insert a new `category_proposals` row and use its id.
**Acceptance:**
- Novel name inserts a new row.
- Duplicate of a pending row reuses the existing id.
- Rejected signature returns fallback.

### T016 ✓ — Parallel categorization with fallback
**Depends on:** T015
**Implements:** FR-007, NFR-003, plan §7 concurrency
**Description:** `categorize_many(tickets)` using `asyncio.gather` wrapped per call by `Semaphore(AI_CONCURRENCY)`. Any exception → fallback `(fallback category, title[:280], 0.0)`.
**Acceptance:** Ten tickets where one mock throws → ten results returned, the failing one has fallback values.

### T017 ✓ — AI cache read/write
**Depends on:** T006, T016
**Implements:** FR-008
**Description:** Repository methods `get_cached(ticket_id, updated_at)` and `set_cached(...)`. Invalid on TTL expiry or stale `updated_at`. Stores either `category_id` or `proposal_id` per the XOR constraint.
**Acceptance:**
- Two reads within TTL with same `updated_at` → second is a hit.
- Read with newer `updated_at` → miss.
- Read after TTL expiry → miss.

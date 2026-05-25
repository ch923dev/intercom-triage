# Phase 5 — Tickets API + overrides + settings

Back to [tasks.md](../../tasks.md).

### T025 ✓ — `POST /tickets/ingest` + `GET /tickets`
**Depends on:** T010, T016, T017, T007
**Implements:** FR-001, FR-004, FR-005, FR-006, FR-008, FR-011, FR-013
**Description:** The extension scrapes Intercom via the browser session and POSTs `HydratedTicket[]` to `/tickets/ingest`. Backend splits cached vs uncached, runs AI on uncached, writes cache, upserts tickets. `GET /tickets` serves the stored board (open by default, `?resolved=true` for the Resolved column) applying overrides + filters and sorting `updated_at` desc.
**Acceptance:**
- Ingest a batch with mocked OpenRouter → tickets stored + categorized.
- Re-ingest unchanged conversations → zero OpenRouter calls (cache hit).
- `GET /tickets` returns ordered, categorized tickets from storage.

### T026 ✓ — Override endpoint + cache integration
**Depends on:** T006, T025
**Implements:** FR-009
**Description:** `PATCH /tickets/{id}/category` upserts into `overrides` with `set_at=now()`. `GET /tickets` applies overrides after AI step and sets `user_override=true`. Override invalidates when `ticket.updated_at > override.set_at`.
**Acceptance:**
- PATCH then re-read → ticket in overridden column, `user_override=true`.
- Simulating advanced `updated_at` → override dropped on next read.

### T027 ✓ — `GET /settings` and `PUT /settings`
**Depends on:** T006
**Implements:** FR-012
**Description:** Read and write the singleton row. Defaults inserted by T006's seed.
**Acceptance:** GET returns defaults on fresh DB; subsequent GET reflects last PUT.

### T028 ✓ — Structured logging on external calls
**Depends on:** T010, T016
**Implements:** NFR-006
**Description:** Wrap Intercom and OpenRouter calls with structured logs carrying `op`, `duration_ms`, `outcome`, `ticket_id`. No ticket bodies.
**Acceptance:** A fetch produces the expected log lines; no ticket body appears anywhere.

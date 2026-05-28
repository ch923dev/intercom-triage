# Phase 2 — Intercom integration (superseded)

Back to [tasks.md](../../tasks.md).

> **Entire phase superseded.** The backend never received an Intercom Access Token. Ingestion pivoted to the Chrome extension, which scrapes the operator's logged-in browser session via Intercom's internal `ember/` API and POSTs `HydratedTicket[]` to `/tickets/ingest`. See T025 (Phase 5) + T040–T042 (Phase 7) for the replacement path. Task bodies retained as historical record.

### T008 ⊘ — Intercom HTTP client
**Status:** superseded — backend has no Intercom Access Token; ingestion pivoted to the Chrome extension (see T025, T040–T042).
**Depends on:** T004
**Implements:** plan §6
**Description:** Async `httpx` client with `Authorization: Bearer <token>` and `Intercom-Version` headers. Module-level `IntercomError`. Resolves workspace id once at startup via `GET /me` and stores in process memory.
**Acceptance:** Mocked test confirms headers and the workspace id cache.

### T009 ⊘ — Search with threshold + state filter
**Status:** superseded — extension drives the conversation list directly from the operator's logged-in session; backend never calls Intercom search.
**Depends on:** T008
**Implements:** FR-001, FR-002
**Description:** Build search body `AND([updated_at > threshold, state filter])`. Paginate via `starting_after` until `MAX_TICKETS_PER_FETCH`.
**Acceptance:** Threshold conversion correct for both units; multi-page mocked response stitched and bounded by the cap.

### T010 ⊘ — Hydration + HTML stripping
**Status:** superseded — extension hydrates via the internal Intercom `ember/` API and POSTs `HydratedTicket[]` to `/tickets/ingest`.
**Depends on:** T009
**Implements:** FR-003, NFR-003
**Description:** Per result, `GET /conversations/{id}?display_as=plaintext`. Strip HTML. Drop empty parts. Hydrate in parallel; per-ticket failures isolated.
**Acceptance:** One failure in three → two tickets returned, no exception. No `<` characters in hydrated bodies.

### T011 ⊘ — Deep-link builder
**Status:** superseded — extension composes the deep link client-side from the operator-provided `app_id` + ticket id.
**Depends on:** T008
**Implements:** FR-010
**Description:** Compose link from the cached workspace id and the ticket id.
**Acceptance:** Hydrated ticket has non-null `url` matching the documented pattern.

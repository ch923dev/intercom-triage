# Intercom Triage — Tasks

**Status:** ready · **Version:** 2.0 · **Implements:** `spec.md` v2.0, `plan.md` v2.0

Index of tasks. Each task is a single PR; full bodies (acceptance criteria, dependencies, descriptions) live in [`docs/_archive/tasks/`](../_archive/tasks/).

**Conventions.**
- `[P]` next to a task ID means it may run in parallel with siblings at the same dependency depth.
- `Implements:` (in the detail files) links to FR-xxx, NFR-xxx, US-xxx (from `spec.md`) or plan §x (from `plan.md`).
- `Depends on:` (in the detail files) lists task IDs that must be merged first.
- Acceptance criteria are testable — write the test before the code.

**Status markers.**
- `✓` = shipped and live in `main`.
- `⊘` = superseded. Detail file retains the original body and names the replacement.
- No marker = still open / backlog.

**Changes from v2.0 (MHU charter pivot — auth + multi-user):** hosted, authenticated, shared-team board. New Phase 20 (T168–T171): auth core (OnlySales-delegated login, stateless access JWT, DB-backed rotating refresh token, migrations 0021–0022), refresh reuse-detection + rate-limit hardening, attribution columns (`resolved_by`/`acted_by`, migration 0023), assignment + My Queue (`assigned_to`/`assigned_at`, migration 0024). Adds US-040–US-043, FR-063–FR-073, NFR-011–NFR-014. Plan §19. CLAUDE.md Scope guardrails + invariants #15–#19 updated.

**Changes from v1.7 (Intercom ingestion pivot):** the backend now fetches Intercom directly from the official `api.intercom.io` REST API with a workspace Access Token, replacing the extension session scrape. New Phase 19 (T161–T166): Intercom client, normalizer, sync orchestration + `POST /tickets/sync`, background poller + config/health, extension reduction, docs/charter. Rewrote FR-001 + FR-031, added NFR-010. `GET /tickets/sync-state` route retired (the service stays, internal).

**Changes from v1.6 (reconciliation):** the forward roadmap (`docs/_archive/ROADMAP.md`) was executed in full through Phase 3 + 4.1, but the work shipped to `main` ahead of these docs. This revision backfills the source-of-truth tasks for it: new Phases 15–18 (T142–T160) cover roadmap 0.2–3.3 and R.4; T106 (parked, roadmap 4.1) and T102 (cost meter, realized by roadmap 1.4) are marked `✓`. Traceability matrix gains FR-043..FR-061, NFR-009, and US-022..US-039. Total task count ~160. Detail bodies are inline below + the acceptance criteria in `spec.md`; per-feature commit SHAs are cited for traceability.

**Changes from v1.4:** added Phase 12 (bulk actions) — T074–T083. Covers Pydantic bulk schemas, six bulk endpoints (resolve / reopen / recategorize / dismiss-chip / followup set / followup clear), backend tests, Vitest harness, `selectionStore` + card/column wiring, `BulkActionBar` + category picker reuse, tickets-store bulk actions with per-id rollback, multi-drag wiring through Board + ResolvedColumn, and `/metrics` counters. Total task count ~83.

**Changes from v1.3:** added Phase 11 (ticket resolution) — T054–T073. Covers Alembic migration, Pydantic schemas, AI prompt/parser, resolver, cache, ingest closure transition, resolution service, endpoints, resolved filter + chip-state, settings, TS types, store, ResolvedColumn, TicketCard + chip, flyout, settings drawer, extension closure pass, popup Resolved tab, docs update, and quality gates. Total task count ~73.

**Changes from v1.2:** added Phase 10 (follow-ups / alarms / notes) — backend T045–T048 + frontend T049–T053. Webapp tokens task T029 expanded to load the design tokens listed in plan §8b. Category seed colors swapped from hex to oklch (T006 already merged — handled as a 1-line patch). Total task count ~55.

**Changes from v1.1:** removed Phase 2 (multi-tenant DB tasks rewritten lighter), Phase 3 (auth — entire phase gone), cloud-deploy tasks collapsed, KMS task removed. Total task count ~40, down from ~59.

---

## Index

### [Phase 0 — Scaffolding](../_archive/tasks/phase-00-scaffolding.md)
- T001 ✓ — Repo scaffold
- T002 [P] ✓ — Dev tooling

### [Phase 1 — Backend foundation](../_archive/tasks/phase-01-backend-foundation.md)
- T003 ✓ — Backend project init
- T004 ✓ — Settings + .env.example
- T005 ✓ — FastAPI skeleton + `/health`
- T006 ✓ — SQLAlchemy models + init_db
- T007 [P] ✓ — `GET /categories`

### [Phase 2 — Intercom integration (superseded)](../_archive/tasks/phase-02-intercom-superseded.md)
- T008 ⊘ — Intercom HTTP client
- T009 ⊘ — Search with threshold + state filter
- T010 ⊘ — Hydration + HTML stripping
- T011 ⊘ — Deep-link builder

### [Phase 3 — AI pipeline](../_archive/tasks/phase-03-ai-pipeline.md)
- T012 ✓ — OpenRouter client
- T013 ✓ — Dynamic prompt builder
- T014 ✓ — AI response parser
- T015 ✓ — Output resolver
- T016 ✓ — Parallel categorization with fallback
- T017 ✓ — AI cache read/write

### [Phase 4 — Category management API](../_archive/tasks/phase-04-category-api.md)
- T018 ✓ — `POST /categories`, `PATCH /categories/{id}`, `POST /categories/{id}/archive`
- T019 ✓ — Archive sweeper
- T020 ✓ — `POST /categories/{src}/merge-into/{dst}`
- T021 ✓ — `GET /proposals`
- T022 ✓ — `POST /proposals/{id}/approve`
- T023 ✓ — `POST /proposals/{id}/merge-into/{category_id}`
- T024 ✓ — `POST /proposals/{id}/reject`

### [Phase 5 — Tickets API + overrides + settings](../_archive/tasks/phase-05-tickets-overrides-settings.md)
- T025 ✓ — `POST /tickets/ingest` + `GET /tickets`
- T026 ✓ — Override endpoint + cache integration
- T027 ✓ — `GET /settings` and `PUT /settings`
- T028 ✓ — Structured logging on external calls

### [Phase 6 — Webapp](../_archive/tasks/phase-06-webapp.md)
- T029 ✓ — Vite + Vue 3 + TS scaffold
- T030 ✓ — Typed API client
- T031 ✓ — Tickets + categories stores (Pinia)
- T032 ✓ — Kanban layout, dynamic columns
- T033 ✓ — TicketCard
- T034 ✓ — Drag-and-drop override
- T035 ✓ — Settings drawer
- T036 ✓ — Toolbar + keyboard nav
- T037 ✓ — Category management page
- T038 ✓ — Proposals review page
- T039 ✓ — Extension discovery callout

### [Phase 7 — Chrome extension](../_archive/tasks/phase-07-extension.md)
- T040 ✓ — MV3 manifest + popup shell
- T041 ✓ — Popup mini-board
- T042 ✓ — Background poll + badge

### [Phase 8 — Polish](../_archive/tasks/phase-08-polish.md)
- T043 ✓ — `GET /metrics` lightweight counters
- T044 ✓ — README + quickstart

### [Phase 10 — Follow-ups, alarms, notes](../_archive/tasks/phase-10-followups.md)
- T045 ✓ — `followups` + `ticket_notes` tables + `settings.mute_alarms`
- T046 ✓ — Follow-up endpoints
- T047 ✓ — Notes endpoints
- T048 ✓ — `GET /tickets` composes follow-up + note + mute
- T049 ✓ — Webapp tokens + dark mode + accent picker
- T050 ✓ — Follow-up store + chip + pin-to-top
- T051 ✓ — Alarm loop + banner stack + mute
- T052 ✓ — Notes section in flyout
- T053 ✓ — Popup mirror — due banner + chip

### [Phase 11 — Ticket resolution](../_archive/tasks/phase-11-resolution.md)
- T054 ✓ — Alembic migration + SQLAlchemy model additions
- T055 ✓ — Pydantic schemas: resolution fields + new request bodies
- T056 ✓ — AI prompt + parser carry resolution verdict
- T057 ✓ — `CategorizationResult` + resolver carry resolution
- T058 ✓ — AI cache reads/writes resolution fields
- T059 ✓ — `_upsert_ticket` auto-resolves on Intercom open→closed transition
- T060 ✓ — `services/resolution.py` — manual resolve / reopen / AI toggle / dismiss
- T061 ✓ — Resolution endpoints + router wiring
- T062 ✓ — `GET /tickets` resolved filter + chip-state computation + drag-out reopen
- T063 ✓ — Settings endpoint carries `ai_resolve_default` + threshold
- T064 ✓ — TypeScript types + API client
- T065 ✓ — Tickets store — `resolvedTickets` + actions
- T066 ✓ — `ResolvedColumn` + Board integration
- T067 ✓ — `TicketCard` — resolve icon + `ResolutionChip`
- T068 ✓ — Flyout — resolution section + AI tri-state toggle
- T069 ✓ — Settings drawer — Auto-resolve section
- T070 ✓ — Extension closure pass
- T071 ✓ — Extension popup — Resolved tab + resolve action
- T072 ✓ — Docs — `spec.md`, `plan.md`, `tasks.md`
- T073 ✓ — Quality gates pass on main

### [Phase 12 — Bulk actions](../_archive/tasks/phase-12-bulk.md)
- T074 ✓ — Pydantic bulk schemas
- T075 ✓ — Bulk resolve + reopen endpoints
- T076 ✓ — Bulk recategorize endpoint
- T077 ✓ — Bulk dismiss-chip endpoint
- T078 ✓ — Bulk follow-up set + clear endpoints
- T079 ✓ — Backend tests for T075–T078
- T080 ✓ — Vitest harness + selection store
- T081 ✓ — Card + column selection wiring
- T082 ✓ — `BulkActionBar` + tickets-store bulk actions
- T083 ✓ — Bulk drag through Board + ResolvedColumn
- T084 ✓ — `/metrics` bulk counters + docs refresh

### [Phase 13 — Non-actionable tickets](../_archive/tasks/phase-13-non-actionable.md)
- T085 ✓ — Migration 0010 widens resolved_source + ai_resolution_verdict CHECK
- T086 ✓ — AI prompt + parser carry non_actionable verdict
- T087 ✓ — Ingest auto-applies non_actionable under shared threshold
- T088 ✓ — Resolution service: mark_non_actionable + bulk variant
- T089 ✓ — `POST /tickets/{id}/non-actionable` + `POST /tickets/bulk/non-actionable`
- T090 ✓ — Webapp types + API client + tickets store actions
- T091 ✓ — ResolutionChip non-actionable badge variant
- T092 ✓ — Flyout: Mark non-actionable button
- T093 ✓ — BulkActionBar: Non-actionable button
- T094 ✓ — Extension popup: non-actionable button + badge
- T095 ✓ — Docs (CLAUDE.md invariant, spec/plan/tasks index)

### [Phase 14 — Playbooks](../superpowers/specs/2026-05-26-playbooks-design.md)
- T130 ✓ — `Playbook` model + Alembic migration.
- T131 ✓ — Schemas + create/list/archive service.
- T132 ✓ — `list_for_ticket` effective-category resolution.
- T133 ✓ — update/restore/list_all service.
- T134 ✓ — CRUD router + registration.
- T135 ✓ — AI draft builder (excludes internal_notes) + service.
- T136 ✓ — Draft endpoint.
- T137 ✓ — Frontend types + API client.
- T138 ✓ — Pinia store.
- T139 ✓ — Flyout playbooks section.
- T140 ✓ — Library page + nav.
- T141 ✓ — spec/plan/tasks/CLAUDE invariant docs.

### Phase 4.1 — Parked / snoozed state (roadmap 4.1)
- T106 ✓ — Parked state: `parked_at`/`parked_until`/`parked_reason`(+`parked_note`) trio (migrations 0018/0019), park/unpark + bulk routes, webapp Layout B + ParkMenu, extension Parked tab. Spec FR-042/US-021, plan §14, invariant #14. Commits `889c0f1`, `87522a2`.

### Phase 15 — Operator throughput quick wins (roadmap 0.2–0.4)
- T142 ✓ — Triage facets: `priority`/`sentiment`/`labels` on the categorization call; cached on `ai_cache`, surfaced on `TicketSchema`, priority badge. Cross-package (backend+webapp), cache key unchanged. FR-043/FR-044/US-022. Commit `784832f`.
- T143 ✓ — Aging/SLA card stripes tiered by time since last customer message. FR-045/US-023. Commit `ee99ca5`.
- T144 ✓ — Keyboard-driven triage (`j`/`k`/`e`/digit/`/`), input-guarded. FR-046/US-024/NFR-007. Commit `5630f47`.

### Phase 16 — Throughput + first analytics (roadmap 1.1–1.6)
- T145 ✓ — Saved views / smart filters (client-side, localStorage). FR-047/US-025. Commit `e93084c`.
- T146 ✓ — Priority-sorted queue (optional within-column order). FR-048/US-026. Commit `fe4fa95`.
- T147 ✓ — Stats dashboard: `GET /stats` rollup + `StatsPage`. FR-049/US-027. Commit `c3b9565`.
- T148 ✓ — Token / cost meter: per-(date,model) tokens + USD on `/metrics` + webapp. FR-050/US-028 (realizes T102). Commit `a3074f5`.
- T149 ✓ — Snippets / canned-response manager (`snippets` table + CRUD + `{{var}}`). FR-051/US-029. Commit `86125b1`.
- T150 ✓ — Bulk pre-flight diff preview (client-side, respects `MAX_BULK_IDS`). FR-052/US-030. Commit `58d70a6`.

### Phase 17 — AI reliability + embedding keystone (roadmap 2.1–2.6)
- T151 ✓ — Structured (`json_object`) categorization output; `SYSTEM_PROMPT` + defensive `parse_response` carry the contract. FR-053/US-031. Commit `d6a77cf`. **Amended 2026-06-04:** the original JSON-schema-enforced form (`oneOf`) was reverted — the default Anthropic model rejects `oneOf` + numeric `min`/`max`, 400-ing every call into fallback.
- T152 ✓ — Model cascade (cheap→strong on low confidence), opt-in, off by default. FR-054/US-032. Commit `6892a31`.
- T153 ✓ — Needs-review lane over `ai_confidence` (view-layer, calibrated threshold). FR-055/US-033. Commit `4c354c3`.
- T154 ✓ — Local offline embedding layer (sentence-transformers + `ticket_embeddings`, migration 0017-era). Keystone. FR-056/US-034. Commit `d917ebd`.
- T155 ✓ — Few-shot categorization from confirmed-override neighbours. FR-057/US-035. Commit `e7a2288`.
- T156 ✓ — RAG draft replies grounded in resolved tickets + playbooks (`POST /playbooks/draft-reply`). FR-058/US-036. Commit `cd45ec7`.

### Phase 18 — Insights harvested from embeddings (roadmap 3.1–3.3, R.4)
- T157 ✓ — Offline HDBSCAN clustering of resolved tickets + c-TF-IDF labels (`/clusters`, background loop). FR-059/US-037. Commit `db8272d`.
- T158 ✓ — Playbook-gap ranking (`GET /clusters/gaps`). FR-060/US-038. Commit `790cf59`.
- T159 ✓ — Semantic playbook auto-match on ticket open (`GET /playbooks/suggested`). FR-061/US-039. Commit `a2de64f`.
- T160 ✓ — Latency p50/p95/max histograms in `metrics.py` (robustness R.4). NFR-009. Commit `ffb28c5`.

### Phase 19 — Backend-direct Intercom ingestion (Access Token pivot)
- T161 ✓ — Intercom REST client (`clients/intercom.py`): `POST /conversations/search` (cursor), `GET /conversations/{id}`, TTL-cached `GET /contacts/{id}`; retry + 429/`X-RateLimit-Reset` aware; `IntercomError`/`IntercomAuthError`. FR-001, inv #1.
- T162 ✓ — Official-API → `HydratedTicket` normalizer (`services/intercom_normalizer.py`): `part_type` routing, `source`-first, priority/state coercion, HTML strip + attachment fallback, contact panel-field merge. FR-003, inv #2/#3/#4, R.1/R.5.
- T163 ✓ — Sync orchestration (`services/sync.py:run_sync_cycle`): server-side skip-known + closure pass; `POST /tickets/sync` + `SyncResponse`; `GET /tickets/sync-state` route retired (service kept internal). FR-001, FR-031.
- T164 ✓ — Background poller + lifespan wiring (`main:_intercom_poll_loop`, `get_intercom` dep); `intercom_*` config + `intercom_configured`/`missing_secrets` + `/health.intercom_configured`. FR-001, NFR-010.
- T165 ✓ — Extension reduction: delete `intercom.js` + ember scraping/closure/sync; drop `app.intercom.com` host perm, app_id setup, Sync button; popup = read-only board + badge-only poller. inv #1.
- T166 ✓ — Docs/charter: invariants #1/#2/#3 rewrite, spec FR-001/FR-031 + NFR-010, plan §2/§4/§6, PROJECT/FEATURES, SECURITY (two secrets) + gitleaks Intercom-token rule, README, sub-package CLAUDE.md.
- T167 ✓ — Remove the Chrome extension entirely: deleted `extension/`, the CORS `chrome-extension://` regex, `webapp/.../ExtensionCallout.vue` (→ `EmptyBoard.vue`), `qa-extension`, and `check-invariants.ps1` extension rules; scrubbed spec/plan/tasks/PROJECT/FEATURES/README + the 14 invariants (#1/#10/#14). Continuation of T165. spec v1.9, inv #1.

### Phase 20 — Auth & multi-user (MHU charter pivot)

- T168 ✓ — Auth core: OnlySales-delegated login (`POST /auth/login`), stateless HS256 access JWT (~30 min, offline-verified), DB-backed rotating refresh token (sha256-hashed, httpOnly+Secure+SameSite cookie), `users` + `sessions` tables (migrations 0021–0022), `get_current_user` gate on all routers except allowlist, webapp login screen + in-memory access token + silent refresh + 401→refresh→retry loop. FR-063/FR-064/FR-065/FR-066/FR-067/FR-073, US-040, NFR-011/NFR-012, plan §19.
- T169 ✓ — Refresh reuse-detection + rate-limit hardening: `sessions.prev_refresh_token_hash` (migration 0022 — included in T168 chain); replaying a rotated-away token revokes the entire session chain immediately; `POST /auth/login` rate-limited per source IP and per target email with bucket eviction. FR-065/FR-068/FR-069, US-043, NFR-013/NFR-014, plan §19.
- T170 ✓ — Attribution: migration 0023 adds `tickets.resolved_by` + `overrides.acted_by` (FK → users, SET NULL); manual resolve / mark-non-actionable / category override (single + bulk) stamp the acting operator; AI/system paths leave null; board composes `UserRef {id, name}` via user-join; flyout shows "resolved by \<name\>". FR-072, US-042, plan §19.
- T171 ✓ — Assignment + My Queue: migration 0024 adds `tickets.assigned_to` + `assigned_at` (FK → users, nullable, SET NULL, indexed); `PATCH /tickets/{id}/assign` + `/tickets/bulk/assign` (null clears; unknown user → 422; bounded by MAX_BULK_IDS); `GET /users` trimmed to `{id, name}`; webapp `myQueueOnly` filter chip + `AssigneePicker` + card tag + Topbar chip. FR-070/FR-071, US-041, plan §19.

### [Phase 9 — Backlog](../_archive/tasks/backlog.md)
- T100 — Webhook subscription on `conversation.user.created`/`conversation.user.replied`; push channel (SSE) to the webapp. *(roadmap 4.3 — open)*
- T102 ✓ — Token / cost meter surfacing OpenRouter spend per day. *(realized by roadmap 1.4 → T148)*
- T103 ⊘ — Multi-user expansion: add a `users` table + simple session cookie auth + per-user overrides and settings. *(superseded by T168–T171 — MHU charter pivot)*
- T104 ✓ — Alembic migrations.
- T107 ✓ — Structured `non_actionable_kind` column on tickets + ai_cache (migration 0020); AI emits/parses + strict schema; cached; stamped on AI non_actionable auto-mark, cleared on every reopen path; surfaced on TicketSchema; webapp chip label + per-kind filter; extension popup chip. FR-062/US-019, plan §8c, migration 0020. Branch feat/t107-non-actionable-kind. *(Cross-package backend+webapp+extension at the API-contract level; HydratedTicket / invariant #2 untouched — non_actionable_kind is board-state on TicketSchema, like triage facets T142.)*

---

## Traceability matrix

Every requirement maps to at least one task.

| Requirement | Implementing tasks |
|---|---|
| FR-001 | T009, T025, T161, T162, T163, T164 |
| FR-002 | T009 |
| FR-003 | T010 |
| FR-004 | T014, T007, T025 |
| FR-005 | T014, T025 |
| FR-006 | T014, T025 |
| FR-007 | T016 |
| FR-008 | T017, T025 |
| FR-009 | T026, T034 |
| FR-010 | T011 |
| FR-011 | T025, T035 |
| FR-012 | T027, T035 |
| FR-013 | T025, T032 |
| FR-014 | T004 |
| FR-015 | T013, T014, T015 |
| FR-016 | T022, T023, T024 |
| FR-017 | T018, T019, T020, T037 |
| FR-018 | T006, T007 |
| FR-019 | T045, T046, T048 |
| FR-020 | T051 |
| FR-021 | T051 |
| FR-022 | T046, T051 |
| FR-023 | T045, T047, T052 |
| FR-024 | T045, T049, T051 |
| NFR-001 | verified via T025 integration test |
| NFR-002 | T017 |
| NFR-003 | T010, T016 |
| NFR-004 | T006 |
| NFR-005 | T004 |
| NFR-006 | T028, T043 |
| NFR-007 | T036 |
| NFR-008 | T005 (single `uvicorn` command) |
| US-001..US-011 | covered transitively above |
| US-015 | T061, T062, T065, T066, T067, T068, T071 |
| US-016 | T056, T057, T058, T062, T063, T065, T067, T068, T069 |
| US-017 | T059, T070, T071 |
| FR-025 | T054, T059, T060, T061, T062, T064, T065, T066 |
| FR-026 | T055, T059, T060 |
| FR-027 | T054, T055, T056, T057, T058, T062, T067 |
| FR-028 | T055, T061, T062, T064 |
| FR-029 | T054, T055, T060, T064, T065, T068 |
| FR-030 | T054, T055, T063, T064, T069 |
| FR-031 | T070, T163 |
| FR-032 | T080, T081 |
| FR-033 | T074, T075, T076, T077, T078, T082 |
| FR-034 | T080, T081 |
| FR-035 | T083 |
| FR-036 | T074 |
| US-018 | T074, T075, T076, T077, T078, T081, T082, T083 |
| FR-037 | T086, T087, T088, T089, T090, T091, T092, T093 |
| US-019 | T088, T089, T092, T093, T094 |
| US-020 | T130, T131, T132, T134, T136, T137, T138, T139, T140, T141 |
| FR-038 | T130, T131, T134 |
| FR-039 | T132, T134, T139 |
| FR-040 | T135, T136 |
| FR-041 | T133, T134, T138, T140 |
| US-021 | T106 |
| FR-042 | T106 |
| US-022 | T142 |
| FR-043 | T142 |
| FR-044 | T142, T146 |
| US-023 | T143 |
| FR-045 | T143 |
| US-024 | T144 |
| FR-046 | T144 |
| US-025 | T145 |
| FR-047 | T145 |
| US-026 | T146 |
| FR-048 | T146 |
| US-027 | T147 |
| FR-049 | T147 |
| US-028 | T148 |
| FR-050 | T148 |
| US-029 | T149 |
| FR-051 | T149 |
| US-030 | T150 |
| FR-052 | T150 |
| US-031 | T151 |
| FR-053 | T151 |
| US-032 | T152 |
| FR-054 | T152 |
| US-033 | T153 |
| FR-055 | T153 |
| US-034 | T154 |
| FR-056 | T154 |
| US-035 | T155 |
| FR-057 | T155 |
| US-036 | T156 |
| FR-058 | T156 |
| US-037 | T157 |
| FR-059 | T157 |
| US-038 | T158 |
| FR-060 | T158 |
| US-039 | T159 |
| FR-061 | T159 |
| FR-062 | T107 |
| NFR-009 | T160 |
| NFR-010 | T164 |
| US-040 | T168, T169 |
| US-041 | T171 |
| US-042 | T170 |
| US-043 | T169 |
| FR-063 | T168 |
| FR-064 | T168 |
| FR-065 | T168, T169 |
| FR-066 | T168 |
| FR-067 | T168 |
| FR-068 | T169 |
| FR-069 | T169 |
| FR-070 | T171 |
| FR-071 | T171 |
| FR-072 | T170 |
| FR-073 | T168 |
| NFR-011 | T168 |
| NFR-012 | T168 |
| NFR-013 | T169 |
| NFR-014 | T169 |

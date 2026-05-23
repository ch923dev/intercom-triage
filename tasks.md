# Intercom Triage — Tasks

**Status:** ready · **Version:** 1.4 · **Implements:** `spec.md` v1.4, `plan.md` v1.4

Each task is a single PR. Every task lists what spec requirement it implements and what other tasks must merge first.

**Conventions.**
- `[P]` next to a task ID means it may run in parallel with siblings at the same dependency depth.
- `Implements:` links to FR-xxx, NFR-xxx, US-xxx (from `spec.md`) or plan §x (from `plan.md`).
- `Depends on:` lists task IDs that must be merged first.
- Acceptance criteria are testable — write the test before the code.

**Changes from v1.3:** added Phase 11 (ticket resolution) — T054–T073. Covers Alembic migration, Pydantic schemas, AI prompt/parser, resolver, cache, ingest closure transition, resolution service, endpoints, resolved filter + chip-state, settings, TS types, store, ResolvedColumn, TicketCard + chip, flyout, settings drawer, extension closure pass, popup Resolved tab, docs update, and quality gates. Total task count ~73.

**Changes from v1.2:** added Phase 10 (follow-ups / alarms / notes) — backend T045–T048 + frontend T049–T053. Webapp tokens task T029 expanded to load the design tokens listed in plan §8b. Category seed colors swapped from hex to oklch (T006 already merged — handled as a 1-line patch). Total task count ~55.

**Changes from v1.1:** removed Phase 2 (multi-tenant DB tasks rewritten lighter), Phase 3 (auth — entire phase gone), cloud-deploy tasks collapsed, KMS task removed. Total task count ~40, down from ~59.

---

## Phase 0 — Scaffolding

### T001 — Repo scaffold
**Depends on:** —
**Implements:** —
**Description:** Top-level repo with `backend/`, `webapp/`, `extension/`. Root `README.md`, `.gitignore` (includes `.env` and `backend/data/`), `.editorconfig`, license.
**Acceptance:** `tree -L 2` shows three subdirs with README stubs. `.env` is gitignored.

### T002 [P] — Dev tooling
**Depends on:** T001
**Implements:** —
**Description:** Make targets (with PowerShell equivalents documented for Windows): `dev-backend`, `dev-web`, `build-ext`, `seed-db`. Pre-commit config.
**Acceptance:** All targets execute on a clean checkout.

## Phase 1 — Backend foundation

### T003 — Backend project init
**Depends on:** T001
**Implements:** —
**Description:** Python project under `backend/`. `requirements.txt` with FastAPI, uvicorn, httpx, pydantic, pydantic-settings, SQLAlchemy 2.0, aiosqlite. Ruff + mypy configured.
**Acceptance:** Fresh venv install succeeds; ruff and mypy pass on the empty project.

### T004 — Settings + .env.example
**Depends on:** T003
**Implements:** NFR-005, plan §1
**Description:** `config.py` using `pydantic-settings`. Fields: `intercom_access_token`, `openrouter_api_key`, `openrouter_model`, `database_url` (default `sqlite+aiosqlite:///./data/triage.db`), `default_lookback_hours`, `max_tickets_per_fetch`, `ai_concurrency`, `cache_ttl_seconds`, `host` (default `127.0.0.1`), `port` (default `8000`). `.env.example` checked in.
**Acceptance:** App boots without secrets; `/health` reports missing pieces explicitly. Default `database_url` resolves to a SQLite file path.

### T005 — FastAPI skeleton + `/health`
**Depends on:** T004
**Implements:** plan §4
**Description:** `main.py` with FastAPI app, permissive CORS for `localhost` and `chrome-extension://*`, lifespan hook, `GET /health` reporting status and configured model. Server binds to `127.0.0.1`.
**Acceptance:** `curl http://localhost:8000/health` returns 200 with the documented shape.

### T006 — SQLAlchemy models + init_db
**Depends on:** T003, T004
**Implements:** plan §5
**Description:** `models.py` with `Base = DeclarativeBase` and all six tables per plan §5 (`Category`, `CategoryProposal`, `AICacheEntry`, `Override`, `Settings`, `RejectedProposalSignature`). Include the XOR check constraint on `ai_cache`, the singleton check on `settings`, the partial unique indexes. `init_db()` function runs `Base.metadata.create_all` and seeds defaults (seven categories + singleton settings row) when empty. Wire into the lifespan hook.
**Acceptance:**
- First boot creates the SQLite file with all tables.
- First boot inserts seven seed categories and the singleton settings row.
- Restarting does not duplicate seeds.
- Inserting a row with both `category_id` and `proposal_id` is rejected by the DB.

### T007 [P] — `GET /categories`
**Depends on:** T005, T006
**Implements:** FR-004, FR-018
**Description:** Returns active categories + pending proposals in display order.
**Acceptance:** Fresh DB returns the seven seeded categories with `is_fallback=true` on "Other"; new pending proposal shows in the list.

## Phase 2 — Intercom integration

### T008 — Intercom HTTP client
**Depends on:** T004
**Implements:** plan §6
**Description:** Async `httpx` client with `Authorization: Bearer <token>` and `Intercom-Version` headers. Module-level `IntercomError`. Resolves workspace id once at startup via `GET /me` and stores in process memory.
**Acceptance:** Mocked test confirms headers and the workspace id cache.

### T009 — Search with threshold + state filter
**Depends on:** T008
**Implements:** FR-001, FR-002
**Description:** Build search body `AND([updated_at > threshold, state filter])`. Paginate via `starting_after` until `MAX_TICKETS_PER_FETCH`.
**Acceptance:** Threshold conversion correct for both units; multi-page mocked response stitched and bounded by the cap.

### T010 — Hydration + HTML stripping
**Depends on:** T009
**Implements:** FR-003, NFR-003
**Description:** Per result, `GET /conversations/{id}?display_as=plaintext`. Strip HTML. Drop empty parts. Hydrate in parallel; per-ticket failures isolated.
**Acceptance:** One failure in three → two tickets returned, no exception. No `<` characters in hydrated bodies.

### T011 — Deep-link builder
**Depends on:** T008
**Implements:** FR-010
**Description:** Compose link from the cached workspace id and the ticket id.
**Acceptance:** Hydrated ticket has non-null `url` matching the documented pattern.

## Phase 3 — AI pipeline

### T012 — OpenRouter client
**Depends on:** T004
**Implements:** plan §7
**Description:** Authenticated async client. Headers: `Authorization`, `HTTP-Referer`, `X-Title`. Method returns raw model output string.
**Acceptance:** Mocked test confirms request shape per plan §7.

### T013 — Dynamic prompt builder
**Depends on:** T012, T006
**Implements:** plan §7
**Description:** Adapt `snippets/prompt_builder.py` to the production models. Given active categories, pending proposals, and rejected names, build the user prompt. Build transcript with `[type:name] body`, ≤ 6000 chars middle-truncated.
**Acceptance:** Active categories, pending proposals, and rejected names all appear in the user prompt; a 10 000-char transcript is middle-truncated with marker.

### T014 — AI response parser
**Depends on:** T013
**Implements:** FR-004, FR-005, FR-006, FR-015
**Description:** Tolerant JSON parser (strip ` ``` ` fences, brace extraction). Validate `assignment ∈ {existing, pending_proposal, new_proposal}`. For `existing`/`pending_proposal`, verify id exists in the expected state. Normalize `proposed_name` (trim, title-case, lowercase-hash).
**Acceptance:** Each of the three assignments parses correctly; invalid id → fallback path triggered; normalized signature deterministic across whitespace/case differences.

### T015 — Output resolver
**Depends on:** T014, T006
**Implements:** FR-015, plan §7 output resolution
**Description:** Resolve the parsed response into a final `(category_id | proposal_id)`. For `new_proposal`: if signature exists in `rejected_proposal_signatures` → fallback; if a pending proposal with the same signature exists → reuse it; otherwise insert a new `category_proposals` row and use its id.
**Acceptance:**
- Novel name inserts a new row.
- Duplicate of a pending row reuses the existing id.
- Rejected signature returns fallback.

### T016 — Parallel categorization with fallback
**Depends on:** T015
**Implements:** FR-007, NFR-003, plan §7 concurrency
**Description:** `categorize_many(tickets)` using `asyncio.gather` wrapped per call by `Semaphore(AI_CONCURRENCY)`. Any exception → fallback `(fallback category, title[:280], 0.0)`.
**Acceptance:** Ten tickets where one mock throws → ten results returned, the failing one has fallback values.

### T017 — AI cache read/write
**Depends on:** T006, T016
**Implements:** FR-008
**Description:** Repository methods `get_cached(ticket_id, updated_at)` and `set_cached(...)`. Invalid on TTL expiry or stale `updated_at`. Stores either `category_id` or `proposal_id` per the XOR constraint.
**Acceptance:**
- Two reads within TTL with same `updated_at` → second is a hit.
- Read with newer `updated_at` → miss.
- Read after TTL expiry → miss.

## Phase 4 — Category management API

### T018 — `POST /categories`, `PATCH /categories/{id}`, `POST /categories/{id}/archive`
**Depends on:** T006, T007
**Implements:** FR-017
**Description:** CRUD on active categories. Archive sets `is_active=false, archived_at=now()`. Fallback category cannot be archived (409).
**Acceptance:** Create returns the new row; patch updates fields without changing id; archive of fallback returns 409.

### T019 — Archive sweeper
**Depends on:** T018, T017
**Implements:** FR-017
**Description:** On archive, repoint `ai_cache.category_id` and `overrides.category_id` from the archived id to the fallback. Run inline in the same transaction as the archive update.
**Acceptance:** After archive, no `ai_cache` or `overrides` row references the archived id.

### T020 — `POST /categories/{src}/merge-into/{dst}`
**Depends on:** T018
**Implements:** FR-017
**Description:** Single transaction: update `ai_cache.category_id` and `overrides.category_id` from src to dst, archive src.
**Acceptance:** After merge, no rows reference src; transaction is atomic (failure mid-merge leaves no partial state).

### T021 — `GET /proposals`
**Depends on:** T006
**Implements:** US-010, FR-016
**Description:** Returns pending proposals with up to 5 example ticket ids each.
**Acceptance:** Pending proposals listed; resolved ones excluded.

### T022 — `POST /proposals/{id}/approve`
**Depends on:** T017, T021
**Implements:** FR-016
**Description:** Transaction: create a new active `categories` row with `source=ai_proposed`. Update proposal `status=approved`, `resolved_category_id=<new>`. Rewrite cache rows pointing at the proposal to point at the new category.
**Acceptance:** Approving moves the proposal's tickets to a new active column on the next fetch.

### T023 — `POST /proposals/{id}/merge-into/{category_id}`
**Depends on:** T022
**Implements:** FR-016
**Description:** Like approve, but no new category created; cache rows repoint to the target.
**Acceptance:** Merging reassigns all proposal tickets to the target.

### T024 — `POST /proposals/{id}/reject`
**Depends on:** T022, T006
**Implements:** FR-016
**Description:** Update proposal `status=rejected, resolved_category_id=<fallback>`. Repoint cache rows to fallback. Insert normalized signature into `rejected_proposal_signatures`.
**Acceptance:**
- Rejected proposal's tickets move to fallback.
- A subsequent AI proposal with the same normalized name does not re-create a pending row (T015 path validated).

## Phase 5 — Tickets API + overrides + settings

### T025 — `POST /tickets/fetch`
**Depends on:** T010, T016, T017, T007
**Implements:** FR-001, FR-004, FR-005, FR-006, FR-008, FR-011, FR-013
**Description:** Endpoint accepting `FilterSettings`. Splits cached vs uncached, runs AI on uncached, writes cache, applies `include_category_ids` filter, sorts `updated_at` desc.
**Acceptance:**
- Mocked Intercom + mocked OpenRouter → ordered, categorized tickets.
- Re-call with no changes → zero OpenRouter calls.

### T026 — Override endpoint + cache integration
**Depends on:** T006, T025
**Implements:** FR-009
**Description:** `PATCH /tickets/{id}/category` upserts into `overrides` with `set_at=now()`. `/tickets/fetch` applies overrides after AI step and sets `user_override=true`. Override invalidates when `ticket.updated_at > override.set_at`.
**Acceptance:**
- PATCH then fetch → ticket in overridden column, `user_override=true`.
- Simulating advanced `updated_at` → override dropped on next fetch.

### T027 — `GET /settings` and `PUT /settings`
**Depends on:** T006
**Implements:** FR-012
**Description:** Read and write the singleton row. Defaults inserted by T006's seed.
**Acceptance:** GET returns defaults on fresh DB; subsequent GET reflects last PUT.

### T028 — Structured logging on external calls
**Depends on:** T010, T016
**Implements:** NFR-006
**Description:** Wrap Intercom and OpenRouter calls with structured logs carrying `op`, `duration_ms`, `outcome`, `ticket_id`. No ticket bodies.
**Acceptance:** A fetch produces the expected log lines; no ticket body appears anywhere.

## Phase 6 — Webapp

### T029 — Vite + Vue 3 + TS scaffold
**Depends on:** T001
**Implements:** —
**Description:** Initialize `webapp/` with Vite. Add Pinia, `vuedraggable@next`, ESLint, Prettier.
**Acceptance:** `npm run dev` serves the scaffold against the backend.

### T030 — Typed API client
**Depends on:** T029, T025, T026, T027
**Implements:** —
**Description:** `src/api.ts` exposing typed clients for every endpoint in plan §4. Errors surface as typed exceptions, not silent rejections.
**Acceptance:** Functions compile against the backend's OpenAPI schema; 502 raises a typed error.

### T031 — Tickets + categories stores (Pinia)
**Depends on:** T030
**Implements:** —
**Description:** Stores: `categoriesStore`, `ticketsStore`, `settingsStore`. Actions include `applyOverride(id, category_id)` with optimistic update + rollback on failure.
**Acceptance:** `applyOverride` updates immediately; reverts on a mocked failed PATCH.

### T032 — Kanban layout, dynamic columns
**Depends on:** T031
**Implements:** US-002, US-009, FR-013
**Description:** Columns rendered from `categoriesStore`, including pending proposals as live columns with a distinct visual treatment. Independent vertical scroll. Empty / loading / error states per column.
**Acceptance:**
- Fresh DB shows seven seeded columns.
- A pending proposal appears as a column with a "proposal" badge until resolved.

### T033 — TicketCard
**Depends on:** T032
**Implements:** US-003, US-005
**Description:** Title, customer, `time-ago`, summary, confidence indicator, deep-link icon (new tab, `rel="noopener noreferrer"`), override badge when applicable.
**Acceptance:** All fields render; deep-link opens in a new tab.

### T034 — Drag-and-drop override
**Depends on:** T033, T031
**Implements:** US-004, FR-009
**Description:** `vuedraggable` between columns. On drop, call `applyOverride` (optimistic + rollback).
**Acceptance:** Drag persists after refresh; failed PATCH snaps back with a toast.

### T035 — Settings drawer
**Depends on:** T031
**Implements:** US-001, US-007, FR-011, FR-012
**Description:** Drawer for lookback unit/value, states, included categories. Reads/writes via `/settings`. Apply on change.
**Acceptance:** Reloading the page restores settings from server; changing the filter triggers a refresh.

### T036 — Toolbar + keyboard nav
**Depends on:** T032
**Implements:** NFR-007
**Description:** Refresh button, last-refreshed timestamp, arrow keys to scroll columns, `r` to refresh.
**Acceptance:** Keyboard-only flow works; refresh button disables in-flight.

### T037 — Category management page
**Depends on:** T031, T018, T019, T020
**Implements:** US-011, FR-017
**Description:** A page that lists active categories with inline rename/recolor/reorder, an archive button, and a "Merge into…" action.
**Acceptance:** All four mutations work end-to-end against the API.

### T038 — Proposals review page
**Depends on:** T031, T022, T023, T024
**Implements:** US-010, FR-016
**Description:** Lists pending proposals with example tickets. Approve, "Merge into…", and Reject actions.
**Acceptance:**
- Each action calls the matching endpoint and refreshes the board.
- Rejected proposal's name no longer triggers a fresh proposal in the next fetch.

### T039 — Extension discovery callout
**Depends on:** T029
**Implements:** plan §2
**Description:** Persistent but dismissible callout on the webapp pointing to the extension folder + install instructions.
**Acceptance:** Callout appears until dismissed; dismissal persists.

## Phase 7 — Chrome extension

### T040 — MV3 manifest + popup shell
**Depends on:** T001
**Implements:** US-006
**Description:** `manifest.json` (MV3), `popup.html`, minimal popup script. Permissions: `storage`. `host_permissions` for `http://localhost:8000/*`. Icons at 16/32/48/128.
**Acceptance:** Loads as unpacked without warnings; popup renders.

### T041 — Popup mini-board
**Depends on:** T040, T025, T026
**Implements:** US-006
**Description:** Column-tab UI cycling through the full taxonomy (including pending proposals). TicketCard reused or recreated more compact. Tap-to-move override action suitable for popup size (a button list rather than full DnD).
**Acceptance:**
- All categories selectable.
- Override action works inside the popup and survives close/reopen.
- "Open full board" button opens `http://localhost:5173/`.

### T042 — Background poll + badge
**Depends on:** T041, T027
**Implements:** US-006
**Description:** Service worker polls `/tickets/fetch` on the configured interval (read from server settings, off by default). Badge text shows the Urgent count.
**Acceptance:**
- Interval set → badge updates after next poll.
- Interval off → no background calls.

## Phase 8 — Polish

### T043 — `GET /metrics` lightweight counters
**Depends on:** T028
**Implements:** plan §11
**Description:** In-process counters for `tickets_fetched_total`, `ai_calls_total{result}`, `cache_hits_total`, `overrides_set_total`, `proposals_created_total`, `proposals_resolved_total{resolution}`. Exposed as JSON.
**Acceptance:** Counters increment correctly across a fetch + a resolution.

### T044 — README + quickstart
**Depends on:** T005, T006, T029, T040
**Implements:** —
**Description:** Top-level README explaining: prerequisites (Python 3.11+, Node 18+, Chrome), how to get an Intercom token, how to get an OpenRouter key, how to populate `.env`, the three commands to run the three surfaces, and how to back up the SQLite file.
**Acceptance:** A fresh checkout brought up to a working board by following the README only.

## Phase 10 — Follow-ups, alarms, notes

### T045 — `followups` + `ticket_notes` tables + `settings.mute_alarms`
**Depends on:** T006
**Implements:** FR-019, FR-023, FR-024, plan §5
**Description:** Add two SQLAlchemy models (`Followup`, `TicketNote`) and a `mute_alarms` column on `Settings`. Length check on `Followup.reason` (≤ 80). `init_db` already idempotent — schema add lands via `create_all`; existing DBs need a one-time `ALTER TABLE settings ADD COLUMN mute_alarms BOOLEAN DEFAULT 0` (documented in the task PR; later schema changes graduate to Alembic per T104).
**Acceptance:**
- Fresh boot creates both tables.
- Existing DB after migration has the `mute_alarms` column with default 0.
- Inserting a `Followup` with a 100-char reason is rejected.

### T046 — Follow-up endpoints
**Depends on:** T045
**Implements:** FR-019, FR-022, US-012
**Description:** `GET /followups`, `PUT /followups/{ticket_id}`, `POST /followups/{ticket_id}/snooze` (`{minutes:int}`), `POST /followups/{ticket_id}/mark-fired`, `DELETE /followups/{ticket_id}`. PUT upserts; snooze recomputes `due_at = now + minutes` and clears `fired`.
**Acceptance:**
- PUT then GET returns the row.
- Snooze updates `due_at` and clears `fired`.
- mark-fired sets `fired=true` without touching `due_at`.
- DELETE removes the row; subsequent DELETE returns 200 (idempotent).

### T047 — Notes endpoints
**Depends on:** T045
**Implements:** FR-023, US-014
**Description:** `GET /notes`, `PUT /notes/{ticket_id}` (`{body:str}`). Empty body deletes the row and returns `{ok, deleted:true}`.
**Acceptance:**
- PUT with non-empty body → row stored.
- PUT with empty body → row gone.
- GET returns only non-empty rows.

### T048 — `/tickets/fetch` composes follow-up + note + mute
**Depends on:** T025, T046, T047
**Implements:** plan §8a
**Description:** Extend the `Ticket` response shape with `followup: Followup | null` and `note: TicketNote | null` joined from the two new tables by `ticket_id`. The `mute_alarms` flag is exposed through `GET /settings`.
**Acceptance:**
- Fetching a ticket with a stored follow-up returns the embedded record.
- Settings response carries `mute_alarms`.

### T049 — Webapp tokens + dark mode + accent picker
**Depends on:** T029
**Implements:** plan §8b
**Description:** CSS variables for the light + dark palettes per plan §8b. Geist + JetBrains Mono loaded from Google Fonts in `index.html`. Tweaks store persists dark mode, accent swatch, density, show-summary, show-confidence — server side via existing `settings` row (extended with these fields). Pulse / ring / slide keyframes injected once.
**Acceptance:**
- Toggling dark mode flips `<html data-theme>`.
- Picking an accent re-paints the page within one frame.

### T050 — Follow-up store + chip + pin-to-top
**Depends on:** T031, T046
**Implements:** US-012, FR-019, plan §8a
**Description:** Pinia `followupsStore` with `setFollowup`, `clearFollowup`, `snooze`, `markFired`. `TicketCard` renders the chip per plan §8b. Column-grouping sorter pins due tickets to the top.
**Acceptance:**
- Setting a follow-up via the flyout renders a chip immediately (optimistic).
- A due card sorts to the top of its column.

### T051 — Alarm loop + banner stack + mute
**Depends on:** T050, T027
**Implements:** US-013, FR-020, FR-021, FR-022, FR-024
**Description:** Once-per-second tick. On transition to due: push a banner record, play WebAudio ping unless `mute_alarms` is set, `POST .../mark-fired`. Banner exposes Open / Snooze 15 m / Snooze 1 h / Dismiss. Top-bar status pill shows pending count + flips to accent-pulse when at least one is firing.
**Acceptance:**
- Setting a +12 s follow-up triggers banner + audio at the right moment.
- Muting suppresses audio but not the banner.
- Snooze repositions the alarm; Dismiss leaves the row alone.

### T052 — Notes section in flyout
**Depends on:** T031, T047
**Implements:** US-014, FR-023
**Description:** Textarea bound to `PUT /notes/{ticket_id}` debounced 400 ms. Seven preset chips append `\n• <preset>` bullets. Card surface shows `Notes (N)` chip when body has non-empty lines.
**Acceptance:**
- Typing then waiting 400 ms persists.
- Emptying the textarea deletes the row server-side.

### T053 — Popup mirror — due banner + chip
**Depends on:** T041, T046
**Implements:** US-013 popup mirror
**Description:** Popup reads `GET /followups` on open, runs the same tick loop. Renders a due banner at the top when at least one follow-up is due. Each list row shows the countdown chip; due rows get a 2 px accent left-bar.
**Acceptance:**
- Opening the popup while a follow-up is due shows the banner.
- Closing + reopening preserves state.

## Phase 11 — Ticket resolution

### T054 — Alembic migration + SQLAlchemy model additions
**Depends on:** T006, T045
**Implements:** FR-025, FR-027, FR-029, FR-030, plan §8c
**Description:** Alembic migration `0006_add_ticket_resolution.py` adds `resolved_at`, `resolved_source`, `ai_resolve_enabled`, `resolution_chip_dismissed_at` to `tickets`; `ai_resolution_verdict`, `ai_resolution_confidence`, `ai_resolution_reason` to `ai_cache`; `ai_resolve_default`, `ai_resolve_confidence_threshold` to `settings`. SQLAlchemy models updated with the new mapped columns and check constraints.
**Acceptance:**
- [ ] Fresh DB has all new columns with correct defaults.
- [ ] Check constraint rejects `resolved_at` non-null with `resolved_source` null (and vice versa).
- [ ] Existing DB upgraded via migration retains prior data.

### T055 — Pydantic schemas: resolution fields + new request bodies
**Depends on:** T054
**Implements:** FR-025, FR-026, FR-027, FR-028, FR-029, FR-030
**Description:** Add `ResolvedSource`, `ResolutionVerdict`, `ResolutionChipState` literals. Extend `TicketSchema` with seven resolution fields. Add `AIResolveSet`, `ResolveResponse`, `ReopenResponse`. Extend `FilterSettings` with `ai_resolve_default` + `ai_resolve_confidence_threshold`.
**Acceptance:**
- [ ] `TicketSchema` validates with all resolution fields present or absent.
- [ ] `AIResolveSet` accepts `true`, `false`, and `null`.
- [ ] `FilterSettings` rejects `ai_resolve_confidence_threshold` outside `[0, 1]`.

### T056 — AI prompt + parser carry resolution verdict
**Depends on:** T013, T055
**Implements:** FR-027, plan §7
**Description:** Extend `SYSTEM_PROMPT` with RESOLUTION rules and add the three resolution fields to all three JSON response shapes (existing, pending_proposal, new_proposal). Extend `ParsedAssignment` and `parse_response` to extract, validate, and clamp `resolution_verdict`, `resolution_confidence`, `resolution_reason`.
**Acceptance:**
- [ ] System prompt contains all three resolution field names.
- [ ] Parser correctly extracts verdict + confidence + reason from a complete response.
- [ ] Missing resolution fields parse to `None` without error.
- [ ] Invalid verdict (e.g. `"maybe"`) clamps to `None`.
- [ ] Reason longer than 120 chars is truncated to 120.

### T057 — `CategorizationResult` + resolver carry resolution
**Depends on:** T056
**Implements:** FR-027, plan §7
**Description:** Add three resolution fields to `CategorizationResult`. Thread them from `ParsedAssignment` through every branch of `resolve()`. `_fallback()` leaves them `None` by default.
**Acceptance:**
- [ ] `resolve()` propagates all three fields from `ParsedAssignment` to `CategorizationResult`.
- [ ] Fallback path returns `None` for all three resolution fields.

### T058 — AI cache reads/writes resolution fields
**Depends on:** T054, T057
**Implements:** FR-027, FR-008
**Description:** Update `set_cached` to persist the three resolution fields; update `get_cached` to return them. Legacy rows with null fields round-trip without crashing.
**Acceptance:**
- [ ] Cache write + read preserves verdict, confidence, and reason.
- [ ] A row inserted without resolution fields returns `None` for all three on read.

### T059 — `_upsert_ticket` auto-resolves on Intercom open→closed transition
**Depends on:** T054, T057
**Implements:** FR-026, US-017
**Description:** Modify `_upsert_ticket` in `services/tickets.py` so that when a stored ticket with `resolved_at IS NULL` arrives with `state='closed'`, it stamps `resolved_at = now()` and `resolved_source = 'intercom_closed'`. Second and subsequent closed-state syncs do not re-stamp `resolved_at`.
**Acceptance:**
- [ ] First sync open → second sync closed stamps `resolved_at` + `resolved_source`.
- [ ] Already-resolved ticket's `resolved_at` is unchanged on a subsequent closed sync.
- [ ] No AI call is triggered by the closure event.

### T060 — `services/resolution.py` — manual resolve / reopen / AI toggle / dismiss
**Depends on:** T054
**Implements:** FR-025, FR-026, FR-028, FR-029
**Description:** Create `backend/app/services/resolution.py` with four async functions: `resolve` (stamps `resolved_at + source='manual'`, 409 if already resolved), `reopen` (clears both fields, 409 if not resolved), `set_ai_resolve` (writes nullable tri-state), `dismiss_chip` (sets `resolution_chip_dismissed_at = row.updated_at`). All raise 404 for unknown ticket ids.
**Acceptance:**
- [ ] `resolve` sets correct fields; 409 on double-resolve.
- [ ] `reopen` clears fields; 409 on open ticket.
- [ ] `set_ai_resolve` persists `True`, `False`, and `None`.
- [ ] `dismiss_chip` stamps `resolution_chip_dismissed_at` equal to `updated_at`.
- [ ] All four raise 404 for unknown ticket ids.

### T061 — Resolution endpoints + router wiring
**Depends on:** T055, T060
**Implements:** FR-028, US-015, US-016
**Description:** Add four routes to `backend/app/routers/tickets.py`: `POST /{id}/resolve`, `POST /{id}/reopen`, `PATCH /{id}/ai-resolve`, `POST /{id}/dismiss-chip`. Wire to `resolution_svc`.
**Acceptance:**
- [ ] `POST /tickets/t1/resolve` returns 200 with `resolved_source='manual'`.
- [ ] 404 for unknown id on all four routes.
- [ ] 409 on double-resolve and on reopening an open ticket.

### T062 — `GET /tickets` resolved filter + chip-state computation + drag-out reopen
**Depends on:** T055, T058, T060, T061
**Implements:** FR-025, FR-027, FR-028, US-015, US-016
**Description:** Extend `services/tickets.get_tickets` with a `resolved` parameter (`False` = exclude resolved [default], `True` = only resolved, `None` = both). Compute `resolution_chip_state` server-side using the `_chip_state` helper per §8c. Extend `set_override` to atomically clear resolution when dragging a resolved ticket into a category column.
**Acceptance:**
- [ ] Default `GET /tickets` excludes resolved tickets.
- [ ] `GET /tickets?resolved=true` returns only resolved tickets, sorted by `resolved_at` desc.
- [ ] Chip state is `ai_resolved` when verdict='resolved', confidence ≥ threshold, ticket is open, and chip not dismissed.
- [ ] `PATCH /tickets/{id}/category` on a resolved ticket clears `resolved_at` + `resolved_source`.

### T063 — Settings endpoint carries `ai_resolve_default` + threshold
**Depends on:** T055, T062
**Implements:** FR-030, US-016
**Description:** Update `services/settings.py` and `routers/settings.py` so `GET /settings` returns `ai_resolve_default` and `ai_resolve_confidence_threshold`, and `PUT /settings` persists them.
**Acceptance:**
- [ ] `GET /settings` fresh DB returns `ai_resolve_default=false`, threshold `0.7`.
- [ ] `PUT /settings` with valid payload persists both fields.
- [ ] `PUT /settings` with threshold `> 1.0` returns 422.

### T064 — TypeScript types + API client
**Depends on:** T063
**Implements:** FR-025, FR-027, FR-028, FR-029, FR-030
**Description:** Extend `webapp/src/types/api.ts` with `ResolvedSource`, `ResolutionVerdict`, `ResolutionChipState` types and the seven new `Ticket` fields and two new `FilterSettings` fields. Add `resolveTicket`, `reopenTicket`, `setAiResolve`, `dismissChip`, and updated `listTickets` to `webapp/src/api/client.ts`.
**Acceptance:**
- [ ] TypeScript compilation passes with no new `any`s.
- [ ] `listTickets({ resolved: true })` appends `?resolved=true` to the request.

### T065 — Tickets store — `resolvedTickets` + actions
**Depends on:** T064
**Implements:** US-015, US-016, FR-025, FR-028
**Description:** Add `resolvedTickets` ref to `ticketsStore`. Add `refreshResolved`, `markResolved`, `reopen`, `setAiResolve`, `dismissChip` actions with optimistic updates and rollback on failure. Extend `refresh` + `silentRefresh` to fetch both lists in parallel. Extend `applyOverride` to move resolved tickets back to open when overriding.
**Acceptance:**
- [ ] `markResolved` moves ticket from `tickets` to `resolvedTickets` optimistically; rolls back on API failure.
- [ ] `reopen` moves ticket from `resolvedTickets` to `tickets` optimistically; rolls back on API failure.
- [ ] `dismissChip` sets `resolution_chip_state` to `null` locally.

### T066 — `ResolvedColumn` + Board integration
**Depends on:** T065
**Implements:** US-015, FR-025, FR-028
**Description:** Create `webapp/src/components/ResolvedColumn.vue` — always-visible column sourced from `resolvedTickets`, accepts drops from category columns (calls `markResolved`), allows drag-out to category columns (handled by receiving column's `applyOverride`). Integrate into `Board.vue` as the rightmost column.
**Acceptance:**
- [ ] Resolved column renders regardless of `include_category_ids` setting.
- [ ] Dragging an open ticket into the Resolved column resolves it immediately.
- [ ] Dragging a resolved ticket into a category column reopens + overrides it.

### T067 — `TicketCard` — resolve icon + `ResolutionChip`
**Depends on:** T065, T066
**Implements:** US-015, US-016, FR-027
**Description:** Add a ✓ icon to `TicketCard` that calls `markResolved` / `reopen` depending on current state. Create `ResolutionChip.vue` — advisory chip rendered on a card when `resolution_chip_state` is non-null. Clicking the chip applies the suggestion; a dismiss (×) button hides it.
**Acceptance:**
- [ ] ✓ icon resolves open tickets; on resolved cards the icon reopens.
- [ ] Chip renders only when `resolution_chip_state` is set; click applies suggestion; dismiss calls `dismissChip`.

### T068 — Flyout — resolution section + AI tri-state toggle
**Depends on:** T065
**Implements:** US-015, US-016, FR-029
**Description:** Add a *Resolution* section to `TicketFlyout.vue` with a "Mark resolved" / "Reopen" button and an AI tri-state toggle (`Auto` / `On` / `Off`) that calls `setAiResolve`.
**Acceptance:**
- [ ] "Mark resolved" button resolves the ticket; changes to "Reopen" on resolved tickets.
- [ ] AI toggle cycles through `null` / `true` / `false` and persists via `PATCH /tickets/{id}/ai-resolve`.

### T069 — Settings drawer — Auto-resolve section
**Depends on:** T063, T064
**Implements:** FR-030, US-016
**Description:** Add an *Auto-resolve* section to `SettingsDrawer.vue` with a global enable toggle (`ai_resolve_default`) and a confidence threshold slider / input (`ai_resolve_confidence_threshold`). Reads/writes via `PUT /settings`.
**Acceptance:**
- [ ] Toggle and slider persist after page reload.
- [ ] Threshold input rejects values outside `[0, 1]` before submitting.

### T070 — Extension closure pass
**Depends on:** T059
**Implements:** US-017, FR-031
**Description:** Extend the extension sync flow with a closure pass: diff tracked ticket ids against the open list; for any ids no longer present, fetch them from Intercom's closed-conversation list and POST them to `POST /tickets/fetch` so `_upsert_ticket` stamps `resolved_at`. Modify `extension/api.js`, `extension/intercom.js`, and `extension/background.js`.
**Acceptance:**
- [ ] A ticket tracked as open that Intercom now reports as closed appears as resolved after the next sync.
- [ ] The closure pass does not trigger an AI categorization call.

### T071 — Extension popup — Resolved tab + resolve action
**Depends on:** T070
**Implements:** US-015, US-017
**Description:** Add a *Resolved* tab to the extension popup that renders resolved tickets from `GET /tickets?resolved=true`. Add a resolve/reopen action button per card. Modify `extension/popup.js` and `extension/popup.css`.
**Acceptance:**
- [ ] Resolved tab lists resolved tickets sorted most-recently-resolved first.
- [ ] Resolve action on an open card moves it to the Resolved tab immediately.

### T072 — Docs — `spec.md`, `plan.md`, `tasks.md`
**Depends on:** T054
**Implements:** US-015, US-016, US-017, FR-025..FR-031
**Description:** Add US-015/016/017 and FR-025..FR-031 to `spec.md`; add §8c and schema additions to `plan.md`; add Phase 11 entries to `tasks.md`. Update version headers and traceability matrix.
**Acceptance:**
- [ ] Every new FR is referenced by at least one task in the traceability matrix.
- [ ] Version headers in all three docs advance to v1.4.

### T073 — Quality gates pass on main
**Depends on:** T054, T055, T056, T057, T058, T059, T060, T061, T062, T063, T064, T065, T066, T067, T068, T069, T070, T071, T072
**Implements:** NFR-001, NFR-002, NFR-003
**Description:** All backend tests pass (`pytest`). Webapp typechecks clean (`tsc --noEmit`). Vitest suite green. Extension loads without warnings in Chrome. End-to-end smoke: resolve a ticket manually, verify it appears in Resolved column on both webapp and popup, reopen it, verify it returns to its category column.
**Acceptance:**
- [ ] `pytest` exits 0.
- [ ] `npm run typecheck` exits 0 in `webapp/`.
- [ ] Extension side-loads without manifest errors.
- [ ] Manual smoke test passes for all three resolution paths (manual, AI chip, Intercom-closed).

## Phase 9 — Backlog

- **T100** — Webhook subscription on `conversation.user.created`/`conversation.user.replied`; push channel (SSE) to webapp and extension.
- **T102** — Token / cost meter surfacing OpenRouter spend per day.
- **T103** — Multi-user expansion: add a `users` table + simple session cookie auth + per-user overrides and settings. Path back to v1.1 architecture.
- **T104** — Alembic migrations: introduce when the first schema change is needed beyond `create_all`.

---

## Traceability matrix

Every requirement maps to at least one task.

| Requirement | Implementing tasks |
|---|---|
| FR-001 | T009, T025 |
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
| FR-031 | T070 |

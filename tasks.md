# Intercom Triage — Tasks

**Status:** ready · **Version:** 1.3 · **Implements:** `spec.md` v1.3, `plan.md` v1.3

Each task is a single PR. Every task lists what spec requirement it implements and what other tasks must merge first.

**Conventions.**
- `[P]` next to a task ID means it may run in parallel with siblings at the same dependency depth.
- `Implements:` links to FR-xxx, NFR-xxx, US-xxx (from `spec.md`) or plan §x (from `plan.md`).
- `Depends on:` lists task IDs that must be merged first.
- Acceptance criteria are testable — write the test before the code.

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

## Phase 9 — Backlog

- **T100** — Webhook subscription on `conversation.user.created`/`conversation.user.replied`; push channel (SSE) to webapp and extension.
- **T101** — Per-category Slack hook (Urgent → `#support-urgent`).
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

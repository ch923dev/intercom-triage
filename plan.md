# Intercom Triage — Technical Plan

**Status:** ready · **Version:** 1.7 · **Implements:** `spec.md` v1.7 · **Sibling docs:** `spec.md`, `tasks.md`

This document defines **how** the system is built. Each section maps back to one or more spec requirements. Tasks in `tasks.md` reference both spec IDs and plan sections.

**Changes from v1.5:** reconciliation backfill matching `spec.md` v1.7. Adds §15 (AI reliability — structured outputs, model cascade, needs-review lane), §16 (local embedding layer + few-shot + RAG draft replies), §17 (recurring-issue insights — clustering, playbook-gap, auto-match), §18 (operator throughput & analytics — triage facets, aging, keyboard, saved views, priority sort, stats, cost meter, snippets, bulk pre-flight). Also folds in the §13 (Playbooks) and §14 (Parked) sections that had been appended without a version bump, and **corrects three now-false facts** in §1/§5/§12: the project uses **Alembic** (forward-only migrations), not `metadata.create_all`, and the data model has grown well past six tables. The §11 observability note is updated to match the shipped stdlib-logging + latency-histogram + cost-meter reality.

**Changes from v1.4:** added §8d (bulk actions): a transient client-side selection store, five `bulk` endpoints that loop per-id over the existing services and return per-id success/failure, an `<BulkActionBar>` surface in the webapp, range-select within column, bulk drag through `vuedraggable`'s multi-drag mode, and a `MAX_BULK_IDS` cap. No schema additions.

**Changes from v1.3:** added §8c (ticket resolution): orthogonal resolved flag on `tickets`, four new endpoints, server-computed chip state, AI verdict bundled into the existing categorization call, extension closure pass. Schema additions documented in §5.

**Changes from v1.2:** added two persistence tables (`followups`, `ticket_notes`), the matching endpoints, the front-end alarm loop spec, and the design-system tokens lifted from `Intercom Triage.html`. Category seed colors converted to **oklch** to match the design palette.

**Changes from v1.1:** all cloud and auth infrastructure removed. SQLite replaces Cloud SQL Postgres. KMS removed (Intercom token in `.env`). Identity Platform / OAuth removed (no users, no JWT verification). Alembic dropped in favor of SQLAlchemy `create_all` on startup. Backend is a single-process FastAPI on `localhost`.

---

## 1. Stack decisions

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11+, FastAPI | Matches Christian's existing stack |
| HTTP client | `httpx` (async) | Standard async client |
| Config | `pydantic-settings` reading `.env` | Existing pattern |
| Database | SQLite (default), via SQLAlchemy 2.0 async (`aiosqlite` driver) | Zero-setup, single file, ships with Python. Postgres swap is a one-line URL change. |
| Schema management | **Alembic** (forward-only migrations) + seeding on startup, run by `init_db` | Adopted once the schema started changing (see §12). `metadata.create_all` is used only for the in-memory test DB / schema smoke. |
| Webapp | Vue 3 + Vite + TypeScript | Matches OnlySales frontend |
| Client state | Pinia | Standard Vue 3 |
| Drag-and-drop | `vuedraggable@next` (multi-drag for bulk) | Vue 3 compatible |
| Webapp tests | Vitest + Vue Test Utils + happy-dom | Lands with Phase 12 bulk-actions |
| Extension | Manifest V3 + vanilla TypeScript | Keeps popup bundle small |
| AI gateway | OpenRouter | Single contract for Anthropic models |
| AI model (default) | `anthropic/claude-sonnet-4.5` | Quality default |
| AI model (cost mode) | `anthropic/claude-haiku-4.5` | Configurable via `.env` |
| Deploy | `uvicorn main:app` on localhost; webapp via `npm run dev` or static build; extension side-loaded | No cloud, no Docker required |
| Secrets | `.env` file (gitignored) | NFR-005 |
| Bulk request cap | `MAX_BULK_IDS` (default 200) | Caps memory + transaction size per bulk call (FR-036) |

## 2. Architecture

Three components. All run locally; backend listens on `localhost` only.

The **backend** is a FastAPI service. It owns the AI integration, the SQLite persistence layer, and the public API surface. Reads its OpenRouter key from `.env`. The backend does NOT call Intercom directly — the extension owns Intercom access via the operator's browser session.

The **webapp** is a Vue 3 SPA. It calls the backend at `http://localhost:<port>`. Owns the Kanban UI, drag-and-drop, settings UI, category admin pages, proposals review queue, and the extension-discovery callout.

The **Chrome extension** is a Manifest V3 extension. It owns Intercom access — scrapes conversations from the logged-in `app.intercom.com` session, strips HTML, and pushes them to the backend. Also calls the localhost backend for the popup mini-board (full taxonomy as column tabs, override-capable), optional background polling, badge, and "Open full board" handoff.

Ingest data flow: extension calls `GET /tickets/sync-state` to read `{id: updated_at}` for stored tickets → walks the operator's Intercom inbox via the ember endpoints → fetches detail only for changed/new conversations → strips HTML (FR-003) → `POST /tickets/ingest` with hydrated conversations → backend checks the AI cache (FR-008); on miss, calls OpenRouter with a prompt built from the current taxonomy → resolves AI output into either an existing category id, an existing pending proposal id, or a newly-created proposal (FR-015) → stores. Reads: `GET /tickets` serves the stored board with overrides applied (FR-009) and sorted (FR-013).

## 3. Data contracts

```text
Ticket {                                  # server → client
  id:             string
  title:          string | null
  state:          "open" | "closed" | "snoozed" | null
  priority:       string | null
  created_at:     ISO8601
  updated_at:     ISO8601
  author:         TicketAuthor
  url:            string | null            # FR-010
  parts:          ConversationPart[]
  category_id:    int | null               # exactly one of category_id / proposal_id is set
  proposal_id:    int | null
  summary:        string                   # FR-005, ≤ 280 chars
  ai_confidence:  float                    # FR-006, [0, 1]
  user_override:  boolean                  # FR-009
  ai_priority:    "low"|"normal"|"high"|"urgent" | null   # FR-043; null on pre-0.2 rows
  ai_sentiment:   "negative"|"neutral"|"positive" | null  # FR-043
  ai_labels:      string[]                 # FR-043; [] default
  # resolution_* (§8c), parked_* (§14) also ride on this shape — see those sections.
}

Category {
  id:           int
  name:         string
  description:  string                     # used in the AI prompt
  color:        string                     # hex, for UI
  sort_order:   int
  is_active:    boolean
  is_fallback:  boolean                    # exactly one row; non-archivable
  source:       "seed" | "ai_proposed" | "user_created"
}

CategoryProposal {
  id:                  int
  name:                string
  description:         string
  example_ticket_ids:  string[]            # up to 5
  status:              "pending" | "approved" | "merged" | "rejected"
  resolved_category_id: int | null
  created_at:          ISO8601
  resolved_at:         ISO8601 | null
}

TicketAuthor     { id, name, email, type }
ConversationPart { author, body, created_at }

FilterSettings {
  lookback_unit:        "hours" | "days"
  lookback_value:       int                # 1..720
  states:               ("open" | "snoozed" | "closed")[]
  include_category_ids: int[] | null       # null = all active + pending proposals
}

CategoryUpdate { category_id: int }        # PATCH override body

Followup {                                 # server ↔ client (US-012, US-013)
  ticket_id: string
  due_at:    ISO8601
  reason:    string | null                 # ≤ 80 chars
  fired:     boolean                       # set true once the alarm has rung
  created_at: ISO8601
  updated_at: ISO8601
}

FollowupSet {                              # PUT body
  due_at: ISO8601                          # absolute; client computes from preset minutes
  reason: string | null
}

TicketNote {                               # server ↔ client (US-014)
  ticket_id: string
  body:      string
  updated_at: ISO8601
}

TicketNoteSet { body: string }             # PUT body; empty string deletes the row

BulkTicketIds       { ticket_ids: string[] }                    # universal bulk request envelope
BulkCategoryUpdate  { ticket_ids: string[], category_id: int }
BulkFollowupSet     { ticket_ids: string[], due_at: ISO8601, reason: string | null }
BulkResult {                                # universal bulk response envelope
  ok_ids:  string[]
  failed:  { id: string, reason: string }[]
}
```

## 4. API contract

No auth header. Backend listens on `127.0.0.1` only.

| Method | Path | Body | Response | Implements |
|---|---|---|---|---|
| GET | `/health` | — | service status, model id | — |
| GET | `/categories` | — | active categories + pending proposals | FR-004, FR-018 |
| POST | `/categories` | `{name, description, color, sort_order}` | new Category | FR-017 |
| PATCH | `/categories/{id}` | partial Category | updated Category | FR-017 |
| POST | `/categories/{id}/archive` | — | `{ok}` | FR-017 |
| POST | `/categories/{src}/merge-into/{dst}` | — | `{ok, moved_count}` | FR-017 |
| GET | `/proposals` | — | pending proposals + example tickets | US-010 |
| POST | `/proposals/{id}/approve` | optional `{color, sort_order}` | resulting Category | FR-016 |
| POST | `/proposals/{id}/merge-into/{category_id}` | — | `{ok, moved_count}` | FR-016 |
| POST | `/proposals/{id}/reject` | — | `{ok}` | FR-016 |
| POST | `/tickets/ingest` | `HydratedTicket[]` (from extension) | `{received, categorized}` | FR-001, FR-004, FR-005, FR-006, FR-008, FR-011, FR-013 |
| GET | `/tickets/sync-state` | — | `{ticket_id: updated_at}` | FR-001 |
| PATCH | `/tickets/{id}/category` | `CategoryUpdate` | `{ok, category_id}` | FR-009 |
| PATCH | `/tickets/{id}` | `TicketEdit` | `{ok}` | FR-009 |
| GET | `/settings` | — | stored `FilterSettings` + `mute_alarms` | FR-012, FR-024 |
| PUT | `/settings` | `FilterSettings` + `mute_alarms` | stored settings | FR-012, FR-024 |
| GET | `/followups` | — | all active follow-ups (one row per ticket) | FR-019 |
| PUT | `/followups/{ticket_id}` | `FollowupSet` | stored `Followup` | FR-019, FR-022 |
| POST | `/followups/{ticket_id}/snooze` | `{minutes:int}` | stored `Followup` | FR-022 |
| POST | `/followups/{ticket_id}/mark-fired` | — | `{ok}` | FR-021 |
| DELETE | `/followups/{ticket_id}` | — | `{ok}` | US-012 |
| GET | `/notes` | — | all non-empty `TicketNote[]` | FR-023 |
| PUT | `/notes/{ticket_id}` | `TicketNoteSet` | stored `TicketNote` or `{ok, deleted:true}` | FR-023 |
| GET | `/tickets` | `?resolved=true\|false` | `Ticket[]` (default excludes resolved) | FR-028 |
| POST | `/tickets/{id}/resolve` | — | `{ok, resolved_at, resolved_source}` | FR-025, FR-026, FR-028 |
| POST | `/tickets/{id}/reopen` | — | `{ok}` | FR-025, FR-028 |
| PATCH | `/tickets/{id}/ai-resolve` | `{enabled: bool\|null}` | `{ok}` | FR-029, FR-028 |
| POST | `/tickets/{id}/dismiss-chip` | — | `{ok}` | FR-027, FR-028 |
| POST | `/tickets/bulk/resolve` | `BulkTicketIds` | `BulkResult` | FR-033, US-018 |
| POST | `/tickets/bulk/reopen` | `BulkTicketIds` | `BulkResult` | FR-033, US-018 |
| PATCH | `/tickets/bulk/category` | `BulkCategoryUpdate` | `BulkResult` | FR-033, US-018 |
| POST | `/tickets/bulk/dismiss-chip` | `BulkTicketIds` | `BulkResult` | FR-033, US-018 |
| PUT | `/followups/bulk` | `BulkFollowupSet` | `BulkResult` | FR-033, US-018 |
| DELETE | `/followups/bulk` | `BulkTicketIds` | `BulkResult` | FR-033, US-018 |
| GET | `/stats` | `?window_days=N` | `StatsResponse` | FR-049 |
| GET | `/snippets` | `?include_archived` | `SnippetRead[]` | FR-051 |
| POST | `/snippets` | `SnippetCreate` | `SnippetRead` | FR-051 |
| PATCH | `/snippets/{id}` | `SnippetUpdate` | `SnippetRead` | FR-051 |
| POST | `/snippets/{id}/archive` · `/restore` | — | `{ok}` | FR-051 |
| GET | `/clusters` | — | `ClusterRead[]` | FR-059 |
| GET | `/clusters/gaps` | — | `ClusterGapRead[]` | FR-060 |
| POST | `/clusters/recompute` | — | `ClusterRead[]` | FR-059 |
| GET | `/playbooks/suggested` | `?ticket_id` | `SuggestedPlaybook[]` | FR-061 |
| POST | `/playbooks/draft-reply` | `PlaybookDraftRequest` | `DraftReplyResponse` | FR-058 |

> The table above is the contract spine, not the full surface — the playbooks
> CRUD/draft, non-actionable, park/unpark, notes, note-entries, and attachments
> endpoints are documented in their own plan sections (§13, §14) and the README
> API table. `GET /health` also exposes `review_confidence_threshold` (FR-055).

Error contract: `502` on upstream AI failure, `422` on schema violation (including bulk requests over `MAX_BULK_IDS`), `404` on unknown id, `409` on archive of fallback or other invalid state transition. Bulk endpoints never abort the batch on a per-id failure — they record `{id, reason}` in `failed[]` and return 200.

## 5. Data model

SQLAlchemy 2.0 declarative models in `backend/app/models.py`; the schema is created and migrated by **Alembic** (forward-only revisions in `backend/alembic/versions/`, run by `init_db` on boot — `upgrade head`, or `stamp head` on a pre-Alembic DB), then seeded if empty. The model has grown well past the original six tables (now ~16, including `followups`, `ticket_notes`, `note_entries`, `note_attachments`, `playbooks`, `snippets`, `ticket_embeddings`, `ticket_clusters` / `ticket_cluster_members`); the core tables below remain the contract spine, and §13–§18 document the additions. The `metadata.create_all` path survives only for the in-memory test DB and the `python -m app.models` schema smoke.

```text
categories
  id              integer pk
  name            text not null
  description     text not null
  color           text
  sort_order      int default 0
  is_active       boolean default true
  is_fallback     boolean default false
  source          text check (source in ('seed','ai_proposed','user_created'))
  created_at      datetime default now
  archived_at     datetime
  -- partial unique (name) where is_active
  -- partial unique (is_fallback) where is_fallback     (singleton fallback)

category_proposals
  id                  integer pk
  name                text not null
  description         text not null
  example_ticket_ids  json default '[]'
  status              text default 'pending' check (status in ('pending','approved','merged','rejected'))
  resolved_category_id integer fk → categories(id) on delete set null
  created_at          datetime default now
  resolved_at         datetime
  -- partial unique (name) where status = 'pending'

ai_cache
  ticket_id           text pk
  category_id         integer fk → categories(id) on delete cascade   nullable
  proposal_id         integer fk → category_proposals(id) on delete cascade   nullable
  summary             text not null
  confidence          real not null
  ticket_updated_at   datetime not null
  cached_at           datetime default now
  ai_resolution_verdict     text                              -- 'resolved' | 'not_resolved' | null
  ai_resolution_confidence  real                              -- [0,1] | null
  ai_resolution_reason      text                              -- ≤ 120 chars | null
  -- check: exactly one of category_id, proposal_id is set

overrides
  ticket_id    text pk
  category_id  integer not null fk → categories(id) on delete cascade
  set_at       datetime default now

settings
  id                              integer pk check (id = 1)        -- singleton row
  lookback_unit                   text default 'hours' check in ('hours','days')
  lookback_value                  int default 24 check between 1 and 720
  states                          json default '["open"]'
  include_category_ids            json                              -- null = all
  updated_at                      datetime default now
  ai_resolve_default              boolean default false
  ai_resolve_confidence_threshold real default 0.7 check between 0.0 and 1.0

rejected_proposal_signatures
  signature      text pk
  rejected_name  text not null
  rejected_at    datetime default now

followups
  ticket_id   text pk
  due_at      datetime not null
  reason      text                          -- ≤ 80 chars; CHECK length(reason) <= 80
  fired       boolean default false
  created_at  datetime default now
  updated_at  datetime default now

ticket_notes
  ticket_id   text pk
  body        text not null                 -- non-empty; empty body deletes the row
  updated_at  datetime default now
```

Settings additions for FR-024:

```text
settings.mute_alarms  boolean default false       -- column added to the existing singleton
```

Schema additions for §8c (FR-025..FR-031):

```text
tickets (resolution columns — added via Alembic 0006):
  resolved_at                   datetime                          -- null = open
  resolved_source               text                              -- 'manual' | 'intercom_closed' | 'non_actionable' | 'ai_resolved' | null
  ai_resolve_enabled            boolean nullable                  -- null = inherit settings default
  resolution_chip_dismissed_at  datetime                          -- null = chip not dismissed
  -- check: (resolved_at IS NULL) = (resolved_source IS NULL)
  -- check: resolved_source IN ('manual','intercom_closed','non_actionable','ai_resolved') or null
  --        (widened by migrations 0010 non_actionable, 0012 ai_resolved)
  -- index: ix_tickets_resolved_at (partial, where resolved_at IS NOT NULL)

ai_cache (resolution columns — same migration):
  ai_resolution_verdict     text    -- 'resolved' | 'not_resolved' | null
  ai_resolution_confidence  real    -- [0,1] | null
  ai_resolution_reason      text    -- ≤ 120 chars | null

settings (resolution columns — same migration):
  ai_resolve_default              boolean default false
  ai_resolve_confidence_threshold real default 0.7 check between 0.0 and 1.0
```

Behavioral notes. `ai_cache` enforces "exactly one of `category_id`, `proposal_id`" via a check constraint — this matches the AI output resolver (§7). Foreign keys cascade so that when a category or proposal is hard-deleted, dependent cache rows go with it. `overrides` cascades from category too. The `settings` table is a singleton via `CHECK (id = 1)`; the app inserts the row at first startup. Partial unique indexes prevent two active categories or two pending proposals from sharing a name, while letting archived/resolved rows reuse names. `followups` and `ticket_notes` are keyed by `ticket_id` only — no FK because the ticket id is owned by Intercom, not this DB; rows are deleted when the operator clears the follow-up or empties the notes; `GET /tickets` joins both in by ticket id when composing the response.

## 6. Intercom integration

The operator has no Intercom API token. The Chrome extension scrapes
conversations from the logged-in `app.intercom.com` session — workspace
`j3dxf22l` via the internal `ember/` endpoints — strips HTML, and pushes
hydrated conversations to the backend via `POST /tickets/ingest`. The extension
first calls `GET /tickets/sync-state` to skip unchanged conversations
(NFR-003). Deep links resolve client-side: the extension already knows the
workspace id from the session URL. The backend owns categorization + storage
only; no upstream HTTP call to Intercom from the server.

## 7. AI specification

OpenRouter `/chat/completions`, OpenAI-compatible. Headers: `Authorization`, `HTTP-Referer`, `X-Title`. Model from `OPENROUTER_MODEL` env.

Request shape: `model`, `messages=[system,user]`, `temperature=0.1`, `max_tokens=400`, `response_format={type:"json_object"}`.

The prompt builder is in `backend/app/ai/prompt.py`. It assembles the user message from the current active categories, pending proposals, and rejected-name list, plus the ticket's title, state, and transcript (≤ 6000 chars, middle-truncated).

The AI returns one of three assignment shapes (see prompt builder for the strict JSON contract):
- `existing` — pick a current active category id
- `pending_proposal` — reuse one of the pending proposals listed in the prompt
- `new_proposal` — propose a new category name and description

**Output resolution** (server-side):
- `existing` → validate the id exists and is active; cache with `category_id`.
- `pending_proposal` → validate the id is pending; cache with `proposal_id`.
- `new_proposal` → normalize `proposed_name` (trim, title-case, lowercase-hash). If the hash exists in `rejected_proposal_signatures` → fall back. If a pending proposal with the same hash exists → reuse it. Otherwise insert a new `category_proposals` row and cache against it.

**Concurrency:** `asyncio.Semaphore(AI_CONCURRENCY)` (default 4).

**Fallback (FR-007):** any exception, parse failure, invalid id, or schema violation yields `(category_id = fallback, summary = title[:280], confidence = 0.0)`. The batch never fails.

**Cache (FR-008):** keyed by `ticket_id` (no tenant qualifier now). Invalid if `cached_at + TTL < now` OR `incoming.ticket_updated_at > cached.ticket_updated_at`. TTL configurable, default 5 min.

## 8. Category management

**Seeding.** On first startup, if the `categories` table is empty, seven defaults are inserted with `source=seed`: Urgent, Bug, Feature Request, Question, Billing, Complaint, Other. "Other" is marked `is_fallback=true`. The singleton `settings` row is also inserted at first startup.

**Proposal lifecycle.** `pending` → (`approved` | `merged` | `rejected`).
- **Approve:** mark proposal approved, create a new `categories` row with `source=ai_proposed`, set `resolved_category_id`. Repoint cache rows: `UPDATE ai_cache SET category_id=<new>, proposal_id=NULL WHERE proposal_id=<id>`.
- **Merge into existing:** mark proposal merged with `resolved_category_id=<target>`. Same cache repoint to the target.
- **Reject:** mark proposal rejected with `resolved_category_id=<fallback>`. Repoint cache rows to fallback. Insert normalized signature into `rejected_proposal_signatures` so the AI doesn't re-propose the same name.

**Active-category mutations.** Rename/recolor/reorder are in-place; ids stable. Archive sets `is_active=false, archived_at=now()` and runs an inline sweep that repoints `ai_cache.category_id` and `overrides.category_id` from the archived category to the fallback. Merging A → B updates all `ai_cache` and `overrides` rows from A to B and archives A. All multi-row updates run in a single transaction.

## 8a. Follow-ups, alarms, notes

**Persistence.** Both `followups` and `ticket_notes` are upserts keyed by `ticket_id`. The `PUT /followups/{ticket_id}` endpoint accepts an absolute `due_at` — the client computes the timestamp from preset minutes (`+15m`, `+1h`, `+4h`, `+EOD`, `+24h`) so server clock and client clock stay in sync at the moment the operator sets it. Empty `body` on `PUT /notes/{ticket_id}` deletes the row (idempotent if already absent).

**Server-side alarm role:** none. The backend is a passive store; alarm evaluation runs in each client surface. This keeps the backend stateless wrt timing and lets the popup raise alarms even when the webapp isn't open.

**Client alarm loop** (webapp + popup):
1. On open, `GET /followups` to populate state; `GET /settings.mute_alarms` to read the mute flag.
2. Tick once per second. For each follow-up not yet `fired` with `due_at ≤ now`:
   - Push a banner record into a local stack.
   - If `mute_alarms` is false, play a short WebAudio two-note ping (700 ms, 880 → 1175 Hz). The audio object is created on the first user interaction (browser autoplay policy).
   - `POST /followups/{ticket_id}/mark-fired` so subsequent reloads don't re-ring the same alarm.
3. **Pin-to-top:** when grouping tickets by category, due (`due_at ≤ now`) tickets sort before others within the same column.
4. **Snooze:** `POST /followups/{ticket_id}/snooze` with `{minutes}`. Server resets `due_at` and clears `fired`.
5. **Dismiss:** purely client-side; banner record drops, follow-up row keeps `fired=true`.

**Card surfaces.** A non-due follow-up renders as a `F/U in 15m` chip in mono. A due follow-up renders as `Follow up · due now` with an accent border and a 0.5 px outer ring (`0 0 0 4px rgba(255,77,46,.08)`). A non-empty note renders as a `Notes (N)` chip where N is `body.split('\n').filter(Boolean).length`.

**Flyout surfaces.** A *Follow-up* section with preset chips + a *Clear* action. A *Next steps* section with the seven preset action chips that append `\n• <preset>` into the textarea, plus the freeform textarea bound to `PUT /notes/{ticket_id}` debounced 400 ms.

## 8b. Design system

Lifted from the canonical design at `design_bundle/intercom-ticket-management-with-ai-categorization/project/`. Webapp + popup must match.

**Type:** Geist (400/500/600/700) for prose, JetBrains Mono (400/500/600) for labels, ids, counts, deltas. Loaded from Google Fonts in `index.html`.

**Color tokens (light):**

```text
--bg        #faf9f6   (warm off-white)
--panel     #ffffff
--ink       #111111
--ink2      #555555
--ink3      #8a8a82
--line      #e6e3db
--line-soft #efece4
--chip-bg   #f3efe6
--hover     #f5f2ea
--accent    #ff4d2e   (configurable; 5 swatches in tweaks)
--shadow    0 12px 32px rgba(40,30,20,.10)
```

**Color tokens (dark):**

```text
--bg        #0e0f0e
--panel     #15161a
--ink       #f5f4ef
--ink2      #a3a39d
--ink3      #6a6a64
--line      #26282d
--line-soft #1e2025
--chip-bg   #1c1d22
--hover     #1a1b20
--shadow    0 12px 36px rgba(0,0,0,.45)
```

**Category swatches** (oklch — overrides v1.2 hex):

```text
urgent     oklch(0.62 0.20 25)
bug        oklch(0.56 0.18 285)
feature    oklch(0.66 0.13 205)
question   oklch(0.72 0.13 92)
billing    oklch(0.62 0.13 148)
complaint  oklch(0.66 0.16 50)
other      oklch(0.65 0.00 0)
```

**Borders.** 0.5 px hairlines. 4 px card radius. 3 px button/chip radius. Filter pills 999 px.

**Mono micro-labels.** 10–11 px, `letter-spacing: .04em`, `text-transform: uppercase`. Used for ids (`INT-48211`), updated-ago (`4m ago`), counts (`8 msgs`), section headers (`Customer`, `Plan`), follow-up chips (`F/U in 15m`).

**Animations.** Three keyframes total:

```css
@keyframes triagePulse { 0%,100%{opacity:1} 50%{opacity:.45} }
@keyframes triageRing  { 0%{box-shadow:0 0 0 0 rgba(255,77,46,.55)} 100%{box-shadow:0 0 0 14px rgba(255,77,46,0)} }
@keyframes triageSlide { from{transform:translateX(20px);opacity:0} to{transform:translateX(0);opacity:1} }
```

**Density variants.** `compact` (12.5 px title, 2-line clamp, 8/10 px padding), `balanced` (13.5 px title, 3-line clamp, 11/12 px padding, **default**), `comfy` (same title, 4-line summary clamp).

**Tweaks panel** (operator-toggleable, persisted in `settings`): dark mode, accent swatch, density, show summary, show confidence. Mute alarms is the sixth toggle.

## 8c. Ticket resolution

Operator marks tickets resolved; resolved tickets leave the category columns
into a dedicated always-visible Resolved column. Resolution is an orthogonal
flag on `tickets`, not a state value or a category.

**Sources:** `manual` (operator drag/icon/flyout), `intercom_closed` (silent
auto-resolve when Intercom state flips open → closed during sync), AI-suggested
(advisory chip; operator confirms; never auto-moves).

**Schema additions:**
- `tickets`: `resolved_at`, `resolved_source`, `ai_resolve_enabled` (raw nullable per-ticket override), `resolution_chip_dismissed_at`.
- `ai_cache`: `ai_resolution_verdict`, `ai_resolution_confidence`, `ai_resolution_reason`.
- `settings`: `ai_resolve_default`, `ai_resolve_confidence_threshold`.

**Endpoints:** `POST /tickets/{id}/resolve`, `POST /tickets/{id}/reopen`,
`PATCH /tickets/{id}/ai-resolve`, `POST /tickets/{id}/dismiss-chip`.
`GET /tickets?resolved=true|false` filters; default excludes resolved.

**Chip state** computed server-side per row from settings + ticket + AI cache;
never auto-moves a ticket.

See `docs/superpowers/specs/2026-05-23-ticket-resolution-design.md` for the full
design.

**`non_actionable_kind` (roadmap 4.2 / T107, migration 0020):** `tickets.non_actionable_kind` + `ai_cache.non_actionable_kind` — nullable enum (`auto_reply` | `thanks` | `spam` | `out_of_office` | `other`). AI-derived: the categorization structured response returns it only for the `non_actionable` verdict; missing/invalid falls back to `other`. Stamped on ingest's AI auto-mark path; manual marks leave it null; every reopen path clears it (CHECK-coupled to `resolved_source='non_actionable'`). Rides `TicketSchema` (board-state only, not `HydratedTicket` — invariant #2 not involved, same pattern as triage facets T142). Webapp non-actionable column filters by it; both surfaces label the chip.

## 8d. Bulk actions

Operator selects N tickets and applies one action. Cuts per-ticket click cost.
Webapp-only in v1 — popup ergonomics too cramped for multi-select.

**Selection store (client).** New Pinia `selectionStore` exposes
`Set<string>` of selected ticket ids, plus `toggle(id)`, `addRange(columnId, fromId, toId)`,
`addAll(ids)`, `clear()`, getters `count`, `has(id)`, `asArray()`. The store is
transient — cleared on view change, on Escape, on empty-background click, and
after every successful bulk action. Range-select consults the column's
displayed-sort order, which lives on `Column.vue` and is exposed via a small
helper.

**Card interaction (`TicketCard.vue`).**
- Plain click → existing flyout behavior (unchanged).
- Cmd/Ctrl+click → `selection.toggle(id)`, no flyout.
- Shift+click → if a card in the same column is already selected, extend the
  range from the last-selected anchor to the clicked card (sorted order);
  otherwise behave as Cmd/Ctrl+click. Selected cards get a 2 px accent ring
  via `data-selected="true"`.

**Column header.** `Column.vue` shows a `Select all (N)` mono chip when at
least one card in that column is selected or when the header is hovered.
Clicks call `selection.addAll(columnTicketIds)`.

**Bulk action bar (`BulkActionBar.vue`).** Sticky bottom-center, slides in
when `selection.count > 0`. Layout:

```
[N selected] [Clear]   ·   [Resolve] [Reopen]   ·   [Move to ▾]   ·
[Follow-up ▾] [Clear F/U]   ·   [More ▾]
```

Buttons that don't apply to the current selection are disabled with a tooltip
explaining why (e.g. `Reopen` is disabled unless every selected card is
resolved). Move-to and Follow-up chips reuse the existing category picker +
preset chip components.

**Bulk drag.** `vuedraggable` runs in multi-drag mode. When the operator
starts dragging a card that is in the selection set, the drag payload becomes
the entire selection. Dropping into a category column issues a bulk
`PATCH /tickets/bulk/category`; dropping into the Resolved column issues
`POST /tickets/bulk/resolve`. Dropping a non-selected card behaves as today
(single-item override).

**Optimistic updates with per-id rollback.** Each bulk store action
(`bulkResolve`, `bulkReopen`, `bulkRecategorize`, `bulkSetFollowup`,
`bulkClearFollowup`, `bulkDismissChip`) snapshots the affected ticket rows,
mutates them locally, then issues the bulk request. On response, any id in
`failed[]` is rolled back from the snapshot; a single toast summarizes:
`"12 resolved, 1 failed (T123 — already resolved)"`.

**Server.** Each bulk endpoint loops the existing per-id service function
(`resolution_svc.resolve`, `set_override`, etc.) inside one session. The loop
catches `HTTPException` per id and records `{id, reason}` to `failed[]`. The
loop commits once at the end — service functions that flush mid-loop are
re-implemented with `session.no_autoflush` blocks if necessary. A new
`MAX_BULK_IDS` config (default 200) is enforced on the request body via a
Pydantic `Field(max_length=...)`; over-cap requests return 422 before any DB
work.

**Metrics (`/metrics`).** New counter `bulk_actions_total{op, result}` —
labels: `resolve | reopen | recategorize | followup_set | followup_clear | dismiss_chip`
× `ok | partial | fail`. Plus `bulk_action_ids_total{op}` to track volume.

**Vitest harness.** Webapp gains a vitest setup (Vue Test Utils +
`happy-dom`) as part of this phase. The selection store and the bulk store
actions are the first units under test; existing stores get coverage as
opportunistic follow-up but are not in scope for the phase.

## 9. Settings

Singleton row in the `settings` table. Both surfaces `GET /settings` on open and `PUT /settings` on change. No client-side persistence — the surface reads from the backend each session.

## 10. Deployment

Local-only. To run:

```
cd backend && uvicorn main:app --port 8000              # backend on localhost
cd webapp && npm run dev                                  # webapp on localhost:5173
# extension: chrome://extensions → load unpacked → ./extension
```

SQLite file lives at `backend/data/triage.db` (configurable via `DATABASE_URL`). Backups are a single file copy.

Postgres swap: change `DATABASE_URL` in `.env` to a `postgresql+asyncpg://…` URL, ensure `asyncpg` is installed. Schema is portable; SQLAlchemy handles dialect differences.

## 11. Observability

Structured logging via Python's standard `logging` (stdlib only — no structlog). `observability.log_event` / `logged_call` emit per external call: `op`, `duration_ms`, `outcome`, `ticket_id` where applicable. No ticket bodies in logs.

Lightweight counters in process memory (`tickets_fetched_total`, `ai_calls_total{result}`, `cache_hits_total`, `overrides_set_total`, `proposals_created_total`, `proposals_resolved_total{resolution}`, `bulk_actions_total{op,result}`, …), plus two additions surfaced via `GET /metrics`:

- **Latency histograms (NFR-009):** external-call durations sampled into bounded per-key deques; `metrics.histogram_snapshot()` reports p50 / p95 / max. Nearest-rank percentiles over the retained window — single-operator scope, not a Prometheus exporter.
- **Token / cost meter (FR-050):** OpenRouter token usage accumulated per (UTC-date, model) with an estimated USD cost (`app/pricing.py` × token counts). In-process, resets on restart.

Promote to OpenTelemetry / Logfire only if you start running this against a real workload.

## 12. Decision log

| Decision | Alternatives | Reason |
|---|---|---|
| SQLite default with portable schema | Postgres from day one | Local single-user tool; zero setup. Postgres remains a one-line swap. |
| ~~No Alembic for v1~~ **(superseded)** | Alembic from day one | Originally `create_all` + seed for simplicity, "add Alembic when the first schema change happens." That happened — the project now runs **forward-only Alembic migrations** (see §1, §5). `create_all` is retained only for tests / schema smoke. |
| No authentication | Shared header secret, OAuth, JWT | Backend listens on `localhost`; threat model is a single trusted user on their own machine. |
| Integer PKs instead of UUIDs | UUIDs everywhere | No multi-system uniqueness requirement. Integers are smaller, faster, easier to read in dev. |
| Reverted from multi-tenant | Keep multi-tenant from v1.1 | YAGNI for current scope. Reintroducing tenants later means adding a `tenant_id` column and a resolution layer; no other architectural rework. |
| Reverted Identity Platform | Roll JWT verification | Auth dropped entirely. |
| OpenRouter rather than direct Anthropic API | Direct Anthropic SDK | Already in use; single key, swappable models. |
| Pending proposals appear as live columns | Hide proposals until approved | Surfaces the curation work; prevents stale pending state being invisible. |
| Server-side settings (singleton row) | `.env` or per-surface local storage | One source of truth; both surfaces read the same shape; trivial to back up. |
| Rejected-proposal signatures table kept | Drop with the multi-tenant scope | Still useful for one user — prevents the AI re-proposing the same category every fetch. |

## §13 — Playbooks

Design spec: `docs/superpowers/specs/2026-05-26-playbooks-design.md`.

- New `playbooks` table (one isolated backend module: `services/playbooks.py`
  + `routers/playbooks.py`). No change to ingest, cache, or `HydratedTicket`.
- Lookup resolves a ticket's effective category exactly as board composition
  does (override wins iff `ticket.updated_at <= override.set_at`).
- AI drafter reuses `OpenRouterClient`; prompt is built from `parts` + operator
  notes only — `internal_notes` is never read.
- Webapp: `stores/playbooks.ts`, flyout section `TicketPlaybooks.vue`, library
  view `PlaybooksPage.vue` wired through the `view` store (no router).

## §14 — Parked / snoozed state

Design spec: `docs/superpowers/specs/2026-05-27-parked-snoozed-state-design.md`.
Plan: `docs/superpowers/plans/2026-05-27-parked-snoozed-state.md`. Roadmap 4.1 / T106.

- Parallel state mirroring resolution: `tickets.parked_at` / `parked_until` /
  `parked_reason` (enum), three CheckConstraints — trio all-or-null, reason enum,
  and `NOT (parked_at IS NOT NULL AND resolved_at IS NOT NULL)`. Migration 0018.
  Park is orthogonal to resolution + category.
- `clear_parked(row)` runs on every resolve path (`apply_resolve`,
  `apply_mark_non_actionable`, `_maybe_auto_resolve_from_ai`, the `_upsert_ticket`
  close-transition) so the not-parked-and-resolved constraint always holds.
- "Ready to resume" (`parked_until <= now`) is derived on read — no background
  job. Endpoints: `POST /tickets/{id}/park` + `/unpark` + `/tickets/bulk/park` +
  `/bulk/unpark`. Parked is board-state on `TicketSchema`, NOT `HydratedTicket`
  (extension `normalizeConversation` untouched); sticky across re-sync because
  `_upsert_ticket` never writes the trio.
- Webapp Layout B: parked tickets excluded from category columns; Topbar
  `parkedOnly` filter chip + `★ ready` badge; `ParkMenu.vue` (duration presets +
  reason) drives park; bulk park/unpark in `BulkActionBar`. Extension popup gains
  a Parked tab + single-ticket park/unpark.

## §15 — AI reliability (roadmap 2.1 / 2.2 / 2.3)

Three independent reliability layers over the single categorization call. All
preserve FR-007 (any failure → fallback for that ticket; batch never aborts) and
the content-signature cache key (#6).

- **Strict structured outputs (FR-053).** The categorization request uses
  OpenRouter's JSON-schema-enforced `response_format` instead of relying on
  `{...}` extraction from free text. A response that fails the schema is treated
  as a parse failure → fallback for that one ticket. The fragile fence-stripping
  path remains as a defensive fallback but is no longer the primary contract.
- **Model cascade (FR-054), opt-in.** `cascade_enabled` (default off). When on,
  the cheap model (`openrouter_cheap_model`, default `anthropic/claude-3.5-haiku`)
  categorizes first; if its self-reported confidence `< cascade_escalate_below`
  (default 0.7) — or the cheap call fails / returns malformed output — the ticket
  escalates to the strong `openrouter_model`. Cost model in `app/pricing.py`.
  **Measure escalation rate before enabling on a real corpus** — a >40% rate
  erases the savings.
- **Needs-review lane (FR-055).** Pure view-layer split, no migration, no stored
  state — mirrors the non-actionable column pattern (#10). An open, non-overridden
  ticket with `ai_confidence < review_confidence_threshold` (default **0.65**,
  *calibrated* in `tests/test_review_calibration.py`, not guessed) surfaces in a
  webapp review lane; writing an override clears it. The threshold is mirrored in
  `webapp/src/utils/review.ts` as `REVIEW_CONFIDENCE_THRESHOLD` (keep in sync) and
  surfaced on `GET /health` for auditability.

## §16 — Local embedding layer + few-shot + RAG (roadmap 2.4 / 2.5 / 2.6)

The keystone (2.4) plus its first two consumers.

- **Embedding layer (FR-056).** Local `sentence-transformers` (`all-MiniLM-L6-v2`,
  384-dim, CPU, ~80 MB, lazy-loaded) writing to a `ticket_embeddings` table in the
  same SQLite DB. `embeddings_enabled` (default on) gates the whole layer; off =
  the ingest hook is a no-op and the heavy import is skipped. Embeds customer-
  visible `parts[]` + title (+ operator notes where applicable) **only** — never
  `internal_notes[]` (#4). Computed on ingest; **never** reads or writes
  `ai_cache` / the content signature (#6). `app/ai/embeddings.py`.
- **Few-shot categorization (FR-057).** `app/ai/fewshot.py`. On an uncached
  ticket, retrieve the nearest `fewshot_examples` (default 3, `0` disables)
  confirmed-override neighbours by embedding similarity and inject them into the
  prompt as gold-label examples. Gated on `embeddings_enabled`. With injection off
  the prompt is byte-identical to the cold-corpus path.
- **RAG draft replies (FR-058).** `POST /playbooks/draft-reply` →
  `DraftReplyResponse {body, grounding_ticket_ids, playbook_ids}`. Grounds an
  ephemeral customer reply in the k nearest RESOLVED tickets (customer-visible
  parts only) + the ticket's effective-category playbooks. Reuses
  `OpenRouterClient`; never reads `internal_notes[]` (#4); 503 when AI unconfigured.
  Nothing persisted.

## §17 — Recurring-issue insights (roadmap 3.1 / 3.2 / 3.3)

All three ride on §16's embeddings. Read-only over a periodically-recomputed
snapshot; none touch `ai_cache` (#6).

- **Clustering (FR-059).** `app/ai/clustering.py` + a background loop in
  `app/main.py` (`_clustering_loop`, spawned only when `clustering_enabled` AND
  `embeddings_enabled`). HDBSCAN over RESOLVED tickets' embeddings; outliers
  flagged, not force-fit; each cluster labelled with c-TF-IDF top terms over
  customer-visible `parts[]` + title only (#4). Cadence `clustering_interval_seconds`
  (default 6 h); skipped below `clustering_min_tickets` (default 5). Snapshot
  written atomically to `ticket_clusters` + `ticket_cluster_members`. Reads:
  `GET /clusters`; manual refresh: `POST /clusters/recompute`.
- **Playbook-gap detection (FR-060).** `GET /clusters/gaps` →
  `ClusterGapRead[]`. Ranks clusters whose dominant *effective* category (#13) has
  no active playbook, most-recurring-first; names the `category_id` to write a
  playbook for plus `member_count` support. Pure local join over the snapshot +
  playbooks.
- **Playbook auto-match (FR-061).** `GET /playbooks/suggested?ticket_id=` →
  `SuggestedPlaybook[] {playbook, score}`. Ranks the ticket's effective-category
  playbooks by cosine similarity to its customer-visible text (#4), most-relevant-
  first. Ephemeral; empty when uncategorized / no in-category playbooks.

## §18 — Operator throughput & analytics (roadmap 0.2–0.4, 1.1–1.6)

UX + visibility. Mostly pure-stack; the one cross-package change is 0.2.

- **Triage facets (FR-043/FR-044), cross-package.** The categorization structured
  response gains `priority` (`low`\|`normal`\|`high`\|`urgent`), `sentiment`
  (`negative`\|`neutral`\|`positive`), and `labels: string[]`. Stored on `ai_cache`
  (`ai_priority` / `ai_sentiment` / `ai_labels`, null/empty on pre-0.2 rows),
  surfaced on `TicketSchema`, consumed by the webapp (priority badge) — **one PR
  across backend + webapp** (the extension/`HydratedTicket` shape is untouched,
  so invariant #2 doesn't apply here). Same single AI call; cache key unchanged.
- **Aging indicators (FR-045).** Pure webapp. Card stripe tiered by time since the
  last customer-visible part; thresholds in one constant. Timestamps already on
  the wire (#5).
- **Keyboard triage (FR-046).** Pure webapp keybindings (`j`/`k`/`e`/digit/`/`),
  guarded against firing inside text inputs. Satisfies NFR-007.
- **Saved views (FR-047).** Pinia `savedViews` store, persisted to `localStorage`;
  named presets over the facets the board already returns. Backend untouched.
- **Priority-sorted queue (FR-048).** Optional within-column ordering by
  `ai_priority`, remembered locally; off restores recency / follow-up-due order.
- **Stats dashboard (FR-049).** `GET /stats?window_days=N` → `StatsResponse`
  (`services/stats.py`): `total_tickets`, `category_breakdown`, `volume_trend`,
  `resolution_mix`, `resolve_time_buckets`, `median_resolve_hours`. Group-by over
  the local store; no migration. Renders spec §8's four success metrics.
- **Cost meter (FR-050).** See §11 — per-(date, model) token + USD estimate on
  `/metrics`; webapp surfaces today's spend.
- **Snippets (FR-051).** `snippets` table + thin CRUD (`/snippets`,
  archive/restore). Body stored verbatim with `{{variable}}` placeholders;
  substitution client-side (`webapp/src/utils/snippets.ts`). Global (not category-
  scoped), no AI draft — lighter than playbooks; durable (#13).
- **Bulk pre-flight diff (FR-052).** Client-side preview of affected vs skipped
  counts from loaded ticket state before a bulk apply; mirrors `MAX_BULK_IDS` (#9).

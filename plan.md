# Intercom Triage — Technical Plan

**Status:** ready · **Version:** 1.2 · **Implements:** `spec.md` v1.2 · **Sibling docs:** `spec.md`, `tasks.md`

This document defines **how** the system is built. Each section maps back to one or more spec requirements. Tasks in `tasks.md` reference both spec IDs and plan sections.

**Changes from v1.1:** all cloud and auth infrastructure removed. SQLite replaces Cloud SQL Postgres. KMS removed (Intercom token in `.env`). Identity Platform / OAuth removed (no users, no JWT verification). Alembic dropped in favor of SQLAlchemy `create_all` on startup. Backend is a single-process FastAPI on `localhost`.

---

## 1. Stack decisions

| Layer | Choice | Why |
|---|---|---|
| Backend | Python 3.11+, FastAPI | Matches Christian's existing stack |
| HTTP client | `httpx` (async) | Standard async client |
| Config | `pydantic-settings` reading `.env` | Existing pattern |
| Database | SQLite (default), via SQLAlchemy 2.0 async (`aiosqlite` driver) | Zero-setup, single file, ships with Python. Postgres swap is a one-line URL change. |
| Schema management | SQLAlchemy `metadata.create_all` + seeding on startup | Alembic is overkill at this scope; add later if/when schema needs versioned migrations |
| Webapp | Vue 3 + Vite + TypeScript | Matches OnlySales frontend |
| Client state | Pinia | Standard Vue 3 |
| Drag-and-drop | `vuedraggable@next` | Vue 3 compatible |
| Extension | Manifest V3 + vanilla TypeScript | Keeps popup bundle small |
| AI gateway | OpenRouter | Single contract for Anthropic models |
| AI model (default) | `anthropic/claude-sonnet-4.5` | Quality default |
| AI model (cost mode) | `anthropic/claude-haiku-4.5` | Configurable via `.env` |
| Deploy | `uvicorn main:app` on localhost; webapp via `npm run dev` or static build; extension side-loaded | No cloud, no Docker required |
| Secrets | `.env` file (gitignored) | NFR-005 |

## 2. Architecture

Three components. All run locally; backend listens on `localhost` only.

The **backend** is a FastAPI service. It owns the Intercom integration, the AI integration, the SQLite persistence layer, and the public API surface. Reads its Intercom token and OpenRouter key from `.env`.

The **webapp** is a Vue 3 SPA. It calls the backend at `http://localhost:<port>`. Owns the Kanban UI, drag-and-drop, settings UI, category admin pages, proposals review queue, and the extension-discovery callout.

The **Chrome extension** is a Manifest V3 extension. Calls the same `localhost` backend. Owns the popup mini-board (full taxonomy as column tabs, override-capable), optional background polling, badge, and "Open full board" handoff.

Fetch data flow: client `POST /tickets/fetch` with a `FilterSettings` body → backend queries Intercom Conversations Search with a time-bounded query (FR-001) → hydrates each result, HTML stripped (FR-003) → for each ticket, checks the AI cache (FR-008); on miss, calls OpenRouter with a prompt built from the current taxonomy → resolves AI output into either an existing category id, an existing pending proposal id, or a newly-created proposal (FR-015) → applies user overrides (FR-009) → sorts and returns (FR-013).

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
| POST | `/tickets/fetch` | `FilterSettings` | `Ticket[]`, sorted | FR-001, FR-004, FR-005, FR-006, FR-008, FR-011, FR-013 |
| PATCH | `/tickets/{id}/category` | `CategoryUpdate` | `{ok, category_id}` | FR-009 |
| GET | `/settings` | — | stored `FilterSettings` | FR-012 |
| PUT | `/settings` | `FilterSettings` | stored `FilterSettings` | FR-012 |

Error contract: `502` on upstream Intercom failure, `422` on schema violation, `404` on unknown id, `409` on archive of fallback or other invalid state transition.

## 5. Data model

Six tables. SQLAlchemy 2.0 declarative models; created via `metadata.create_all` on first run, then seeded if empty. Concrete models in `snippets/models.py`.

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
  -- check: exactly one of category_id, proposal_id is set

overrides
  ticket_id    text pk
  category_id  integer not null fk → categories(id) on delete cascade
  set_at       datetime default now

settings
  id                    integer pk check (id = 1)        -- singleton row
  lookback_unit         text default 'hours' check in ('hours','days')
  lookback_value        int default 24 check between 1 and 720
  states                json default '["open"]'
  include_category_ids  json                              -- null = all
  updated_at            datetime default now

rejected_proposal_signatures
  signature      text pk
  rejected_name  text not null
  rejected_at    datetime default now
```

Behavioral notes. `ai_cache` enforces "exactly one of `category_id`, `proposal_id`" via a check constraint — this matches the AI output resolver (§7). Foreign keys cascade so that when a category or proposal is hard-deleted, dependent cache rows go with it. `overrides` cascades from category too. The `settings` table is a singleton via `CHECK (id = 1)`; the app inserts the row at first startup. Partial unique indexes prevent two active categories or two pending proposals from sharing a name, while letting archived/resolved rows reuse names.

## 6. Intercom integration

The backend calls `POST /conversations/search` with the token from `.env`. Query body: `AND([updated_at > threshold, state filter])`, `per_page: 50`, paginated via `starting_after` until either chain end or `MAX_TICKETS_PER_FETCH` (default 100). Each result is hydrated via `GET /conversations/{id}?display_as=plaintext` in parallel; one failure does not fail the batch (NFR-003). The Intercom workspace id is resolved once at startup via `GET /me` and cached in process memory for deep-link composition (FR-010): `https://app.intercom.com/a/apps/<workspace_id>/conversations/<id>`. HTML is stripped (`<br>` → `\n`, `</p>` → `\n`, remaining tags removed) before AI input.

## 7. AI specification

OpenRouter `/chat/completions`, OpenAI-compatible. Headers: `Authorization`, `HTTP-Referer`, `X-Title`. Model from `OPENROUTER_MODEL` env.

Request shape: `model`, `messages=[system,user]`, `temperature=0.1`, `max_tokens=400`, `response_format={type:"json_object"}`.

The prompt builder is in `snippets/prompt_builder.py`. It assembles the user message from the current active categories, pending proposals, and rejected-name list, plus the ticket's title, state, and transcript (≤ 6000 chars, middle-truncated).

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

Structured logging via Python's standard `logging` plus `structlog` (or the existing OnlySales `StructuredLogger` if you want consistency). Per external call: `op`, `duration_ms`, `outcome`, `ticket_id` where applicable. No ticket bodies in logs.

Lightweight counters in process memory for `tickets_fetched_total`, `ai_calls_total{result}`, `cache_hits_total`, `overrides_set_total`, `proposals_created_total`, `proposals_resolved_total{resolution}`. Exposed via `GET /metrics` returning JSON. Promote to OpenTelemetry / Logfire only if you start running this against a real workload.

## 12. Decision log

| Decision | Alternatives | Reason |
|---|---|---|
| SQLite default with portable schema | Postgres from day one | Local single-user tool; zero setup. Postgres remains a one-line swap. |
| No Alembic for v1 | Alembic from day one | Schema is small and stable; `create_all` plus a seed function is simpler. Add Alembic when the first schema change happens. |
| No authentication | Shared header secret, OAuth, JWT | Backend listens on `localhost`; threat model is a single trusted user on their own machine. |
| Integer PKs instead of UUIDs | UUIDs everywhere | No multi-system uniqueness requirement. Integers are smaller, faster, easier to read in dev. |
| Reverted from multi-tenant | Keep multi-tenant from v1.1 | YAGNI for current scope. Reintroducing tenants later means adding a `tenant_id` column and a resolution layer; no other architectural rework. |
| Reverted Identity Platform | Roll JWT verification | Auth dropped entirely. |
| OpenRouter rather than direct Anthropic API | Direct Anthropic SDK | Already in use; single key, swappable models. |
| Pending proposals appear as live columns | Hide proposals until approved | Surfaces the curation work; prevents stale pending state being invisible. |
| Server-side settings (singleton row) | `.env` or per-surface local storage | One source of truth; both surfaces read the same shape; trivial to back up. |
| Rejected-proposal signatures table kept | Drop with the multi-tenant scope | Still useful for one user — prevents the AI re-proposing the same category every fetch. |

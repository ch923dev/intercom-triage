# CLAUDE.md

Repo-wide guidance for Claude Code. This file is the **top-level entry point** — read first, then drop into the relevant sub-package CLAUDE.md.

> Sub-package guides:
> - [`backend/CLAUDE.md`](./backend/CLAUDE.md) — FastAPI + async SQLAlchemy + OpenRouter
> - [`webapp/CLAUDE.md`](./webapp/CLAUDE.md) — Vue 3 + Pinia + Vite
> - [`extension/CLAUDE.md`](./extension/CLAUDE.md) — Chrome MV3 popup + service worker

These four principles override defaults. Apply every change.

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

- State assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

Across this repo:
- The system is a **single-operator local tool**, not a SaaS. One Intercom workspace, one taxonomy, one operator, one machine. Don't add multi-tenancy, auth, deployment infra, hosted observability, or rate-limited public surfaces.
- The contract is `spec.md` (what) + `plan.md` (how) + `tasks.md` (the T-numbers cited throughout the code). Read before guessing. Module docstrings reference these by section / task id.
- The data-flow pivot is non-obvious: **the backend has no Intercom Access Token.** The Chrome extension scrapes conversations from the operator's logged-in browser session and POSTs to `/tickets/ingest`. Empty board = "operator hasn't synced," not "fetch failed." Don't add Intercom HTTP clients on the backend. Don't add Access-Token paths.
- The same `HydratedTicket` shape spans three packages (`extension/intercom.js:normalizeConversation` → backend `app/schemas.py:HydratedTicket` → webapp `src/types/api.ts`). Edits ship together.
- Intercom's `renderable_type` mapping (1/12 customer, 2/24 admin, 3 internal-note) is reverse-engineered + unstable. Flag any change touching it.

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" / "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

Across this repo:
- Three packages, three stacks, intentionally. **Don't merge them**. The extension is plain ES modules (no bundler) because it must load in MV3; the webapp is Vue 3 + Vite because it's a SPA; the backend is FastAPI because it's an HTTP service. Don't introduce a monorepo tool, shared package, or codegen step.
- `localhost:8000` (backend) + `localhost:5173` (webapp dev) + `chrome-extension://…` (popup). No reverse proxy, no Docker, no nginx. The Vite dev server proxies `/api/*` to `127.0.0.1:8000`. Don't change the topology.
- Default to no comments. Module-level `Reference: plan.md §X, tasks.md TXXX` markers point at external specs — they're the canonical convention. Don't echo what the code already says.
- One backend, one DB (SQLite by default, Postgres via `DATABASE_URL` swap). Don't add a second store, a cache server (the AI cache lives in the same SQLite DB), or a message broker.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports your change made unused. Don't remove pre-existing dead code unless asked.

Across this repo:
- Each package has its own style rules — see the sub-CLAUDE.md. Don't impose one package's style on another (Python ruff config ≠ webapp prettier ≠ extension ad-hoc).
- Cross-package changes (schema, ingest shape, API contract) ship in one PR. Don't merge backend half of a contract change without the webapp + extension half.
- Naive UTC in the DB; `Z`-suffixed ISO on the wire. Both clients (`webapp` + `extension`) `Date.parse` the `Z` form correctly. Never emit a naive ISO from the backend.
- `MAX_BULK_IDS = 200` (in `backend/app/config.py`) is the shared cap. Webapp warns the operator before submitting larger selections. Bumping it = code change in both places.

The test: every changed line traces directly to the user's request.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals before writing code. For multi-step work, state the plan up front:

```
1. [step] → verify: [check]
2. [step] → verify: [check]
```

Repo-wide green path before merge:

| Package    | Quality gate                                                                 |
|------------|------------------------------------------------------------------------------|
| backend    | `ruff check app tests && ruff format --check app tests && mypy app && pytest -q` |
| webapp     | `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build` |
| extension  | Reload unpacked in `chrome://extensions` → sync → confirm popup renders + badge count + no console errors |

"Make it work" is not a success criterion. Name the test, the click-path, the curl, or the `/metrics` counter that proves the change.

---

# Reference

## Repo map

```
intercom-ticket-management/
├── backend/        FastAPI service + SQLite + OpenRouter integration       ← see backend/CLAUDE.md
├── webapp/         Vue 3 SPA — the kanban board + admin pages              ← see webapp/CLAUDE.md
├── extension/      Chrome MV3 popup + background service worker            ← see extension/CLAUDE.md
├── docs/           Long-form specs (superpowers/, design records)
├── scripts/        dev-backend.ps1/.sh, seed-db.ps1/.sh
├── design_bundle/  Static design assets referenced by DESIGN.md
├── spec.md         Requirements — WHAT (US-*, FR-*, NFR-*)
├── plan.md         Architecture + decisions — HOW (§1..§12)
├── tasks.md        Task breakdown w/ traceability matrix (T001..)
└── README.md       Quickstart + API surface table
```

## System architecture (one paragraph)

Operator signs into Intercom in Chrome. The Chrome extension scrapes conversations from the logged-in session via Intercom's undocumented `ember/` API. The extension POSTs `HydratedTicket[]` to the backend (`POST /tickets/ingest`). The backend categorizes via OpenRouter (semaphore-bounded, cache-aware on the customer-visible content signature) against the operator's curated taxonomy, stores rows in SQLite, and serves the board via `GET /tickets`. The webapp (Vue SPA) and the extension's popup mini-board both read from the backend; mutations (override, resolve, follow-up, bulk) go back through the same HTTP API.

## Data flow (cross-package)

```
                          Intercom (browser session, ember/ API)
                                  │
                                  ▼
                  ┌──────────────────────────────────┐
                  │ extension/intercom.js            │
                  │   normalizeConversation()        │
                  └──────────────┬───────────────────┘
                                 │ HydratedTicket[]
                                 ▼
                  POST /tickets/ingest         (backend categorizes + caches + stores)
                                 │
                          ┌──────┴──────┐
                          ▼             ▼
              GET /tickets       GET /tickets
                  (webapp)        (popup mini-board)
                  PATCH/PUT/POST: override · resolve · reopen · followup ·
                                 note · bulk · ai-resolve · dismiss-chip
```

The `HydratedTicket` shape is defined in `backend/app/schemas.py` and consumed verbatim by both clients. The backend's `/tickets/sync-state` endpoint returns `{id: updated_at}` so the extension can skip the per-conversation detail fetch for unchanged conversations.

## Run the stack locally

Each in its own terminal:

```powershell
# Terminal 1 — backend (FastAPI on 127.0.0.1:8000)
.\scripts\dev-backend.ps1

# Terminal 2 — webapp (Vite on 127.0.0.1:5173, proxies /api → :8000)
cd webapp
npm install
npm run dev

# Terminal 3 — extension
#   chrome://extensions → Developer mode → Load unpacked → select extension/
#   Reload the unpacked extension after every code change.
```

First boot: backend creates `backend/data/triage.db`, seeds 7 default categories, inserts the singleton settings row. Missing `OPENROUTER_API_KEY` does not block startup — `/health` reports it; ingest writes every ticket to the fallback category until the key is provided.

Operator must enter the Intercom workspace `app_id` (e.g. `j3dxf22l`) in the popup setup screen once; it's stored in `chrome.storage.local.intercomAppId`.

## Cross-package invariants

These are the ones a Claude touching multiple packages keeps getting wrong if not flagged:

1. **No Intercom Access Token anywhere.** Extension is the only ingestion path.
2. **`HydratedTicket` shape spans three packages.** Edit all three together or break ingest.
3. **`renderable_type` mapping is reverse-engineered.** 1/12 customer, 2/24 admin, 3 internal-note, anything else skipped.
4. **`parts[]` is customer-visible (fed to AI); `internal_notes[]` is team-only (never fed to AI).** Keep them separated end-to-end.
5. **Naive UTC in DB; `Z`-suffixed ISO on the wire.** Pydantic `UTCDatetime` / `NaiveUTCDatetime` enforce this; JS clients depend on it.
6. **AI cache key = content signature (last customer-visible part timestamp), not Intercom `updated_at`.** Internal teammate notes must not bust cache.
7. **Fallback `CategorizationResult` rows are never cached.** Caching a fallback poisons the ticket until a new customer message arrives.
8. **`title_user_edited` / `summary_user_edited` are sticky across re-syncs.** Extension ingest + backend `_upsert_ticket` must preserve operator edits.
9. **`MAX_BULK_IDS = 200`.** Backend constant, webapp pre-flight warning. Bump together.
10. **`tickets.resolved_at` ⇔ `resolved_source`** (XOR CheckConstraint). `resolved_source ∈ {'manual', 'intercom_closed'}`.
11. **Drag-out reopen is atomic.** Setting an override on a resolved ticket clears `resolved_at` + `resolved_source` in the same transaction.
12. **Singleton `Settings` row enforced by `CHECK (id = 1)`.** `init_db` inserts it on first boot.

## Versions / stack at a glance

| Package    | Stack                                                                                 |
|------------|---------------------------------------------------------------------------------------|
| backend    | Python 3.11+, FastAPI 0.115, SQLAlchemy 2.0 (async), Alembic, pydantic v2, httpx       |
| webapp     | Vue 3.5, Pinia 2.3, Vite 6, TypeScript 5.6, vue-tsc, ESLint 9, Prettier 3, Vitest 2    |
| extension  | Plain ES modules, MV3, no build step, no dependencies                                  |
| AI         | OpenRouter (`anthropic/claude-sonnet-4.5` default; swap via `OPENROUTER_MODEL`)        |
| Storage    | SQLite (default, `backend/data/triage.db`) · Postgres swap via `DATABASE_URL`         |

## When in doubt

1. Read `spec.md` for the *what*.
2. Read `plan.md` for the *how*.
3. Read the sub-package `CLAUDE.md` for stack-specific rules.
4. Grep for the relevant T-number in `tasks.md` to find the implementation footprint.
5. If still unclear — ask. The cost of a clarifying question is one round-trip; the cost of a wrong guess across three packages is much higher.

## Don't

- Don't add a backend-side Intercom HTTP client.
- Don't introduce a monorepo tool / shared package / codegen step.
- Don't deploy this anywhere (no Dockerfile, no CI/CD, no production config).
- Don't add user auth / RBAC / tenants.
- Don't extend the surface area without spec / plan / tasks updates first — those three docs are the source of truth and the traceability matrix.

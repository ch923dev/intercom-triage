# CLAUDE.md

Repo-wide guidance for Claude Code. Top-level entry point — read first, then drop into the relevant sub-package CLAUDE.md.

> Sub-package guides:
> - [`backend/CLAUDE.md`](./backend/CLAUDE.md) — FastAPI + async SQLAlchemy + OpenRouter
> - [`webapp/CLAUDE.md`](./webapp/CLAUDE.md) — Vue 3 + Pinia + Vite
> - [`extension/CLAUDE.md`](./extension/CLAUDE.md) — Chrome MV3 popup + service worker

## Read first

- [`docs/principles.md`](./docs/principles.md) — the four engineering principles (Think / Simplicity / Surgical / Goal-Driven). Override defaults; apply on every change.
- [`docs/architecture.md`](./docs/architecture.md) — system summary, data-flow diagram, run-the-stack steps, version table.
- `spec.md` — requirements (`US-*`, `FR-*`, `NFR-*`).
- `plan.md` — architecture decisions (§1..§12).
- `tasks.md` — task breakdown + traceability matrix (`T001..`).

## Repo map

```
intercom-ticket-management/
├── backend/        FastAPI service + SQLite + OpenRouter integration       ← see backend/CLAUDE.md
├── webapp/         Vue 3 SPA — the kanban board + admin pages              ← see webapp/CLAUDE.md
├── extension/      Chrome MV3 popup + background service worker            ← see extension/CLAUDE.md
├── docs/           Principles, architecture, long-form specs (superpowers/, design records)
├── scripts/        dev.ps1 (single-command launcher), seed-db.ps1/.sh
├── design_bundle/  Static design assets referenced by DESIGN.md
├── spec.md         Requirements — WHAT (US-*, FR-*, NFR-*)
├── plan.md         Architecture + decisions — HOW (§1..§12)
├── tasks.md        Task breakdown w/ traceability matrix (T001..)
└── README.md       Quickstart + API surface table
```

## Quality gates (run before merge)

| Package    | Gate                                                                                                          |
|------------|---------------------------------------------------------------------------------------------------------------|
| backend    | `ruff check app tests && ruff format --check app tests && mypy app && pytest -q`                              |
| webapp     | `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`                      |
| extension  | Reload unpacked in `chrome://extensions` → sync → confirm popup renders + badge count + no console errors      |

## Cross-package invariants

The ones a Claude touching multiple packages keeps getting wrong if not flagged:

1. **No Intercom Access Token anywhere.** Extension is the only ingestion path.
2. **`HydratedTicket` shape spans three packages** (`extension/intercom.js:normalizeConversation` → `backend/app/schemas.py:HydratedTicket` → `webapp/src/types/api.ts`). Edit all three together or break ingest.
3. **`renderable_type` mapping is reverse-engineered.** 1/12 customer, 2/24 admin, 3 internal-note, anything else skipped.
4. **`parts[]` is customer-visible (fed to AI); `internal_notes[]` is team-only (never fed to AI).** Keep them separated end-to-end.
5. **Naive UTC in DB; `Z`-suffixed ISO on the wire.** Pydantic `UTCDatetime` / `NaiveUTCDatetime` enforce this; JS clients depend on it.
6. **AI cache key = content signature (last customer-visible part timestamp), not Intercom `updated_at`.** Internal teammate notes must not bust cache.
7. **Fallback `CategorizationResult` rows are never cached.** Caching a fallback poisons the ticket until a new customer message arrives.
8. **`title_user_edited` / `summary_user_edited` are sticky across re-syncs.** Extension ingest + backend `_upsert_ticket` must preserve operator edits.
9. **`MAX_BULK_IDS = 200`.** Backend constant (`backend/app/config.py`), webapp pre-flight warning. Bump together.
10. **`tickets.resolved_at` ⇔ `resolved_source`** (XOR CheckConstraint). `resolved_source ∈ {'manual', 'intercom_closed', 'non_actionable'}`. Non-actionable renders as its own Kanban column (webapp) / its own popup tab (extension) — split from Resolved at the view layer (`tickets.nonActionableTickets` / `pureResolvedTickets` getters); storage stays unified. Reopen path clears both.
11. **Drag-out reopen is atomic.** Setting an override on a resolved ticket clears `resolved_at` + `resolved_source` in the same transaction.
12. **Singleton `Settings` row enforced by `CHECK (id = 1)`.** `init_db` inserts it on first boot.
13. **Playbooks are durable operator knowledge, not cache.** `playbooks` rows
    survive ingest / re-sync untouched and are never content-signature-keyed.
    The AI drafter (`POST /playbooks/draft`) reads `parts` + operator notes
    only — never `internal_notes` (see #4). A ticket sees playbooks for its
    *effective* category (override beats AI).

## Subagent doctrine

- Delegate broad codebase searches (>3 grep/glob rounds, "find every place that does X") to `Agent(subagent_type=Explore)` so the main context stays focused on the task. Direct `Grep` / `Glob` for targeted, single-file lookups.
- Delegate independent parallel research (e.g. "summarise backend/app/services/ + extension/intercom.js side-by-side") to two `Agent` calls in one message. Don't run them sequentially in the main thread.
- Do **not** delegate the actual edit. Cross-package edits (HydratedTicket, renderable_type, MAX_BULK_IDS) must run in the main thread with the corresponding skill loaded so the invariant guardrails apply.
- Do **not** delegate when the answer is already in `docs/architecture.md`, `spec.md`, `plan.md`, or `tasks.md`. Read those directly — they exist precisely to short-circuit exploration.

## Scope guardrails

- Single-operator local tool, not a SaaS. One workspace, one taxonomy, one operator, one machine. No multi-tenancy, auth, deployment infra, hosted observability, public surfaces.
- Three packages, three stacks, intentionally. **Don't merge them.** Extension = plain ES modules (MV3); webapp = Vue 3 + Vite (SPA); backend = FastAPI (HTTP). No monorepo tool, shared package, codegen step.
- `localhost:4000` (backend) + `localhost:5173` (webapp dev) + `chrome-extension://…` (popup). Vite proxies `/api/*` → `127.0.0.1:4000`. No reverse proxy, Docker, nginx.
- Cross-package changes (schema, ingest shape, API contract) ship in one PR. Don't merge backend half of a contract change without webapp + extension half.

## When in doubt

1. Read `spec.md` for the *what*.
2. Read `plan.md` for the *how*.
3. Read the sub-package `CLAUDE.md` for stack-specific rules.
4. Grep for the relevant T-number in `tasks.md` to find the implementation footprint.
5. If still unclear — ask. Cost of a clarifying question = one round-trip; cost of a wrong guess across three packages = much higher.

## Don't

- Don't add a backend-side Intercom HTTP client.
- Don't introduce a monorepo tool / shared package / codegen step.
- Don't deploy this anywhere (no Dockerfile, no CI/CD, no production config).
- Don't add user auth / RBAC / tenants.
- Don't extend the surface area without `spec.md` / `plan.md` / `tasks.md` updates first — those three docs are the source of truth and the traceability matrix.

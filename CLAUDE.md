# CLAUDE.md

Repo-wide guidance for Claude Code. Top-level entry point — read first, then drop into the relevant sub-package CLAUDE.md.

> Sub-package guides:
> - [`backend/CLAUDE.md`](./backend/CLAUDE.md) — FastAPI + async SQLAlchemy + OpenRouter
> - [`webapp/CLAUDE.md`](./webapp/CLAUDE.md) — Vue 3 + Pinia + Vite

## Read first

- [`docs/principles.md`](./docs/principles.md) — the four engineering principles (Think / Simplicity / Surgical / Goal-Driven). Override defaults; apply on every change.
- [`docs/PROJECT.md`](./docs/PROJECT.md) — canonical project handbook: architecture, data-flow, stack, data model, full API surface, feature/roadmap status, glossary.
- [`docs/FEATURES.md`](./docs/FEATURES.md) — exhaustive feature catalog by capability area (what the product does, with code anchors + surfaces).
- [`docs/README.md`](./docs/README.md) — the docs hub (navigable index of everything below).
- [`docs/contract/spec.md`](./docs/contract/spec.md) — requirements (`US-*`, `FR-*`, `NFR-*`).
- [`docs/contract/plan.md`](./docs/contract/plan.md) — architecture decisions (§1..§12).
- [`docs/contract/tasks.md`](./docs/contract/tasks.md) — task breakdown + traceability matrix (`T001..`).

## Repo map

```
intercom-ticket-management/
├── backend/        FastAPI service + SQLite + OpenRouter integration       ← see backend/CLAUDE.md
├── webapp/         Vue 3 SPA — the kanban board + admin pages              ← see webapp/CLAUDE.md
├── docs/           📚 Hub (docs/README.md) · handbook (PROJECT/FEATURES) · contract/ (spec·plan·tasks) · principles · superpowers/ design records
├── scripts/        dev.ps1 (single-command launcher), seed-db.ps1/.sh
├── design_bundle/  Static design assets referenced by DESIGN.md
└── README.md       Quickstart + API surface table
```

## Quality gates (run before merge)

| Package    | Gate                                                                                                          |
|------------|---------------------------------------------------------------------------------------------------------------|
| backend    | `ruff check app tests && ruff format --check app tests && mypy app && pytest -q`                              |
| webapp     | `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`                      |

## Cross-package invariants

The ones a Claude touching multiple packages keeps getting wrong if not flagged:

1. **Backend owns Intercom ingestion via an Access Token.** The backend polls the official `api.intercom.io` REST API with a workspace Bearer token from `backend/.env` (`INTERCOM_ACCESS_TOKEN`), normalizes payloads in `backend/app/services/intercom_normalizer.py`, and ingests them through `run_sync_cycle` (`backend/app/services/sync.py`). A background poller (interval-gated, default off) + `POST /tickets/sync` drive it. The backend `IntercomClient` is the only ingestion path; no client surface touches Intercom.
2. **`HydratedTicket` shape spans two packages** (`backend/app/schemas.py:HydratedTicket` → `webapp/src/types/api.ts`). The producer is the backend normalizer (`backend/app/services/intercom_normalizer.py:normalize_conversation`), not any client surface. Edit the backend schema + webapp type together or break the board.
3. **`part_type` mapping (official API).** Intercom conversation parts carry a `part_type` string: `comment` (+ customer author → `parts[]`, admin/bot author → `parts[]` with `is_admin`), `note` → `internal_notes[]`, `assignment`/`open`/`close`/`snoozed`/… → skipped. The opening message lives on `source` and is emitted as the first part. Unknown `part_type` → skipped + logged (`intercom.unknown_part_type`). Stable + documented (replaces the old reverse-engineered numeric `renderable_type` codes).
4. **`parts[]` is customer-visible (fed to AI); `internal_notes[]` is team-only (never fed to AI).** Keep them separated end-to-end. The normalizer enforces this via `part_type='note'` → `internal_notes[]`.
5. **Naive UTC in DB; `Z`-suffixed ISO on the wire.** Pydantic `UTCDatetime` / `NaiveUTCDatetime` enforce this; JS clients depend on it.
6. **AI cache key = content signature (last customer-visible part timestamp), not Intercom `updated_at`.** Internal teammate notes must not bust cache.
7. **Fallback `CategorizationResult` rows are never cached.** Caching a fallback poisons the ticket until a new customer message arrives.
8. **`title_user_edited` / `summary_user_edited` are sticky across re-syncs.** Backend ingest (`_upsert_ticket`) must preserve operator edits when the poller re-fetches a conversation.
9. **`MAX_BULK_IDS = 200`.** Backend constant (`backend/app/config.py`), webapp pre-flight warning. Bump together.
10. **`tickets.resolved_at` ⇔ `resolved_source`** (XOR CheckConstraint). `resolved_source ∈ {'manual', 'intercom_closed', 'non_actionable', 'ai_resolved'}` (`ai_resolved` = AI auto-close under the operator's auto-resolve toggle, migration 0012). Non-actionable renders as its own Kanban column (webapp) — split from Resolved at the view layer (`tickets.nonActionableTickets` / `pureResolvedTickets` getters); storage stays unified. Reopen path clears both. A non-actionable ticket may carry a structured `non_actionable_kind` (`auto_reply`/`thanks`/`spam`/`out_of_office`/`other`) on `tickets` + `ai_cache` (AI-derived, board-state only — not on `HydratedTicket`; invariant #2 untouched); it is CHECK-coupled to `resolved_source='non_actionable'` and cleared on every reopen path with the resolution pair (migration 0020 / T107).
11. **Drag-out reopen is atomic.** Setting an override on a resolved ticket clears `resolved_at` + `resolved_source` in the same transaction.
12. **Singleton `Settings` row enforced by `CHECK (id = 1)`.** `init_db` inserts it on first boot.
13. **Playbooks are durable operator knowledge, not cache.** `playbooks` rows
    survive ingest / re-sync untouched and are never content-signature-keyed.
    The AI drafter (`POST /playbooks/draft`) reads `parts` + operator notes
    only — never `internal_notes` (see #4). A ticket sees playbooks for its
    *effective* category (override beats AI).
14. **Parked is board-state, not a conversation field.** `parked_at` /
    `parked_until` / `parked_reason` live on `TicketSchema` (the board
    response), never on `HydratedTicket` (invariant #2 untouched). The
    trio is XOR-locked (all-set or all-null) and a ticket is never both parked
    and resolved; every resolve path calls `clear_parked`. "Ready to resume"
    (`parked_until ≤ now`) is derived on read, never stored — no scheduler.
    `_upsert_ticket` never writes the trio, so parked state survives re-sync by
    construction (cf. #8). Parked tickets are excluded from the live category
    columns and surfaced via a parked-only filter chip (roadmap 4.1 / T106).
    Reason `other` may carry an optional free-text `parked_note` (≤200 chars),
    cleared with the trio.
15. **Auth required on every route except the allowlist.** `get_current_user` is
    applied to every router. The explicit allowlist is: `/health`, `/auth/login`,
    `/auth/refresh`. Attachment image `GET` endpoints also accept the session
    cookie in lieu of a Bearer token; all mutation endpoints accept Bearer only.
    Adding a new router without the dependency is a security regression.
16. **Session = stateless access JWT + DB-backed rotating refresh token with
    reuse-detection.** The access JWT (~30 min, HS256) is verified offline per
    request. The refresh token is stored as a `sha256` hash only
    (`sessions.refresh_token_hash`); the raw token is never written to the DB or
    logs. On every `POST /auth/refresh` the token rotates: the old hash moves to
    `prev_refresh_token_hash`. Replaying a rotated-away token matches
    `prev_refresh_token_hash` and **immediately revokes the session**
    (reuse-detection) — there is no session-family id, so this single row *is*
    the chain. The branch logs `refresh_reuse_detected` (WARNING) so a genuine
    replay is visible in the logs. Two browser tabs sharing one cookie, or a
    double-fired refresh, can trip this and force a re-login — accepted for
    small-team scope (plan §19 double-refresh tradeoff, NFR-014). Because the
    access JWT is verified offline (no per-request DB read), `is_active` is not
    re-checked mid-token: a deactivated user keeps a valid access token until it
    expires (<= access TTL), and hard revocation lands on the next refresh
    (`rotate_session` rejects an inactive user). `get_current_user` documents
    this at the enforcement point.
17. **Attribution + assignment fields are board-state only — never on
    `HydratedTicket`.** `tickets.resolved_by` / `overrides.acted_by` /
    `tickets.assigned_to` / `tickets.assigned_at` live on `TicketSchema` /
    `Override` (the board response layer) and are composed via a `users` join at
    read time as `UserRef {id, name}`. They are never on `HydratedTicket`
    (invariant #2 untouched). AI-driven and system paths leave attribution null;
    `_upsert_ticket` never writes the attribution/assignment fields, so they
    survive re-sync by construction.
18. **Per-user follow-ups/notes are DEFERRED (Phase 4). Settings stays shared.**
    `note_entries.user_id` does not yet exist as an active column. The `settings`
    singleton row (`CHECK (id = 1)`) is team-wide — every operator reads and
    writes the same settings. Do not add per-user settings or per-user follow-up
    filtering until Phase 4 is explicitly designed and tasks.md is updated.
19. **No password is ever stored or logged.** Login proxies straight to OnlySales;
    our backend only persists the Fernet-encrypted upstream OnlySales refresh
    token (`sessions.onlysales_refresh_encrypted`). No password field exists on
    any model. Never log `request.body()` on the login endpoint or any auth
    path.

## Subagent doctrine

- Delegate broad codebase searches (>3 grep/glob rounds, "find every place that does X") to `Agent(subagent_type=Explore)` so the main context stays focused on the task. Direct `Grep` / `Glob` for targeted, single-file lookups.
- Delegate independent parallel research (e.g. "summarise backend/app/services/sync.py + backend/app/clients/intercom.py side-by-side") to two `Agent` calls in one message. Don't run them sequentially in the main thread.
- Do **not** delegate the actual edit. Cross-package edits (HydratedTicket, the `part_type` mapping, MAX_BULK_IDS) must run in the main thread with the corresponding skill loaded so the invariant guardrails apply.
- Do **not** delegate when the answer is already in `docs/PROJECT.md`, `docs/contract/spec.md`, `docs/contract/plan.md`, or `docs/contract/tasks.md`. Read those directly — they exist precisely to short-circuit exploration.

## Scope guardrails

- **Auth + multi-user are IN scope** (charter pivot — MHU). The tool is a hosted, authenticated, shared-team board. Multiple operators sign in with OnlySales credentials; one shared ticket pool, one taxonomy, one settings row — all team-wide. Identity is delegated to OnlySales (our backend never stores a password).
- **Multi-tenancy is OUT of scope.** No `tenant_id`, no per-tenant data isolation, no per-user Intercom tokens. Every authenticated user sees the same board.
- **Per-user follow-ups/notes** are deferred (Phase 4 — `note_entries.user_id` not yet active). `Settings` remains a shared team-wide singleton.
- **pgvector/semantic layer on Postgres** is deferred — hosted v1 runs embeddings/clustering off.
- Two packages, two stacks, intentionally. **Don't merge them.** webapp = Vue 3 + Vite (SPA); backend = FastAPI (HTTP). No monorepo tool, shared package, codegen step.
- Cross-package changes (schema, ingest shape, API contract) ship in one PR. Don't merge backend half of a contract change without the webapp half.

## When in doubt

1. Read `docs/contract/spec.md` for the *what*.
2. Read `docs/contract/plan.md` for the *how*.
3. Read the sub-package `CLAUDE.md` for stack-specific rules.
4. Grep for the relevant T-number in `docs/contract/tasks.md` to find the implementation footprint.
5. If still unclear — ask. Cost of a clarifying question = one round-trip; cost of a wrong guess across two packages = much higher.

## Don't

- Don't add a SECOND Intercom integration. The backend `IntercomClient` (`backend/app/clients/intercom.py`) is the only ingestion path; don't give the webapp Intercom access.
- Don't introduce a monorepo tool / shared package / codegen step.
- Don't deploy this anywhere (no Dockerfile, no CI/CD, no production config). *(Hosted deployment is the operator's concern — we ship no infra config.)*
- Don't add **multi-tenancy** (`tenant_id`, per-tenant data isolation). Auth + multi-user are in scope; tenant isolation is explicitly out. Don't add RBAC enforcement beyond what is already stored in `scope` (captured for a future phase, not enforced in v1).
- Don't store or log passwords, raw refresh tokens, or the upstream OnlySales token in plaintext. Login proxies to OnlySales; only the Fernet-encrypted upstream refresh token is persisted.
- Don't extend the surface area without `docs/contract/spec.md` / `docs/contract/plan.md` / `docs/contract/tasks.md` updates first — those three docs are the source of truth and the traceability matrix.

## Parallel sessions & worktrees

Multiple Claude sessions may run on this repo at once. Claude Code has NO
cross-session file lock — two sessions on the same branch will silently
clobber each other's edits. So **each concurrent feature/task gets its own
git worktree**: isolated working dir, own branch, shared `.git`.

**When to create one.** Before starting a distinct feature/bugfix that could
run alongside another session — anything that earns its own feature branch.
Use the `EnterWorktree` tool at the start of the task (or the user launches
with `claude --worktree <slug>`); it creates `.claude/worktrees/<slug>/` on a
branch off `origin/HEAD`, and clean worktrees auto-remove on exit. For parallel
subagents doing real edits, set `isolation: worktree`. Skip worktrees for quick
single-session edits, doc tweaks, or when no other session is active.

**Worktrees isolate the filesystem, NOT git history.** These shared files still
conflict at MERGE time — serialize or pre-assign them across sessions:

- `backend/alembic/versions/` — linear Alembic revision chain with sequential
  numeric prefixes (`0001_…` upward). Two sessions branching off the same head
  create colliding revisions / multiple Alembic heads. Only ONE session adds a
  migration at a time, or pre-assign the next number + `down_revision`.
- `backend/app/main.py` (`include_router(...)` block) + `backend/app/routers/__init__.py`
  — the router registry. Every new endpoint appends here; coordinate the inserts.
- The `HydratedTicket` contract — `backend/app/schemas.py` ↔
  `webapp/src/types/api.ts` (invariant #2), produced by
  `backend/app/services/intercom_normalizer.py`. A shape change touches the
  schema, the normalizer, and the webapp type; don't split it across parallel
  sessions.
- `webapp/package-lock.json` — never hand-merge; re-run `npm install` (in
  `webapp/`) after merge. Backend has no lockfile (pip `requirements.txt`).
- Single-source docs — `docs/contract/spec.md`, `docs/contract/plan.md`, `docs/contract/tasks.md`, `docs/PROJECT.md`,
  this `CLAUDE.md`. Append-heavy; coordinate or expect textual conflicts.

**Keep branches short (<~2 days) and rebase on the default branch daily.**
Divergence is what makes merges painful; short-lived branches are the biggest
conflict reducer.

Supporting setup: `.claude/worktrees/` is gitignored,
`CLAUDE_CODE_GLOB_NO_IGNORE=false` keeps Glob from returning duplicate matches
across nested worktrees, and `.worktreeinclude` copies the repo's gitignored
config/secret files (`backend/.env`) into each new worktree. Each worktree
still needs its own dependency install — `backend` venv + `npm install` in
`webapp` — those are not copied (too heavy).

# Intercom Triage — Project Knowledge

> **Canonical living handbook.** Read this first for orientation: what the system
> is, how it's built, and where it stands. This doc is the single home for the
> durable knowledge that used to be scattered across `architecture.md`,
> `ROADMAP.md`, and the README.
>
> **It points, it does not duplicate.** The contract source of truth stays in
> `contract/spec.md` (what) / `contract/plan.md` (how) / `contract/tasks.md` (traceability). The
> per-change rules + the 19 cross-package invariants stay in the `CLAUDE.md`
> hierarchy (auto-loaded every session). When this doc and one of those
> disagree, *they* win — fix this doc.

---

## 1. What it is & scope

A hosted, authenticated, shared-team tool that pre-categorizes and summarizes
recent Intercom conversations so operators scan and route from one Kanban board
instead of opening each ticket. Multiple operators sign in with their OnlySales
credentials and work one shared ticket pool, one taxonomy, one settings row.
Two packages, two stacks (localhost in dev).

**Charter (the constraint is the product).** One Intercom workspace, one
taxonomy, one shared board, many operators. Identity is delegated to OnlySales —
the backend never stores a password. **In scope (charter pivot — MHU):** auth,
multi-user collaboration, ticket assignment + My Queue, attribution, hosted
deployment. **Out of scope by design:** multi-tenancy (no `tenant_id`, no
per-tenant data isolation — every authenticated user sees the same board),
per-user Intercom tokens, RBAC enforcement beyond the stored `scope`, replying
from the tool, team leaderboards, CSAT, autonomous action agents, multi-channel.
Per-user follow-ups/notes (`note_entries.user_id`) and the pgvector/semantic
layer are deferred (Phase 4). We ship no infra config — hosted deployment is the
operator's concern. See the root [`CLAUDE.md`](../CLAUDE.md) "Scope guardrails" /
"Don't" sections.

---

## 2. Two packages at a glance

| Package | Stack | Role | Guide |
|---|---|---|---|
| `backend/` | FastAPI + async SQLAlchemy 2.0 + SQLite + OpenRouter + Intercom REST | **The ingestion path + auth.** Polls `api.intercom.io` with an Access Token, normalizes, categorizes (cache-aware) against the operator's taxonomy, stores, and serves the board. Embeddings, clustering, playbooks, stats. Owns auth: OnlySales-delegated login + rotating DB-backed sessions; guards every route. | [`backend/CLAUDE.md`](../backend/CLAUDE.md) |
| `webapp/` | Vue 3 + Pinia + Vite + TS (no router) | The Kanban board + admin/settings pages. Optimistic-update Pinia store is the heart. | [`webapp/CLAUDE.md`](../webapp/CLAUDE.md), [`webapp/DESIGN.md`](../webapp/DESIGN.md) |

Two stacks intentionally — **do not merge them.** No monorepo tool, shared
package, or codegen step.

---

## 3. Architecture & data flow

The backend polls Intercom's official `api.intercom.io` REST API with a
workspace Access Token (`app/clients/intercom.py`), normalizes payloads to
`HydratedTicket` (`app/services/intercom_normalizer.py`), and ingests via
`app/services/sync.py:run_sync_cycle` — driven by a background poller and a
manual `POST /tickets/sync`. It categorizes via OpenRouter (semaphore-bounded,
cache-aware on the customer-visible content signature) against the curated
taxonomy, stores rows in SQLite, and serves the board via `GET /tickets`. The
webapp reads from the backend; mutations (override, resolve, follow-up, bulk,
park…) go back through the same HTTP API.

```
        Intercom official REST API (api.intercom.io, Access Token)
                                  │
                                  ▼
                  ┌──────────────────────────────────┐
                  │ backend: clients/intercom.py +    │
                  │ services/intercom_normalizer.py + │
                  │ services/sync.py (poll / sync)    │
                  └──────────────┬───────────────────┘
                                 │ categorize + cache + store
                                 ▼
                          GET /tickets
                            (webapp)
                  PATCH/PUT/POST: override · resolve · reopen · followup ·
                                 note · bulk · ai-resolve · park · dismiss-chip
```

Server-side skip-known (an internal `get_sync_state`) skips the per-conversation
detail fetch for conversations already stored unchanged.

**Auth boundary.** Every route except the allowlist (`/health`, `/auth/login`,
`/auth/refresh`, `/auth/logout`) requires a bearer access JWT via
`get_current_user` (inv #15). Login proxies to OnlySales; the backend mirrors
the user, issues a stateless access JWT (~30 min) + a DB-backed rotating refresh
token (httpOnly cookie), and stamps the acting operator on manual resolve /
recategorize / assign (inv #17). The webapp gates the whole board behind login
and refreshes the access token on 401.

---

## 4. Run the stack

```powershell
# Backend on 127.0.0.1:4000, webapp on 127.0.0.1:5173 (proxies /api → :4000).
# Runs pip/npm install (idempotent), then a Windows Terminal split-pane.
.\scripts\dev.ps1
```

First boot: backend creates `backend/data/triage.db`, seeds 7 default
categories (Urgent, Bug, Feature Request, Question, Billing, Complaint, Other),
inserts the singleton settings row. A missing `OPENROUTER_API_KEY` does **not**
block startup — `/health` reports it; ingest writes every ticket to the
fallback category until the key is set.

---

## 5. Stack & versions

| Area | Versions |
|---|---|
| backend | Python 3.11+ (3.12 tested), FastAPI 0.135.4, SQLAlchemy 2.0 (async), Alembic, pydantic v2, httpx |
| embeddings/ML | sentence-transformers 5.5.1 + torch 2.8.0 (CPU, `all-MiniLM-L6-v2`, 384-dim), sqlite-vec 0.1.9 (pre-v1, pinned exact), scikit-learn 1.6.1 (HDBSCAN clustering) |
| webapp | Vue 3.5, Pinia 2.3, Vite 6, TypeScript 5.6, vue-tsc, ESLint 9, Prettier 3, Vitest 2 |
| AI | OpenRouter (`anthropic/claude-sonnet-4.5` default; swap via `OPENROUTER_MODEL`) |
| auth | OnlySales-delegated identity (`pyapi.onlysales.io`) · HS256 access JWT (PyJWT) · Fernet (`cryptography`) encrypts the upstream refresh token at rest · sha256 refresh-hash rotation |
| storage | SQLite (default, `backend/data/triage.db`) · Postgres swap via `DATABASE_URL` |

---

## 6. Data model

SQLite (Postgres-swappable). Naive-UTC timestamps in the DB, `Z`-suffixed on
the wire (invariant #5). Migrations are forward-only Alembic revisions
(`backend/alembic/versions/0001…0025`; auth tables landed 0021–0022,
attribution/assignment 0023–0025).

| Table | Purpose / key constraints |
|---|---|
| `tickets` | PK = Intercom string id. `parts` (customer-visible) + `internal_notes` (team-only). `resolved_at ⇔ resolved_source` XOR (`manual`/`intercom_closed`/`non_actionable`/`ai_resolved`). `non_actionable_kind` CHECK-coupled to `resolved_source='non_actionable'`. Parked trio (`parked_at`/`parked_until`/`parked_reason`) XOR-locked, never co-resolved. `title_user_edited`/`summary_user_edited` sticky. Attribution/assignment (`resolved_by`/`assigned_to`→`users`, `assigned_to ⇔ assigned_at` XOR) are board-state, composed via a join (inv #17). |
| `ai_cache` | Per-ticket categorization cache. `category_id ⊕ proposal_id` XOR. `ticket_updated_at` stores the **content signature** (last customer-visible part timestamp), not Intercom `updated_at`. Fallback results never cached. Carries AI facets + `non_actionable_kind`. |
| `categories` | `is_active=False`+`archived_at` archives. Unique name among active (partial index). Exactly one `is_fallback=True`. |
| `category_proposals` | Pending → approved/merged/rejected. Partial-unique name while pending. |
| `overrides` | PK = ticket_id. Manual category override; beats AI iff `tickets.updated_at ≤ set_at`. `acted_by`→`users` (attribution, inv #17). Drag-out reopen clears resolution atomically here. |
| `rejected_proposal_signatures` | Normalized signatures of rejected names; pipeline raises → fallback on match. |
| `followups` | PK = ticket_id; PUT upserts. No FK (Intercom ids churn). |
| `ticket_notes` | Per-ticket free-text note (legacy single-body). Empty body = deleted row. |
| `note_entries` | Append-only investigation log; `timer_min` upserts a followup same transaction. Soft-delete. |
| `note_attachments` | Polymorphic owner (`entry`/`ticket`), content-addressed by sha256 on disk. Soft-delete + GC sweep. |
| `playbooks` | Category-scoped durable operator knowledge. Never content-signature-keyed; survives re-sync. |
| `snippets` | Global canned replies; `{{var}}` substitution client-side. |
| `ticket_embeddings` | 384-dim vectors (sqlite-vec). Separate store — never touches `ai_cache`. |
| `ticket_clusters` / `ticket_cluster_members` | Offline recurring-issue clustering snapshot. |
| `settings` | Singleton (`CHECK id = 1`). Filter + AI flags; `init_db` inserts it. Team-wide — no per-user settings (inv #18). |
| `users` | Local mirror of an OnlySales identity (`onlysales_id`/`email`/`name`/`scope`/`is_active`/`last_login_at`). No password column (inv #19). FK target for attribution/assignment. |
| `sessions` | Refresh-token ledger: `refresh_token_hash` + `prev_refresh_token_hash` (reuse-detection), Fernet-encrypted `onlysales_refresh_encrypted`, `issued_at`/`expires_at`/`revoked_at`/`last_used_at`. Raw tokens never stored (inv #16/#19). |

---

## 7. The 19 cross-package invariants (index)

**Canonical text + rationale: root [`CLAUDE.md`](../CLAUDE.md) "Cross-package
invariants."** (`scripts/check-invariants.ps1` lingers as a manual checker but is
no longer wired as a hook — dropped in commit `43792e6`.) One-line index only:

1. Backend owns Intercom ingestion via an Access Token (`api.intercom.io`); the backend client is the only ingestion path.
2. `HydratedTicket` spans two packages (backend schema ↔ webapp type), produced by the backend normalizer — edit together or break the board.
3. `part_type` mapping (official API): `comment`→`parts[]`, `note`→`internal_notes[]`, events skipped, `source` first.
4. `parts[]` is customer-visible (fed to AI); `internal_notes[]` is team-only (never fed to AI).
5. Naive UTC in DB; `Z`-suffixed ISO on the wire.
6. AI cache key = content signature (last customer-visible part timestamp), not Intercom `updated_at`.
7. Fallback `CategorizationResult` rows are never cached.
8. `title_user_edited` / `summary_user_edited` are sticky across re-syncs.
9. `MAX_BULK_IDS = 200` — backend constant + webapp pre-flight; bump together.
10. `resolved_at ⇔ resolved_source` XOR; `non_actionable_kind` coupled to `non_actionable`.
11. Drag-out reopen is atomic (clears `resolved_at` + `resolved_source` one transaction).
12. Singleton `Settings` row, `CHECK (id = 1)`.
13. Playbooks are durable operator knowledge, not cache.
14. Parked is board-state (trio on the board response, not `HydratedTicket`), XOR-locked.
15. Auth required on every route except the allowlist (`/health`, `/auth/login`, `/auth/refresh`, `/auth/logout`); attachment image GETs also accept the session cookie.
16. Session = stateless access JWT + DB-backed rotating refresh token with reuse-detection; raw tokens never stored; `is_active` not re-checked mid-token (hard revocation lands on refresh).
17. Attribution + assignment (`resolved_by`/`acted_by`/`assigned_to`/`assigned_at` as `UserRef`) are board-state only — never on `HydratedTicket` (#2 untouched).
18. Per-user follow-ups/notes are DEFERRED (Phase 4 — `note_entries.user_id` absent); `Settings` stays a shared team-wide singleton.
19. No password is ever stored or logged; only the Fernet-encrypted upstream OnlySales refresh token is persisted.

---

## 8. API surface

Interactive docs at <http://localhost:4000/docs> while the backend runs.
Router footprint: `backend/app/routers/`.

| Group | Endpoints |
|---|---|
| health / metrics | `GET /health` · `GET /metrics` |
| auth / users | `POST /auth/login` · `/auth/refresh` · `/auth/logout` · `/auth/logout-all` · `GET /auth/me` · `GET /users` |
| categories | `GET /categories` · `POST /categories` · `PATCH /{id}` · `POST /{id}/archive` · `POST /{src}/merge-into/{dst}` |
| proposals | `GET /proposals` · `POST /{id}/approve` · `/merge-into/{cat}` · `/reject` |
| tickets (read/ingest) | `GET /tickets` · `POST /tickets/sync` (run a poll cycle) · `POST /tickets/ingest` (internal) |
| tickets (single) | `PATCH /{id}/category` · `PATCH /{id}` · `POST /{id}/resolve` · `/non-actionable` · `/reopen` · `/park` · `/unpark` · `/dismiss-chip` · `PATCH /{id}/ai-resolve` · `PATCH /{id}/assign` |
| tickets (bulk, capped 200) | `POST /tickets/bulk/resolve` · `/reopen` · `/dismiss-chip` · `/non-actionable` · `/park` · `/unpark` · `PATCH /tickets/bulk/category` · `PATCH /tickets/bulk/assign` — each returns `{ok_ids, failed[]}` |
| followups | `GET /followups` · `PUT /followups/bulk` · `DELETE /followups/bulk` · `PUT /{id}` · `POST /{id}/snooze` · `/mark-fired` · `DELETE /{id}` |
| notes | `GET /notes` · `PUT /notes/{id}` |
| note entries | `GET /notes/entries` · `GET /notes/entries/{ticket_id}` · `POST /notes/entries` · `DELETE /notes/entries/{id}` |
| attachments | `POST /attachments` · `GET /attachments?ticket_id=…` · `GET /{id}/raw` · `/thumb` · `DELETE /{id}` |
| settings | `GET /settings` · `PUT /settings` |
| snippets | `GET /snippets` · `POST /snippets` · `PATCH /{id}` · `POST /{id}/archive` · `/restore` |
| stats | `GET /stats?window_days=…` |
| playbooks | `GET /playbooks` · `GET /playbooks/suggested?ticket_id=…` · `POST /playbooks` · `POST /playbooks/draft` · `/draft-reply` · `PATCH /{id}` · `POST /{id}/archive` · `/restore` |
| clusters | `GET /clusters` · `GET /clusters/gaps` · `POST /clusters/recompute` |

---

## 9. AI pipeline (brief)

`backend/app/ai/`. On ingest, uncached tickets fan out to OpenRouter under an
`asyncio.Semaphore(AI_CONCURRENCY)`. Each call sends the operator's category
set + pending proposals + rejected signatures + the conversation; response is
one JSON object (`temperature=0.1`, `response_format=json_object`) choosing
`existing` / `pending_proposal` / `new_proposal` plus summary, confidence,
priority, sentiment, labels, resolution verdict, and `non_actionable_kind`.
Retries on 429/5xx/transient with jittered backoff. Any malformed shape →
per-ticket fallback (the batch never aborts); fallbacks are never cached
(invariant #7). Optional opt-in **model cascade** (cheap model first, escalate
on low confidence). **Embeddings** (separate `ticket_embeddings` store) power
few-shot categorization from confirmed overrides, RAG draft replies, and offline
clustering — all reading customer-visible `parts[]` + operator notes only, never
`internal_notes` (invariant #4).

---

## 10. Feature & roadmap status

The project is feature-complete against `contract/spec.md` v2.0 (the MHU charter
pivot — auth, multi-user, hosted). The 2026-05 roadmap is now an execution log
(full ledger with commit SHAs + the original phase tables:
[`docs/_archive/ROADMAP.md`](./_archive/ROADMAP.md)).

Full per-feature catalog (every capability, by area, with code anchors):
**[`docs/FEATURES.md`](./FEATURES.md)**.

**Shipped to `main`:** Phases 0–3 + 4.1 (parked, T106) + 4.2 (`non_actionable_kind`,
T107) + robustness R.1–R.5 + **MHU (auth, multi-user, ticket assignment + My
Queue, attribution, security hardening — PR #10, US-040..043, T161..T171)**.
That covers: priority/sentiment/multi-label, aging
indicators, keyboard triage, saved views, priority-sorted queue, stats
dashboard, cost meter, snippets, bulk pre-flight diff, structured JSON
outputs, model cascade, needs-review lane, the local embedding layer, few-shot
categorization, RAG draft replies, recurring-issue clustering, playbook-gap
detection, playbook auto-match, OnlySales-delegated login, rotating sessions
with reuse-detection, per-ticket + bulk assignment, and operator attribution.

**Open backlog** (the only live forward items):

| ID | Item | Notes |
|---|---|---|
| 4.3 / **T100** | Webhook + SSE live updates | `conversation.user.created`/`replied` → push to webapp instead of poll-on-open. Heaviest deferred feature. |

---

## 11. Quality gates (run before merge)

| Package | Gate | Skill |
|---|---|---|
| backend | `ruff check app tests && ruff format --check app tests && mypy app && pytest -q` | `/qa-backend` |
| webapp | `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build` | `/qa-webapp` |

`/qa-all` runs backend + webapp back-to-back. Last full run (2026-06-08, PR #10
merge): backend 518 tests, webapp 248 tests — all green.

---

## 12. Glossary

- **HydratedTicket** — the normalized conversation shape the backend normalizer produces and stores; spans backend schema ↔ webapp type (invariant #2).
- **part_type** — Intercom's official conversation-part type: `comment`→`parts[]` (customer or admin), `note`→`internal_notes[]`, events skipped; the opening `source` message is the first part (invariant #3). Replaced the old reverse-engineered numeric `renderable_type` codes.
- **content signature** — the last customer-visible part timestamp; the AI cache key (invariant #6). Teammate notes/assignments advance Intercom `updated_at` but must not bust cache.
- **override beats AI** — a manual category override wins while `tickets.updated_at ≤ override.set_at`.
- **proposal** — an AI-suggested new category, pending operator approve/merge/reject.
- **fallback** — the catch-all category a ticket lands in when AI is unavailable or returns garbage; fallback results are never cached.
- **resolved_source** — why a ticket is resolved: `manual` / `intercom_closed` / `non_actionable` / `ai_resolved`.
- **non-actionable** — a resolved sub-state (spam / thanks / auto-reply / out-of-office / other); its own board column, split at the view layer.
- **parked** — board-state "waiting on customer/third-party/internal" with a wake time; XOR-locked trio, never co-resolved, surfaced via a filter chip.
- **playbook** — durable, category-scoped operator response recipe; not cache, survives re-sync (invariant #13).
- **snippet** — global canned reply with `{{var}}` slots; lighter than a playbook.
- **session** — OnlySales-delegated login state: a stateless HS256 access JWT (~30 min, verified offline) + a DB-backed refresh token that rotates on every `/auth/refresh`; replaying a rotated token trips reuse-detection and revokes the session (inv #16).
- **attribution** — the operator stamped on a manual action: `resolved_by` (who resolved), `acted_by` (who overrode the category), `assigned_to` (assignee). Board-state only, composed via a `users` join (inv #17).
- **My Queue** — the board lane filtered to tickets assigned to the signed-in operator.

---

## 13. Documentation map

Where knowledge lives now, and the boundary this handbook respects:

| Doc | Owns | Status |
|---|---|---|
| **`docs/PROJECT.md`** (this) | System orientation: architecture, data-flow, stack, data model, API surface, feature status, glossary. | Canonical living handbook. |
| **`docs/FEATURES.md`** | Exhaustive feature catalog by capability area, with code anchors + surfaces. | Canonical feature reference. |
| `CLAUDE.md` (+ `backend/`, `webapp/`) | Per-change rules + the 19 invariants. Auto-loaded every session. | Canonical, authoritative. **Not folded here.** |
| `contract/spec.md` / `contract/plan.md` / `contract/tasks.md` | Requirements (US/FR/NFR, US-001..043) · architecture decisions (§1–§19) · traceability matrix (T001–T171). | Contract source of truth. **Not folded here** (charter-protected). |
| `docs/principles.md` | The four engineering principles. | Live; referenced by every sub-package CLAUDE.md. |
| `webapp/DESIGN.md` | Design-system source of truth (tokens/palette/components). | Live. |
| `*/README.md`, `SECURITY.md` | Per-package quickstart + secrets/threat model. | Live reference. |
| `docs/superpowers/specs/` + `plans/` | Per-feature design records ("why we built it this way"); cited by shipped-code docstrings. | Kept in place — the design archive. |
| `docs/_archive/` | Retired point-in-time artifacts: the 2026-05 audit cycle, resolved package reviews, the verbatim `architecture.md` + `ROADMAP.md`, the per-phase task breakdowns, roadmap-execution dispatch contracts. | History only; superseded by this doc + `tasks.md`. |

**Boundary rule:** one fact, one home. This handbook *links* to CLAUDE.md /
spec / plan / tasks rather than copying them — duplication is exactly the drift
that prompted the consolidation.

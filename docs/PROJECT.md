# Intercom Triage — Project Knowledge

> **Canonical living handbook.** Read this first for orientation: what the system
> is, how it's built, and where it stands. This doc is the single home for the
> durable knowledge that used to be scattered across `architecture.md`,
> `ROADMAP.md`, and the README.
>
> **It points, it does not duplicate.** The contract source of truth stays in
> `spec.md` (what) / `plan.md` (how) / `tasks.md` (traceability). The
> per-change rules + the 14 cross-package invariants stay in the `CLAUDE.md`
> hierarchy (auto-loaded every session). When this doc and one of those
> disagree, *they* win — fix this doc.

---

## 1. What it is & scope

A local, single-operator tool that pre-categorizes and summarizes recent
Intercom conversations so the operator scans and routes from one Kanban board
instead of opening each ticket. Three packages, three stacks, all on
`localhost`.

**Charter (the constraint is the product).** One workspace, one taxonomy, one
operator, one machine. **No** multi-tenancy, auth, RBAC, cloud deploy, Docker,
CI/CD, hosted observability, or public surface. Out-of-scope-by-design:
team leaderboards, CSAT, autonomous action agents, multi-channel. See the root
[`CLAUDE.md`](../CLAUDE.md) "Scope guardrails" / "Don't" sections.

---

## 2. Three packages at a glance

| Package | Stack | Role | Guide |
|---|---|---|---|
| `extension/` | Plain ES modules, Chrome MV3, no build | **The only ingestion path.** Scrapes Intercom's undocumented `ember/` API from the operator's logged-in session, normalizes to `HydratedTicket[]`, POSTs to the backend. | [`extension/CLAUDE.md`](../extension/CLAUDE.md) |
| `backend/` | FastAPI + async SQLAlchemy 2.0 + SQLite + OpenRouter | Categorize (cache-aware) against the operator's taxonomy, store, and serve the board. Embeddings, clustering, playbooks, stats. | [`backend/CLAUDE.md`](../backend/CLAUDE.md) |
| `webapp/` | Vue 3 + Pinia + Vite + TS (no router) | The Kanban board + admin/settings pages. Optimistic-update Pinia store is the heart. | [`webapp/CLAUDE.md`](../webapp/CLAUDE.md), [`webapp/DESIGN.md`](../webapp/DESIGN.md) |

Three stacks intentionally — **do not merge them.** No monorepo tool, shared
package, or codegen step.

---

## 3. Architecture & data flow

The operator signs into Intercom in Chrome. The extension scrapes conversations
from the logged-in session via Intercom's `ember/` API and POSTs
`HydratedTicket[]` to `POST /tickets/ingest`. The backend categorizes via
OpenRouter (semaphore-bounded, cache-aware on the customer-visible content
signature) against the curated taxonomy, stores rows in SQLite, and serves the
board via `GET /tickets`. The webapp and the extension popup mini-board both
read from the backend; mutations (override, resolve, follow-up, bulk, park…) go
back through the same HTTP API.

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
              POST /tickets/ingest   (backend categorizes + caches + stores)
                                 │
                          ┌──────┴──────┐
                          ▼             ▼
                  GET /tickets     GET /tickets
                   (webapp)        (popup mini-board)
                  PATCH/PUT/POST: override · resolve · reopen · followup ·
                                 note · bulk · ai-resolve · park · dismiss-chip
```

`GET /tickets/sync-state` returns `{id: updated_at}` so the extension skips the
per-conversation detail fetch for unchanged conversations.

---

## 4. Run the stack

```powershell
# Backend on 127.0.0.1:4000, webapp on 127.0.0.1:5173 (proxies /api → :4000).
# Runs pip/npm install (idempotent), then a Windows Terminal split-pane.
.\scripts\dev.ps1
```

Extension is loaded once manually: `chrome://extensions` → Developer mode →
Load unpacked → select `extension/`. Reload it after every code change.

First boot: backend creates `backend/data/triage.db`, seeds 7 default
categories (Urgent, Bug, Feature Request, Question, Billing, Complaint, Other),
inserts the singleton settings row. A missing `OPENROUTER_API_KEY` does **not**
block startup — `/health` reports it; ingest writes every ticket to the
fallback category until the key is set. The operator enters the Intercom
workspace `app_id` (e.g. `j3dxf22l`) in the popup setup screen once
(`chrome.storage.local.intercomAppId`).

---

## 5. Stack & versions

| Area | Versions |
|---|---|
| backend | Python 3.11+ (3.12 tested), FastAPI 0.135.4, SQLAlchemy 2.0 (async), Alembic, pydantic v2, httpx |
| embeddings/ML | sentence-transformers 5.5.1 + torch 2.8.0 (CPU, `all-MiniLM-L6-v2`, 384-dim), sqlite-vec 0.1.9 (pre-v1, pinned exact), scikit-learn 1.6.1 (HDBSCAN clustering) |
| webapp | Vue 3.5, Pinia 2.3, Vite 6, TypeScript 5.6, vue-tsc, ESLint 9, Prettier 3, Vitest 2 |
| extension | Plain ES modules, MV3, no build step, no dependencies |
| AI | OpenRouter (`anthropic/claude-sonnet-4.5` default; swap via `OPENROUTER_MODEL`) |
| storage | SQLite (default, `backend/data/triage.db`) · Postgres swap via `DATABASE_URL` |

---

## 6. Data model

SQLite (Postgres-swappable). Naive-UTC timestamps in the DB, `Z`-suffixed on
the wire (invariant #5). Migrations are forward-only Alembic revisions
(`backend/alembic/versions/0001…0020`).

| Table | Purpose / key constraints |
|---|---|
| `tickets` | PK = Intercom string id. `parts` (customer-visible) + `internal_notes` (team-only). `resolved_at ⇔ resolved_source` XOR (`manual`/`intercom_closed`/`non_actionable`/`ai_resolved`). `non_actionable_kind` CHECK-coupled to `resolved_source='non_actionable'`. Parked trio (`parked_at`/`parked_until`/`parked_reason`) XOR-locked, never co-resolved. `title_user_edited`/`summary_user_edited` sticky. |
| `ai_cache` | Per-ticket categorization cache. `category_id ⊕ proposal_id` XOR. `ticket_updated_at` stores the **content signature** (last customer-visible part timestamp), not Intercom `updated_at`. Fallback results never cached. Carries AI facets + `non_actionable_kind`. |
| `categories` | `is_active=False`+`archived_at` archives. Unique name among active (partial index). Exactly one `is_fallback=True`. |
| `category_proposals` | Pending → approved/merged/rejected. Partial-unique name while pending. |
| `overrides` | PK = ticket_id. Manual category override; beats AI iff `tickets.updated_at ≤ set_at`. Drag-out reopen clears resolution atomically here. |
| `rejected_proposal_signatures` | Normalized signatures of rejected names; pipeline raises → fallback on match. |
| `followups` | PK = ticket_id; PUT upserts. No FK (Intercom ids churn). |
| `ticket_notes` | Per-ticket free-text note (legacy single-body). Empty body = deleted row. |
| `note_entries` | Append-only investigation log; `timer_min` upserts a followup same transaction. Soft-delete. |
| `note_attachments` | Polymorphic owner (`entry`/`ticket`), content-addressed by sha256 on disk. Soft-delete + GC sweep. |
| `playbooks` | Category-scoped durable operator knowledge. Never content-signature-keyed; survives re-sync. |
| `snippets` | Global canned replies; `{{var}}` substitution client-side. |
| `ticket_embeddings` | 384-dim vectors (sqlite-vec). Separate store — never touches `ai_cache`. |
| `ticket_clusters` / `ticket_cluster_members` | Offline recurring-issue clustering snapshot. |
| `settings` | Singleton (`CHECK id = 1`). Filter + AI flags; `init_db` inserts it. |

---

## 7. The 14 cross-package invariants (index)

**Canonical text + rationale: root [`CLAUDE.md`](../CLAUDE.md) "Cross-package
invariants."** Enforced by `scripts/check-invariants.ps1` (PreToolUse hook).
One-line index only:

1. No Intercom Access Token anywhere — the extension is the only ingestion path.
2. `HydratedTicket` spans three packages — edit all three together or break ingest.
3. `renderable_type` mapping is reverse-engineered (1/12 customer, 2/24 admin, 3 internal note).
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

---

## 8. API surface

Interactive docs at <http://localhost:4000/docs> while the backend runs.
Router footprint: `backend/app/routers/`.

| Group | Endpoints |
|---|---|
| health / metrics | `GET /health` · `GET /metrics` |
| categories | `GET /categories` · `POST /categories` · `PATCH /{id}` · `POST /{id}/archive` · `POST /{src}/merge-into/{dst}` |
| proposals | `GET /proposals` · `POST /{id}/approve` · `/merge-into/{cat}` · `/reject` |
| tickets (read/ingest) | `GET /tickets` · `GET /tickets/sync-state` · `POST /tickets/ingest` |
| tickets (single) | `PATCH /{id}/category` · `PATCH /{id}` · `POST /{id}/resolve` · `/non-actionable` · `/reopen` · `/park` · `/unpark` · `/dismiss-chip` · `PATCH /{id}/ai-resolve` |
| tickets (bulk, capped 200) | `POST /tickets/bulk/resolve` · `/reopen` · `/dismiss-chip` · `/non-actionable` · `/park` · `/unpark` · `PATCH /tickets/bulk/category` — each returns `{ok_ids, failed[]}` |
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

The project is feature-complete against `spec.md` v1.7. The 2026-05 roadmap is
now an execution log (full ledger with commit SHAs + the original phase tables:
[`docs/_archive/ROADMAP.md`](./_archive/ROADMAP.md)).

**Shipped to `main`:** Phases 0–3 + 4.1 (parked, T106) + 4.2 (`non_actionable_kind`,
T107) + robustness R.1–R.5. That covers: priority/sentiment/multi-label, aging
indicators, keyboard triage, saved views, priority-sorted queue, stats
dashboard, cost meter, snippets, bulk pre-flight diff, strict structured
outputs, model cascade, needs-review lane, the local embedding layer, few-shot
categorization, RAG draft replies, recurring-issue clustering, playbook-gap
detection, playbook auto-match.

**Open backlog** (the only live forward items):

| ID | Item | Notes |
|---|---|---|
| 4.3 / **T100** | Webhook + SSE live updates | `conversation.user.created`/`replied` → push to webapp + popup instead of poll-on-open. Heaviest deferred feature. |
| 4.4 / **T105** | Bulk actions in the extension popup | Mirror the webapp bulk bar; deferred for popup ergonomics. |

---

## 11. Quality gates (run before merge)

| Package | Gate | Skill |
|---|---|---|
| backend | `ruff check app tests && ruff format --check app tests && mypy app && pytest -q` | `/qa-backend` |
| webapp | `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build` | `/qa-webapp` |
| extension | Reload unpacked → sync → confirm popup renders + badge count + no console errors | `/qa-extension` |

`/qa-all` runs backend + webapp back-to-back. Last full run (2026-05-28):
backend 409 tests, webapp 215 tests, extension 20 tests — all green.

---

## 12. Glossary

- **HydratedTicket** — the normalized conversation shape the extension produces and the backend stores; spans three packages (invariant #2).
- **renderable_type** — Intercom's numeric message-type code, reverse-engineered: 1/12 customer, 2/24 admin, 3 internal note, others skipped (invariant #3).
- **content signature** — the last customer-visible part timestamp; the AI cache key (invariant #6). Teammate notes/assignments advance Intercom `updated_at` but must not bust cache.
- **override beats AI** — a manual category override wins while `tickets.updated_at ≤ override.set_at`.
- **proposal** — an AI-suggested new category, pending operator approve/merge/reject.
- **fallback** — the catch-all category a ticket lands in when AI is unavailable or returns garbage; fallback results are never cached.
- **resolved_source** — why a ticket is resolved: `manual` / `intercom_closed` / `non_actionable` / `ai_resolved`.
- **non-actionable** — a resolved sub-state (spam / thanks / auto-reply / out-of-office / other); its own board column / popup tab, split at the view layer.
- **parked** — board-state "waiting on customer/third-party/internal" with a wake time; XOR-locked trio, never co-resolved, surfaced via a filter chip.
- **playbook** — durable, category-scoped operator response recipe; not cache, survives re-sync (invariant #13).
- **snippet** — global canned reply with `{{var}}` slots; lighter than a playbook.

---

## 13. Documentation map

Where knowledge lives now, and the boundary this handbook respects:

| Doc | Owns | Status |
|---|---|---|
| **`docs/PROJECT.md`** (this) | System orientation: architecture, data-flow, stack, data model, API surface, feature status, glossary. | Canonical living handbook. |
| `CLAUDE.md` (+ `backend/`, `webapp/`, `extension/`) | Per-change rules + the 14 invariants. Auto-loaded every session. | Canonical, authoritative. **Not folded here.** |
| `spec.md` / `plan.md` / `tasks.md` | Requirements (US/FR/NFR) · architecture decisions (§1–§18) · traceability matrix (T001–T160). | Contract source of truth. **Not folded here** (charter-protected). |
| `docs/principles.md` | The four engineering principles. | Live; referenced by every sub-package CLAUDE.md. |
| `webapp/DESIGN.md` | Design-system source of truth (tokens/palette/components). | Live. |
| `*/README.md`, `SECURITY.md` | Per-package quickstart + secrets/threat model. | Live reference. |
| `docs/superpowers/specs/` + `plans/` | Per-feature design records ("why we built it this way"); cited by shipped-code docstrings. | Kept in place — the design archive. |
| `docs/_archive/` | Retired point-in-time artifacts: the 2026-05 audit cycle, resolved package reviews, the verbatim `architecture.md` + `ROADMAP.md`, the per-phase task breakdowns, roadmap-execution dispatch contracts. | History only; superseded by this doc + `tasks.md`. |

**Boundary rule:** one fact, one home. This handbook *links* to CLAUDE.md /
spec / plan / tasks rather than copying them — duplication is exactly the drift
that prompted the consolidation.

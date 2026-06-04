# Design — Multi-Hosted-User (hosted, authenticated, shared team board)

**Date:** 2026-06-05 · **Status:** approved (design) · **Author:** Christian + Claude
**Type:** charter pivot — auth + hosting + multi-user · **Spec impact:** spec → **v2.0**
**Base branch:** `feat/multi-hosted-user`, branched off `refactor/remove-extension`
(the two-package, extension-removed state — see
[`2026-06-05-remove-extension-design.md`](./2026-06-05-remove-extension-design.md)).

---

## 1. Context & charter pivot

The tool today is a **single-operator, local, no-auth** Kanban triage board over a
backend that polls one Intercom workspace with an Access Token. The root
`CLAUDE.md` charter explicitly forbids auth, tenants, RBAC, hosting, and deploy.

This feature **deliberately reverses five of those guardrails** so a **team of
operators** can use a **hosted** instance, each logging in, all triaging the
**same shared ticket pool**:

| Charter rule (today) | After this feature |
|---|---|
| No user auth | **Auth required** on every route (except health + login/refresh) |
| No multi-tenancy/tenants | **Shared team pool** — one workspace, one board, many users (NOT multi-tenant) |
| `localhost`-only, no deploy | **Hosted/networked** behind TLS, Postgres |
| No RBAC | Roles **captured** (OnlySales `scope`) but **not enforced** in v1 (flat perms) |
| Three packages | Two packages (extension already removed) |

**Still out of scope (unchanged charter):** multi-tenancy / per-tenant data
isolation (every user sees the same tickets — there is no `tenant_id`), per-user
Intercom tokens, autonomous action agents, multi-channel.

**Identity is delegated, not owned.** User accounts and passwords live in
**OnlySales** (`pyapi.onlysales.io`). Our backend never stores a password. It
proxies the OnlySales login, mirrors the returned identity into our DB for
attribution/assignment, and issues its **own** session for our API. Everything
else — tickets, categories, follow-ups, notes, AI — stays in **our** database.

---

## 2. Goal & success criteria

**Goal.** A hosted instance multiple operators sign into; the board, assignment,
attribution, and per-user follow-ups/notes work over one shared ticket pool;
identity comes from OnlySales; all triage data stays in our Postgres.

**Success criteria (verifiable):**

1. An operator with valid OnlySales credentials logs in at the webapp and reaches
   the board; invalid credentials are rejected with a clear error.
2. Every API route except `/health`, `/auth/login`, `/auth/refresh` returns `401`
   without a valid access token.
3. The access token verifies **offline** (no DB hit, no OnlySales call) on every
   request; OnlySales is contacted only at login and (optionally) upstream
   re-validation.
4. A refresh token is **revocable**: logout sets `revoked_at` and the token is
   rejected thereafter; "log out everywhere" revokes all of a user's sessions.
5. A ticket can be **assigned** to an operator; a "My Queue" view shows
   `assigned_to == me`.
6. Resolve / recategorize record **who** did it (`resolved_by` / `acted_by`),
   surfaced in the UI.
7. Follow-ups and note entries are **per-user** (each operator sees their own by
   default, with a "show all teammates'" toggle).
8. The refresh token is stored in an **httpOnly + Secure + SameSite** cookie; the
   access token lives only in memory; no token is readable by page JS at rest.
9. Backend + webapp quality gates pass; the suite runs against Postgres.

---

## 3. Non-goals

- **No multi-tenancy.** No `tenant_id`, no per-user ticket isolation. One shared
  board. (If true tenant isolation is ever wanted, that is a separate, larger
  design.)
- **No RBAC enforcement in v1.** Any authenticated user may edit categories,
  settings, taxonomy, and delete data. `scope` is stored for a future phase.
- **No account management UI.** No signup/password-reset/invite in our app —
  OnlySales owns that lifecycle.
- **No extension.** Already removed on the base branch.
- **No new AI/ingestion behavior.** The Intercom poll + categorize path is
  unchanged; it gains a system identity for attribution only.

---

## 4. Architecture

```
 alice@laptop   bob@desktop          (each their own browser)
      \             /
       v           v
   https://triage.<host>             TLS terminated at reverse proxy / platform
            |
   ┌────────┴──────────────────────────────────────────────┐
   │ OUR backend (FastAPI, networked bind, Postgres)        │
   │                                                        │
   │  POST /auth/login {email,password}                     │
   │     └─► clients/onlysales.py ─► pyapi.onlysales.io     │
   │            ◄─ {accessToken, refreshToken, user{...}}   │
   │     └─► upsert users (by onlysales_id)                 │
   │     └─► create sessions row:                           │
   │           refresh_token_hash (sha256),                 │
   │           onlysales_refresh_encrypted (Fernet)         │
   │     └─► Set-Cookie: refresh (httpOnly,Secure,SameSite) │
   │     └─► return { access_jwt(~30m), user }              │
   │                                                        │
   │  every other request:                                  │
   │     Authorization: Bearer access_jwt                   │
   │     └─► get_current_user dep: verify sig + exp offline │
   │            ─► load User by `sub` ─► attach to request  │
   │                                                        │
   │  POST /auth/refresh  (cookie) ─► rotate refresh,       │
   │     re-mint access; CSRF-guarded                       │
   │  POST /auth/logout   (cookie) ─► revoke session        │
   │                                                        │
   │  tickets · categories · ai · followups · notes · …     │
   │     all in OUR Postgres, ONE shared board              │
   └───────────────────────────┬────────────────────────────┘
                               v
                     Intercom (1 shared Access Token, server-side, unchanged)
```

**New backend modules:**
- `clients/onlysales.py` — async login/refresh proxy to `pyapi.onlysales.io`
  (mirrors `chrome-extension/api.js`: `POST /auth/login`, `POST /auth/refresh-token`,
  normalize `user.id → user._id`, `expiryAt` ISO → unix). Reuses the existing
  `clients/openrouter.py` retry/backoff style.
- `services/auth.py` — login orchestration (proxy → upsert user → create session
  → mint tokens), refresh (validate + rotate), logout (revoke).
- `security/tokens.py` — mint/verify our access JWT (HS256, `SESSION_JWT_SECRET`),
  generate/hash opaque refresh tokens, encrypt/decrypt the upstream refresh token.
- `routers/auth.py` — the `/auth/*` + `/users` endpoints.
- `deps.py:get_current_user` — the cross-cutting auth dependency.

**Token model (decided):** stateless access JWT (~30 min, offline-verified) +
DB-backed opaque refresh token (~30 d) in `sessions`. Refresh **rotates** on use;
reuse of a rotated token revokes the chain (theft detection). Normal refresh is
self-contained (no OnlySales call); the encrypted upstream refresh token is kept
for **optional** periodic re-validation that the OnlySales account still exists /
is active (defer the periodic check to a later phase; store it now).

---

## 5. Data model

### 5.1 New tables (migrations 0021, 0022)

**`users`** — mirror of OnlySales identity (NOT a credential store):

| Column | Type | Notes |
|---|---|---|
| `id` | int PK | our surrogate id |
| `onlysales_id` | str, UNIQUE, NOT NULL | OnlySales `_id` (24-hex) — stable external identity |
| `email` | str, UNIQUE, NOT NULL | |
| `name` | str, nullable | `firstName + lastName` |
| `scope` | str, nullable | `admin`/`manager`/`agent` — captured, not enforced v1 |
| `is_active` | bool, default true | local disable without touching OnlySales |
| `created_at` | naive-UTC | |
| `last_login_at` | naive-UTC, nullable | |

**`sessions`** — refresh-token store / revocation ledger:

| Column | Type | Notes |
|---|---|---|
| `id` | uuid PK | session id |
| `user_id` | int FK → users.id | |
| `refresh_token_hash` | str, indexed | sha256 of the opaque refresh token (raw never stored) |
| `onlysales_refresh_encrypted` | bytes/str, nullable | upstream refresh, Fernet/AES-GCM (`SESSION_REFRESH_ENCRYPTION_KEY`) |
| `issued_at` | naive-UTC | |
| `expires_at` | naive-UTC | ~30 d |
| `revoked_at` | naive-UTC, nullable | logout / rotation-reuse / log-out-everywhere |
| `last_used_at` | naive-UTC, nullable | |
| `user_agent` / `ip` | str, nullable | optional audit |

### 5.2 Column additions

| Table | Add | Migration | Purpose |
|---|---|---|---|
| `tickets` | `assigned_to` (FK users, null) + `assigned_at` | 0023 | Assignment / My Queue |
| `tickets` | `resolved_by` (FK users, null) | 0023 | Attribution (AI/system → null) |
| `overrides` | `acted_by` (FK users, null) | 0024 | Who recategorized |
| `note_entries` | `user_id` **already exists** — repurpose from placeholder to the real authenticated user | 0025 (only if a constraint/index is needed) | Per-user notes |

*(Optional, deferred: `parked_by`. Not in v1.)*

> Migration numbers are indicative (next free is **0021** — the base branch is a
> deletion and added none). Per the worktree doctrine, only one session adds a
> migration at a time, so the exact prefixes are finalized at implementation.

### 5.3 Reshape — `followups` (heaviest change, migration 0026)

Today `followups.PK = ticket_id` (one per ticket; `PUT /followups/{id}` upserts by
ticket id). Per-user follow-ups means a follow-up belongs to **(ticket, user)**:

- Add surrogate `id` PK + `user_id`; keep `ticket_id`, `due_at`, `reason`,
  `fired_at`, timestamps.
- **UNIQUE(ticket_id, user_id)** — preserves the one-per upsert, now keyed by
  ticket **and** user.
- **Blast radius:** `services/followups.py` (upsert/snooze/clear keyed by
  ticket+user), the bulk followup endpoints, `webapp .../followups` store,
  `FollowupBoard.vue` / `FollowupColumn.vue`, the 1 Hz countdown chip query, the
  follow-up alarm path. Contained but real — this is the largest single edit.
- **Migration of existing rows:** assign `user_id` to a designated owner or NULL
  (hosted deploy likely starts with little/no legacy follow-up data); document the
  chosen rule in the migration.

### 5.4 Stays shared / unchanged

`tickets` content, `categories`, `category_proposals`, `playbooks`, `snippets`,
`ai_cache`, `ticket_embeddings`, `ticket_clusters*`, `ticket_notes` (legacy
single body), and `settings` (singleton, team-wide). Existing invariants #5–#13
hold. Client-only personal prefs (`tweaks`, `savedViews`) remain per-browser
`localStorage` — no server change needed.

### 5.5 Per-user notes/followups UX (decided)

Private data on a **shared** ticket creates tension (bob can't see alice's
investigation by default). **Resolution:** default each operator to their **own**
follow-ups + note entries, plus a **"show all teammates'"** toggle on the
follow-up board and the note timeline — filtered, never hidden. Tickets,
categories, and the board stay fully shared.

---

## 6. API surface

### 6.1 New auth router (`routers/auth.py`) — public

| Endpoint | Body / auth | Behavior |
|---|---|---|
| `POST /auth/login` | `{email, password}` | proxy to OnlySales → mirror user → create session → `Set-Cookie` refresh → return `{access_jwt, user}` |
| `POST /auth/refresh` | cookie | validate session row, **rotate** refresh, re-mint access; CSRF-guarded |
| `POST /auth/logout` | cookie | revoke session, clear cookie |
| `POST /auth/logout-all` | access token | revoke all of the user's sessions |
| `GET /auth/me` | access token | current user |
| `GET /users` | access token | lightweight mirror list (assignee picker) |

### 6.2 Cross-cutting auth

`get_current_user` dependency on **every** router except the public allowlist
(`/health`, `/auth/login`, `/auth/refresh`). Applied via router-level
dependencies (not a blanket middleware) so the allowlist is explicit.
`POST /tickets/ingest` + the background poller run under a **system identity**
(server-side only; attribution → null/"system"); they are not user-authenticated.

### 6.3 Changed existing endpoints (capture actor / assignment)

- resolve + `POST /tickets/bulk/resolve` → set `resolved_by = current_user`.
- `PATCH /tickets/{id}/category` + `PATCH /tickets/bulk/category` → set
  `overrides.acted_by`.
- **new** `PATCH /tickets/{id}/assign {user_id|null}` + `POST /tickets/bulk/assign`.
- follow-up endpoints → scoped to `current_user` (ticket_id + user_id).
- note-entry endpoints → stamp `user_id = current_user`; list defaults to mine.
- every `{ok_ids, failed[]}` bulk op records attribution per affected row.

`MAX_BULK_IDS = 200` (invariant #9) unchanged; bulk assign honors it.

---

## 7. Frontend (webapp)

- **`LoginView.vue`** — email + password, inline error states. **App gate:**
  unauthenticated → `LoginView`; authenticated → board. Gate on auth-store state
  (no vue-router — consistent with the existing `view` store switch).
- **`auth` Pinia store** — in-memory `accessToken` + `currentUser`;
  `login / logout / refresh / ensureFresh`. On app load, call `/auth/refresh`
  (cookie) to bootstrap a session silently; failure → show login.
- **`api/client.ts`** — attach `Authorization: Bearer`; `credentials: 'include'`
  (send cookie); on `401` → one `/auth/refresh` then retry; refresh failure →
  clear state + show login. Guard against concurrent refreshes (single in-flight
  promise).
- **My Queue** — `tickets` store getter `myTickets` (`assigned_to === me.id`) + a
  board filter/view. **Assignee picker** on the card + flyout (options from
  `GET /users`).
- **Attribution display** — "resolved by X", "assigned to Y", note "by Z" on the
  card/flyout.
- **Per-user follow-ups/notes** — followups store fetches "my follow-ups";
  `FollowupBoard` + note timeline show mine with a **"show all"** toggle.
- **Token handling** — access token in memory only; the refresh cookie is managed
  by the browser; nothing sensitive in `localStorage`.

---

## 8. Security & hosting

- **TLS** terminated at a reverse proxy / platform; backend binds networked
  (not `127.0.0.1`-only).
- **CORS** — `allow_origins = [webapp origin]`, `allow_credentials = True`
  (required for the cookie). No wildcard. (Base branch already tightened CORS by
  dropping the `chrome-extension://` regex.)
- **Cookie** — `httpOnly; Secure; SameSite=Lax` (or `Strict` if same-site only).
- **CSRF** — `/auth/refresh` is cookie-authenticated → add a CSRF defense
  (double-submit token **or** a required custom header that simple cross-site form
  posts cannot set). Document which.
- **Brute-force** — rate-limit `/auth/login` per-IP and per-email (protects both
  us and OnlySales).
- **Refresh rotation** + reuse-detection revocation (a replayed rotated token
  kills the session chain).
- **Secrets (env / secret manager):** `SESSION_JWT_SECRET`,
  `SESSION_REFRESH_ENCRYPTION_KEY`, `ONLYSALES_AUTH_BASE_URL`
  (default `https://pyapi.onlysales.io`), `INTERCOM_ACCESS_TOKEN`,
  `OPENROUTER_API_KEY`, `DATABASE_URL` (Postgres). A degraded boot (missing AI /
  Intercom secret) is preserved; a missing `SESSION_JWT_SECRET` **must** hard-fail
  boot (no insecure default).

### 8.1 Postgres + embeddings conflict (decided: option a)

`sqlite-vec` (the `ticket_embeddings` vector store) is **SQLite-only**. The whole
semantic layer (few-shot categorization, RAG draft replies, recurring-issue
clustering, playbook auto-match / gap detection) cannot run on Postgres as-is.

**Decision for v1:** ship hosted on Postgres with the **embedding/clustering
layer disabled** (it is already opt-in via `embeddings_enabled` /
`clustering_enabled`). `/health` continues to report semantic-layer availability.
**Fast-follow (separate design):** add a **pgvector** backend behind the existing
embeddings abstraction to restore semantic features on Postgres. Flag this clearly
in `/health` and the deploy docs so the capability gap is visible, not silent.

---

## 9. Docs / charter / contract impact

- **Root `CLAUDE.md`** — rewrite "Scope guardrails" + "Don't": auth, users,
  hosting/deploy now **in** scope; multi-tenancy still **out** (shared pool only).
  Add new invariants (see below). The invariant-guard hook is currently disabled
  in the working tree (operator choice) — re-enabling is independent of this work.
- **New invariants (proposed):**
  1. Every API route requires a valid session **except** `/health`,
     `/auth/login`, `/auth/refresh`.
  2. Access token is **stateless / offline-verified**; the refresh token is
     **DB-backed, rotating, and revocable**. OnlySales is touched only at
     login/refresh.
  3. Attribution columns (`resolved_by`, `acted_by`, `assigned_to`) are
     **audit/board-state only** — never fed to AI, never block ingest, never on
     `HydratedTicket` (invariant #2 untouched).
  4. Per-user follow-ups & note entries are scoped by `user_id`; **tickets,
     categories, settings stay shared.**
  5. No password is ever stored or logged by our backend; identity is delegated to
     OnlySales.
- **`docs/PROJECT.md` / `docs/FEATURES.md`** — new "Auth & multi-user" sections;
  data-model rows for `users` / `sessions` + the new columns; architecture
  diagram update; `/auth/*` + `/users` in the API surface.
- **Contract (`docs/contract/`)** — spec → **v2.0** with new `US-040+` (login,
  assignment, My Queue, attribution, per-user follow-ups/notes), `FR-063+`, and
  NFRs (TLS, CORS, cookie/CSRF, rate-limit, token lifecycle, Postgres). plan.md
  new **§19 Auth & multi-user**. tasks.md new **T167+** with the traceability
  matrix. (v1.9 was the extension-removal bump.)

---

## 10. Phasing (becomes the implementation plan)

1. **Auth core** — `users` + `sessions` tables; `clients/onlysales.py`;
   `security/tokens.py`; `routers/auth.py`; `get_current_user` on all routers;
   webapp `LoginView` + `auth` store + refresh interceptor; CORS/cookie/secrets;
   rate-limit `/auth/login`. *Ship the gate.*
2. **Attribution** — `resolved_by` / `acted_by` columns + capture in services +
   UI display.
3. **Assignment + My Queue** — `tickets.assigned_to`, assign endpoints, `/users`,
   board getter + assignee UI.
4. **Per-user follow-ups & notes** — `followups` reshape (heaviest) + note
   scoping + store/board/UI + "show all" toggle.
5. **Hosting hardening** — Postgres run-through (embeddings-off validation),
   reverse-proxy/TLS config, secrets, deploy notes; CSRF finalize.

*(Extension removal — formerly a phase here — is already complete on the base
branch.)*

---

## 11. Testing strategy

- **Backend:** OnlySales login proxy (mocked via `pytest-httpx`); access-token
  mint/verify; refresh rotation + reuse-revocation; logout / logout-all; `401` on
  every protected route; CSRF on refresh; rate-limit on login; per-user follow-up
  scoping; assignment + My-Queue queries; attribution capture; **Postgres-compat
  smoke** of the new migrations.
- **Webapp:** `auth` store (login/refresh/logout); the `401 → refresh → retry`
  interceptor (incl. single-flight); My-Queue getter; assignment UI; per-user
  follow-up store; login-gate rendering.
- ⚠️ **Harness change:** every existing API test now needs an authenticated-user
  context. Add a shared fixture that overrides `get_current_user` (and seeds a
  mirror user). Broad but mechanical; budget for it explicitly.

---

## 12. Risks & open items

| # | Risk / open item | Disposition |
|---|---|---|
| 1 | Embeddings/clustering can't run on Postgres (`sqlite-vec` is SQLite-only) | **Decided:** disabled in hosted v1; pgvector as a fast-follow design. |
| 2 | Per-user data on a shared ticket hides teammates' work | **Decided:** default-mine + "show all" toggle. |
| 3 | OnlySales base URL — code uses `pyapi.onlysales.io`; request said `api.onlysales.io` | **Confirm at impl start.** Also confirm OnlySales permits server-side login from our host IP + login-response shape is stable. |
| 4 | Flat perms v1 — any logged-in user can edit categories/settings/delete | **Accepted for v1**; `scope` stored for a future RBAC phase. |
| 5 | `followups` reshape ripples into store/board/alarm/bulk | Isolated to Phase 4; covered by tests before/after. |
| 6 | Every existing API test needs auth | Shared dependency-override fixture (§11). |
| 7 | Hard-fail boot if `SESSION_JWT_SECRET` missing | Required — no insecure default. |

---

## 13. Rollback

Auth is additive (new tables, new router, new dependency, new columns). Rollback =
revert the feature branch; the new migrations are forward-only, so a down-path or
a fresh DB is needed if partially deployed. No OnlySales-side change is involved.
```

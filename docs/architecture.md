# Architecture

> Long-form architecture reference. Root `CLAUDE.md` points here. The 12 cross-package invariants stay in `CLAUDE.md` because Claude needs them every change; the prose below is read on demand.

## System summary (one paragraph)

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

One command boots backend + webapp in a Windows Terminal split-pane:

```powershell
# Backend on 127.0.0.1:4000, webapp on 127.0.0.1:5173 (proxies /api → :4000).
# Runs pip install + npm install first (idempotent if cached), then launches
# wt.exe split-pane. Requires Windows Terminal (default on Win 11).
.\scripts\dev.ps1
```

Extension is loaded manually once:

```
chrome://extensions → Developer mode → Load unpacked → select extension/
```

Reload the unpacked extension after every code change.

First boot: backend creates `backend/data/triage.db`, seeds 7 default categories, inserts the singleton settings row. Missing `OPENROUTER_API_KEY` does not block startup — `/health` reports it; ingest writes every ticket to the fallback category until the key is provided.

Operator must enter the Intercom workspace `app_id` (e.g. `j3dxf22l`) in the popup setup screen once; it's stored in `chrome.storage.local.intercomAppId`.

## Versions / stack at a glance

| Package    | Stack                                                                                 |
|------------|---------------------------------------------------------------------------------------|
| backend    | Python 3.11+, FastAPI 0.115, SQLAlchemy 2.0 (async), Alembic, pydantic v2, httpx       |
| webapp     | Vue 3.5, Pinia 2.3, Vite 6, TypeScript 5.6, vue-tsc, ESLint 9, Prettier 3, Vitest 2    |
| extension  | Plain ES modules, MV3, no build step, no dependencies                                  |
| AI         | OpenRouter (`anthropic/claude-sonnet-4.5` default; swap via `OPENROUTER_MODEL`)        |
| Storage    | SQLite (default, `backend/data/triage.db`) · Postgres swap via `DATABASE_URL`         |

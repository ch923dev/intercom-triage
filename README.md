# Intercom Triage

Local single-operator tool that pre-categorizes and summarizes recent Intercom
conversations so you can scan and route in one Kanban view instead of opening
each ticket. Backend + webapp, all on `localhost`.

Start at the **[docs hub](./docs/)**. The contract:
[`spec.md`](./docs/contract/spec.md) for what it does,
[`plan.md`](./docs/contract/plan.md) for how it's built, and
[`tasks.md`](./docs/contract/tasks.md) for the task breakdown.

## Layout

```
.
├── backend/        FastAPI service + SQLite store + Intercom/AI integration
├── webapp/         Vue 3 + Vite SPA — the Kanban board, admin pages, settings
├── snippets/       Reference implementations referenced by task docs
└── docs/           📚 Docs hub (README.md) — handbook, features, contract/{spec,plan,tasks}.md
```

## Prerequisites

- Python 3.11+ (3.12 tested)
- Node 18+
- OpenRouter API key
- Intercom workspace **Access Token** — the backend polls `api.intercom.io` with
  it (Intercom → Settings → Integrations → Developer Hub → your app)

## Quickstart

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # PowerShell  (bash: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env                # then fill in OPENROUTER_API_KEY,
                                      # INTERCOM_ACCESS_TOKEN + INTERCOM_WORKSPACE_APP_ID
uvicorn app.main:app --reload --host 127.0.0.1 --port 4000
```

First boot creates `backend/data/triage.db` and seeds seven categories
(Urgent, Bug, Feature Request, Question, Billing, Complaint, Other) plus the
default filter settings. Missing secrets do **not** block startup — the backend
runs in a degraded mode and `/health` reports what is missing.

To ingest, the backend polls Intercom directly. Trigger one cycle manually with
`curl -X POST http://localhost:4000/tickets/sync`, or set
`INTERCOM_POLL_INTERVAL_SECONDS` (e.g. `120`) in `.env` to run a background
poller (off by default — `0`).

```powershell
curl http://localhost:4000/health
```

### 2. Webapp

```powershell
cd webapp
npm install
npm run dev                           # serves http://localhost:5173
```

The dev server proxies `/api/*` to the backend on `:4000`. Open
<http://localhost:5173> — the board fetches tickets, and the top bar gives you
the category-management and proposal-review pages plus the filter drawer.

## API surface

| Method + path | Purpose |
|---|---|
| `GET /health` | Startup smoke + which secrets are missing |
| `GET /metrics` | Process-lifetime counters (JSON) |
| `GET /categories` | Active categories + pending proposals |
| `POST /categories` · `PATCH /categories/{id}` | Create / rename / recolor / reorder |
| `POST /categories/{id}/archive` | Archive + sweep tickets to fallback |
| `POST /categories/{src}/merge-into/{dst}` | Merge categories |
| `GET /proposals` | Pending AI category proposals + example tickets |
| `POST /proposals/{id}/approve` · `/merge-into/{cat}` · `/reject` | Resolve a proposal |
| `GET /tickets` | The stored board — backend-polled + categorized tickets |
| `POST /tickets/sync` | Run one Intercom fetch+ingest cycle now (503 if no token); the background poller runs the same cycle |
| `POST /tickets/ingest` | Direct ingest of `HydratedTicket[]` (categorize + store) — used internally by the sync cycle |
| `POST /tickets/{id}/resolve` · `/reopen` · `/dismiss-chip` · `PATCH /ai-resolve` | Manual + AI resolution |
| `PATCH /tickets/{id}/category` | Manually override a ticket's category |
| `PATCH /tickets/{id}` | Edit AI-supplied title + summary (sticky across re-syncs) |
| `POST /tickets/bulk/resolve` · `/reopen` · `/dismiss-chip` · `PATCH /tickets/bulk/category` | Multi-select bulk ops, per-id ok/failed result |
| `PUT /followups/bulk` · `DELETE /followups/bulk` | Multi-select follow-up set / clear |
| `GET /settings` · `PUT /settings` | The stored filter settings + `mute_alarms` |
| `GET /followups` | All active follow-up reminders |
| `PUT /followups/{id}` · `/snooze` · `/mark-fired` · `DELETE` | Set / snooze / fire / clear a follow-up |
| `GET /notes` · `PUT /notes/{id}` | Per-ticket next-step notes (empty body deletes) |
| `GET /notes/entries` · `GET /notes/entries/{ticket_id}` | Time-tabled note entries — list all / list by ticket |
| `POST /notes/entries` · `DELETE /notes/entries/{id}` | Append an entry (optional `timer_min` upserts follow-up); soft-delete by id |
| `POST /attachments` · `GET /attachments?ticket_id=...` | Multipart upload / list by ticket. `owner_kind` = `entry`\|`ticket` |
| `GET /attachments/{id}/raw` · `GET /attachments/{id}/thumb` | Stream bytes inline / 256px WebP thumbnail for images |
| `DELETE /attachments/{id}` | Soft-delete; nightly sweep removes orphaned bytes after `ATTACHMENT_GC_DAYS` (default 7) |

Interactive docs at <http://localhost:4000/docs> while the backend runs.

## Bulk actions

Cmd/Ctrl+click a card to add it to a multi-select set; Shift+click extends
within the same column. Hover a column header for a `Select N` chip.
Selection clears on Escape, an empty-background click, or after a successful
bulk action.

When at least one card is selected, a sticky bar appears: **Resolve**,
**Reopen**, **Move to →** (category picker), **Follow-up →** (preset chips
`15m / 1h / 4h / 24h`), **Clear F/U**, **Dismiss chip**. Disabled buttons
explain why on hover (e.g. *Reopen* requires every selected card to be
resolved).

Dragging a card that's in the selection set moves the whole set: drop into a
category column to bulk-recategorize, or into the Resolved column to
bulk-resolve. A single bulk request is capped at 200 ids
(`MAX_BULK_IDS` in `backend/app/config.py`); the webapp warns before
submitting a larger selection. Each bulk endpoint returns
`{ok_ids, failed: [{id, reason}]}` — per-id failures never abort the rest
of the batch.

## Development

Quality gates — all green on `main`:

```powershell
# backend  (from backend/, venv active)
pip install -r requirements-dev.txt
ruff check app tests && ruff format --check app tests
mypy app
pytest -q

# webapp  (from webapp/)
npm run typecheck
npm run build
```

### One-command dev launcher

```powershell
.\scripts\dev.ps1
```

Installs pip + npm deps (idempotent if cached), then opens a Windows Terminal
window with backend (`:4000`) and webapp (`:5173`) in a split-pane. Requires
`wt.exe` (Windows Terminal — default on Win 11).

## Configuration

All secrets live in `backend/.env` (gitignored). See `backend/.env.example`
for the full field list and defaults — model choice, lookback window, AI
concurrency, cache TTL, and the SQLite → Postgres swap.

## Backup

Copy `backend/data/triage.db` somewhere — single file. The Postgres swap is
documented in [`plan.md`](./docs/contract/plan.md#10-deployment).

Attachment files live under `backend/data/attachments/` (content-addressed
by sha256). To back up notes + their files, copy `backend/data/` as a whole.

## License

MIT — see [LICENSE](./LICENSE).

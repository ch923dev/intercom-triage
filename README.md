# Intercom Triage

Local single-operator tool that pre-categorizes and summarizes recent Intercom
conversations so you can scan and route in one Kanban view instead of opening
each ticket. Backend + webapp + Chrome extension, all on `localhost`.

See [`spec.md`](./spec.md) for what it does, [`plan.md`](./plan.md) for how it's
built, and [`tasks.md`](./tasks.md) for the task breakdown.

## Layout

```
.
├── backend/        FastAPI service + SQLite store + Intercom/AI integration
├── webapp/         Vue 3 + Vite SPA — the Kanban board, admin pages, settings
├── extension/      Chrome MV3 popup mini-board + background badge
├── snippets/       Reference implementations referenced by task docs
├── spec.md         Requirements (what)
├── plan.md         Architecture + decisions (how)
└── tasks.md        Task breakdown w/ traceability matrix
```

## Prerequisites

- Python 3.11+ (3.12 tested)
- Node 18+
- Chrome (for the optional extension)
- Intercom **Access Token** with the `Read conversations` scope
- OpenRouter API key

## Quickstart

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # PowerShell  (bash: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env                # then fill in INTERCOM_ACCESS_TOKEN + OPENROUTER_API_KEY
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

First boot creates `backend/data/triage.db` and seeds seven categories
(Urgent, Bug, Feature Request, Question, Billing, Complaint, Other) plus the
default filter settings. Missing secrets do **not** block startup — the backend
runs in a degraded mode and `/health` reports what is missing.

```powershell
curl http://localhost:8000/health
```

### 2. Webapp

```powershell
cd webapp
npm install
npm run dev                           # serves http://localhost:5173
```

The dev server proxies `/api/*` to the backend on `:8000`. Open
<http://localhost:5173> — the board fetches tickets, and the top bar gives you
the category-management and proposal-review pages plus the filter drawer.

### 3. Chrome extension (optional)

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. **Load unpacked** → select the `extension/` folder.

The toolbar popup is a mini-board with the same taxonomy; it talks directly to
the backend on `:8000`. Background polling is **off by default** — pick an
interval in the popup footer to have it badge the Urgent count.

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
| `POST /tickets/fetch` | Fetch + categorize tickets (each carries its follow-up + note) |
| `PATCH /tickets/{id}/category` | Manually override a ticket's category |
| `GET /settings` · `PUT /settings` | The stored filter settings + `mute_alarms` |
| `GET /followups` | All active follow-up reminders |
| `PUT /followups/{id}` · `/snooze` · `/mark-fired` · `DELETE` | Set / snooze / fire / clear a follow-up |
| `GET /notes` · `PUT /notes/{id}` | Per-ticket next-step notes (empty body deletes) |

Interactive docs at <http://localhost:8000/docs> while the backend runs.

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

Dev scripts (PowerShell + bash) live in `scripts/` — see
[`tasks.md`](./tasks.md) T002.

## Configuration

All secrets live in `backend/.env` (gitignored). See `backend/.env.example`
for the full field list and defaults — model choice, lookback window, AI
concurrency, cache TTL, and the SQLite → Postgres swap.

## Backup

Copy `backend/data/triage.db` somewhere — single file. The Postgres swap is
documented in [`plan.md`](./plan.md#10-deployment).

## License

MIT — see [LICENSE](./LICENSE).

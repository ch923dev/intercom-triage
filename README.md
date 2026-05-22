# Intercom Triage

Local single-operator tool that pre-categorizes and summarizes recent Intercom
conversations so you can scan and route in one view instead of opening each
ticket. Backend + webapp + Chrome extension, all on `localhost`.

See [`spec.md`](./spec.md) for what it does, [`plan.md`](./plan.md) for how it's
built, and [`tasks.md`](./tasks.md) for the task breakdown.

## Layout

```
.
├── backend/        FastAPI service + SQLite store (Phase 1+)
├── webapp/         Vue 3 + Vite SPA (Phase 6)
├── extension/      Chrome MV3 popup mini-board (Phase 7)
├── snippets/       Reference implementations referenced by task docs
├── spec.md         Requirements (what)
├── plan.md         Architecture + decisions (how)
└── tasks.md        Task breakdown w/ traceability matrix
```

## Prerequisites

- Python 3.11+ (3.12 tested)
- Node 18+ (for webapp + extension, later phases)
- Chrome (for extension, later phases)
- Intercom **Access Token** with `Read conversations` scope
- OpenRouter API key

## Quickstart — backend only (current scaffold)

```powershell
# from repo root
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1        # PowerShell
# source .venv/bin/activate          # bash equivalent
pip install -r requirements.txt
copy .env.example .env               # then fill in tokens
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then:

```powershell
curl http://localhost:8000/health
curl http://localhost:8000/categories
```

First boot creates `backend/data/triage.db` and seeds seven categories
(Urgent, Bug, Feature Request, Question, Billing, Complaint, Other).

## Dev scripts

PowerShell + bash equivalents in `scripts/`. Documented per task in
[`tasks.md`](./tasks.md#t002--p--dev-tooling) T002.

| Action          | PowerShell                          | bash                         |
|-----------------|-------------------------------------|------------------------------|
| dev-backend     | `.\scripts\dev-backend.ps1`         | `./scripts/dev-backend.sh`   |
| seed-db         | `.\scripts\seed-db.ps1`             | `./scripts/seed-db.sh`       |

`dev-web` and `build-ext` land with their phases.

## Configuration

All secrets live in `backend/.env` (gitignored). See `backend/.env.example`
for the full field list and defaults.

## Backup

Copy `backend/data/triage.db` somewhere. Single file. SQLite swap to Postgres
documented in [`plan.md`](./plan.md#10-deployment).

## License

MIT — see [LICENSE](./LICENSE).

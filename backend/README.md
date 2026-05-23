# Backend — Intercom Triage

FastAPI service on `localhost:8000`. Owns Intercom integration, AI categorization,
SQLite store, and the public API surface.

See [`../spec.md`](../spec.md), [`../plan.md`](../plan.md), and
[`../tasks.md`](../tasks.md).

## Layout

```
backend/
├── app/
│   ├── main.py              FastAPI app + lifespan + CORS
│   ├── config.py            pydantic-settings reading .env
│   ├── db.py                async engine + session factory
│   ├── deps.py              FastAPI dependencies
│   ├── models.py            SQLAlchemy 2.0 models + DEFAULT_CATEGORIES + init_db
│   ├── schemas.py           Pydantic request/response shapes
│   ├── metrics.py           In-process counters
│   ├── observability.py     Stdlib logging wrappers
│   ├── util.py              naive_utcnow + small helpers
│   ├── ai/                  Prompt builder + categorize/resolve pipeline
│   ├── clients/             Intercom + OpenRouter HTTP clients
│   ├── routers/             health · categories · proposals · tickets ·
│   │                        settings · followups · notes · metrics
│   └── services/            cache · categories · followups · notes ·
│                            proposals · resolution · settings · tickets
├── alembic/                 Migration chain (0001 → head)
├── data/                    SQLite file (gitignored) — created on first boot
├── tests/                   pytest
├── .env.example
├── alembic.ini
├── pyproject.toml           ruff + mypy config
└── requirements.txt
```

## Run

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env       # then fill in tokens
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

## API

Full API contract in [`../plan.md`](../plan.md#4-api-contract); table summary in
[`../README.md`](../README.md#api-surface). Interactive docs at
<http://localhost:8000/docs> while the server is running.

## Lint + type check

```powershell
ruff check .
ruff format --check .
mypy app
pytest -q
```

## Smoke test the schema

```powershell
python -m app.models       # spins up in-memory DB, prints seeded categories
```

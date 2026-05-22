# Backend — Intercom Triage

FastAPI service on `localhost:8000`. Owns Intercom integration, AI categorization,
SQLite store, and the public API surface.

See [`../spec.md`](../spec.md), [`../plan.md`](../plan.md), and
[`../tasks.md`](../tasks.md).

## Layout

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, lifespan, CORS
│   ├── config.py          # pydantic-settings reading .env
│   ├── db.py              # engine + session factory
│   ├── models.py          # SQLAlchemy 2.0 models + DEFAULT_CATEGORIES + init_db
│   └── routers/
│       ├── __init__.py
│       ├── health.py      # GET /health
│       └── categories.py  # GET /categories  (Phase 1)
├── data/                  # SQLite file (gitignored) — created on first boot
├── tests/                 # pytest
├── .env.example
├── pyproject.toml         # ruff + mypy config
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

## Endpoints (Phase 1)

| Method | Path           | Purpose                                  |
|--------|----------------|------------------------------------------|
| GET    | `/health`      | Status + configured model + cred summary |
| GET    | `/categories`  | Active categories + pending proposals    |

Full API contract in [`../plan.md`](../plan.md#4-api-contract).

## Lint + type check

```powershell
ruff check .
ruff format --check .
mypy app
```

## Smoke test the schema

```powershell
python -m app.models       # spins up in-memory DB, prints seeded categories
```

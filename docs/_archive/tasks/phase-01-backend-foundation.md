# Phase 1 — Backend foundation

Back to [tasks.md](../../tasks.md).

### T003 ✓ — Backend project init
**Depends on:** T001
**Implements:** —
**Description:** Python project under `backend/`. `requirements.txt` with FastAPI, uvicorn, httpx, pydantic, pydantic-settings, SQLAlchemy 2.0, aiosqlite. Ruff + mypy configured.
**Acceptance:** Fresh venv install succeeds; ruff and mypy pass on the empty project.

### T004 ✓ — Settings + .env.example
**Depends on:** T003
**Implements:** NFR-005, plan §1
**Description:** `config.py` using `pydantic-settings`. Fields: `intercom_access_token`, `openrouter_api_key`, `openrouter_model`, `database_url` (default `sqlite+aiosqlite:///./data/triage.db`), `default_lookback_hours`, `max_tickets_per_fetch`, `ai_concurrency`, `cache_ttl_seconds`, `host` (default `127.0.0.1`), `port` (default `8000`). `.env.example` checked in.
**Acceptance:** App boots without secrets; `/health` reports missing pieces explicitly. Default `database_url` resolves to a SQLite file path.

### T005 ✓ — FastAPI skeleton + `/health`
**Depends on:** T004
**Implements:** plan §4
**Description:** `main.py` with FastAPI app, permissive CORS for `localhost` and `chrome-extension://*`, lifespan hook, `GET /health` reporting status and configured model. Server binds to `127.0.0.1`.
**Acceptance:** `curl http://localhost:8000/health` returns 200 with the documented shape.

### T006 ✓ — SQLAlchemy models + init_db
**Depends on:** T003, T004
**Implements:** plan §5
**Description:** `models.py` with `Base = DeclarativeBase` and all six tables per plan §5 (`Category`, `CategoryProposal`, `AICacheEntry`, `Override`, `Settings`, `RejectedProposalSignature`). Include the XOR check constraint on `ai_cache`, the singleton check on `settings`, the partial unique indexes. `init_db()` function runs `Base.metadata.create_all` and seeds defaults (seven categories + singleton settings row) when empty. Wire into the lifespan hook.
**Acceptance:**
- First boot creates the SQLite file with all tables.
- First boot inserts seven seed categories and the singleton settings row.
- Restarting does not duplicate seeds.
- Inserting a row with both `category_id` and `proposal_id` is rejected by the DB.

### T007 [P] ✓ — `GET /categories`
**Depends on:** T005, T006
**Implements:** FR-004, FR-018
**Description:** Returns active categories + pending proposals in display order.
**Acceptance:** Fresh DB returns the seven seeded categories with `is_fallback=true` on "Other"; new pending proposal shows in the list.

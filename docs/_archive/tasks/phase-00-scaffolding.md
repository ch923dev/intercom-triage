# Phase 0 — Scaffolding

Back to [tasks.md](../../tasks.md).

### T001 ✓ — Repo scaffold
**Depends on:** —
**Implements:** —
**Description:** Top-level repo with `backend/`, `webapp/`, `extension/`. Root `README.md`, `.gitignore` (includes `.env` and `backend/data/`), `.editorconfig`, license.
**Acceptance:** `tree -L 2` shows three subdirs with README stubs. `.env` is gitignored.

### T002 [P] ✓ — Dev tooling
**Depends on:** T001
**Implements:** —
**Description:** Make targets (with PowerShell equivalents documented for Windows): `dev-backend`, `dev-web`, `build-ext`, `seed-db`. Pre-commit config.
**Acceptance:** All targets execute on a clean checkout.

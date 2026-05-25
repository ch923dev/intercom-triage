# Backlog (Phase 9)

Back to [tasks.md](../../tasks.md).

- **T100** — Webhook subscription on `conversation.user.created`/`conversation.user.replied`; push channel (SSE) to webapp and extension.
- **T102** — Token / cost meter surfacing OpenRouter spend per day.
- **T103** — Multi-user expansion: add a `users` table + simple session cookie auth + per-user overrides and settings. Path back to v1.1 architecture.
- **T104 ✓** — Alembic migrations: introduce when the first schema change is needed beyond `create_all`. (Done — see `backend/alembic/versions/0001`..`0009`.)
- **T105** — Bulk actions in the extension popup (deferred from Phase 12 — popup ergonomics too cramped for multi-select in v1).

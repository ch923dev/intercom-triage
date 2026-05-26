# Backlog (Phase 9)

Back to [tasks.md](../../tasks.md).

- **T100** — Webhook subscription on `conversation.user.created`/`conversation.user.replied`; push channel (SSE) to webapp and extension.
- **T102** — Token / cost meter surfacing OpenRouter spend per day.
- **T103** — Multi-user expansion: add a `users` table + simple session cookie auth + per-user overrides and settings. Path back to v1.1 architecture.
- **T104 ✓** — Alembic migrations: introduce when the first schema change is needed beyond `create_all`. (Done — see `backend/alembic/versions/0001`..`0009`.)
- **T105** — Bulk actions in the extension popup (deferred from Phase 12 — popup ergonomics too cramped for multi-select in v1).
- **T106** — Parked / snoozed state. Operator-chosen "waiting on third party / customer / hold." Distinct from non-actionable (Phase 13): non-actionable = nothing to do; parked = deferred action. Likely new `parked_at` + `parked_until` columns, separate column on the board OR a parked-filter chip on category columns. UI shape TBD.
- **T107** — Structured `non_actionable_kind` column on tickets + ai_cache (auto_reply / thanks / spam / out_of_office / other). Enables per-kind filtering + analytics. AI prompt already leads `ai_resolution_reason` with a kind tag — additive migration when needed.

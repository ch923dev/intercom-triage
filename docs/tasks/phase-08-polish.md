# Phase 8 — Polish

Back to [tasks.md](../../tasks.md).

### T043 ✓ — `GET /metrics` lightweight counters
**Depends on:** T028
**Implements:** plan §11
**Description:** In-process counters for `tickets_fetched_total`, `ai_calls_total{result}`, `cache_hits_total`, `overrides_set_total`, `proposals_created_total`, `proposals_resolved_total{resolution}`. Exposed as JSON.
**Acceptance:** Counters increment correctly across a fetch + a resolution.

### T044 ✓ — README + quickstart
**Depends on:** T005, T006, T029, T040
**Implements:** —
**Description:** Top-level README explaining: prerequisites (Python 3.11+, Node 18+, Chrome), how to get an Intercom token, how to get an OpenRouter key, how to populate `.env`, the three commands to run the three surfaces, and how to back up the SQLite file.
**Acceptance:** A fresh checkout brought up to a working board by following the README only.

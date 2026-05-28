# TASK CONTRACTS

One contract per roadmap item. The orchestrator pastes the relevant block into a
subagent dispatch prompt verbatim, prepends the invariant preamble for AI items,
and fills exact file paths. `[AI]` = include invariant preamble.
`[X-PKG]` = cross-package single-PR, do not split.

Each contract: **Scope** (what to build) · **Files** (where) · **Done** (verifiable
acceptance) · **Depends** (must be merged first).

---

## WAVE A — Phase 0

### 0.1 — Doc sync
- Scope: mark Phase 14 tasks T130–T141 `✓` in `tasks.md`; backfill missing
  `FR-037` and `US-019` text into `spec.md` so the matrix stops referencing
  undefined IDs.
- Files: `tasks.md` (~152-163, 229-235), `spec.md`.
- Done: no requirement ID in the matrix lacks a spec definition; Playbooks read
  as shipped. Docs-only, no test impact.
- Depends: none.

### 0.3 — Aging / SLA indicators
- Scope: color ticket cards by time-since-last-customer-message; personal aging
  thresholds (not contractual SLA). Pure webapp.
- Files: webapp card component + styling.
- Done: cards visibly tiered by age; thresholds configurable in one constant.
- Depends: none. Timestamps already on the wire (#5).

### 0.4 — Keyboard-driven triage
- Scope: `j`/`k` navigate, `e` resolve, key-to-category, `/` focus search.
  Pure webapp keybindings (NFR-007).
- Files: webapp keyboard handler + board component.
- Done: full triage loop possible without mouse; no key conflict with inputs.
- Depends: none.

### 0.5 — Debt cleanup
- Scope: remove dead `_ResolverState.fallback_category_id`; align title
  truncation (code caps 120, schema allows 200 — pick one, fix both); delete
  dead `INTERCOM_ACCESS_TOKEN` line from `.env`.
- Files: `pipeline.py:196`, `tickets.py:350`, `schemas.py:383`, `.env`.
- Done: dead code gone, truncation consistent, tests green.
- Depends: none. **Merge BEFORE 0.2** (shared `pipeline.py`).

### 0.2 — Priority + sentiment + multi-label  `[X-PKG]`
- Scope: extend the existing categorization structured response with
  `urgency`/`priority`/`sentiment` and multi-label. Same single AI call — no new
  call, no extra token cost. Backend schema + webapp consumption + extension.
- Files: categorization schema in pipeline; webapp + extension consumers.
- Done: board exposes priority/sentiment; cache key (#6) unchanged; one PR
  across all three packages.
- Depends: 0.5 merged (file ordering).

---

## WAVE B — Phase 1 (all depend on 0.2 merged)

### 1.1 — Saved views / smart filters
- Scope: client-side filter presets (category, age, urgency, resolution source),
  persisted locally. "My morning queue" in one click.
- Done: presets save/load locally; backend untouched (fields already returned).
- Depends: 0.2.

### 1.2 — Priority-sorted queue
- Scope: sort/group board by the 0.2 urgency score; drain top-down.
- Done: board sortable/groupable by priority.
- Depends: 0.2.

### 1.4 — Token / cost meter (T102)
- Scope: per-day OpenRouter spend; add usage counters to `metrics.py`.
- Files: `metrics.py` + webapp surface.
- Done: daily spend visible; counters feed 1.3.
- Depends: 0.2 (wave gate). **Merge before 1.3.**

### 1.3 — Stats dashboard
- Scope: category breakdown, volume trend, resolution-source mix, time-to-resolve
  distribution. Group-by over local SQLite; ties to `resolved_source` (#10).
- Files: backend rollup + webapp dashboard.
- Done: `spec.md §8` four success metrics each rendered.
- Depends: 1.4 merged.

### 1.5 — Snippet / canned-response manager
- Scope: short replies with variable slots (`{{customer_name}}`); lighter than
  playbooks. Keep durable (#13) if extending playbooks table.
- Done: CRUD snippets; variable substitution works.
- Depends: 0.2 (wave gate).

### 1.6 — Bulk pre-flight diff
- Scope: "12 will resolve, 3 skipped" preview before bulk apply. Extends current
  bulk path; keep `MAX_BULK_IDS` synced (#9).
- Done: preview accurate; bulk still respects the cap.
- Depends: 0.2 (wave gate).

---

## WAVE C — Phase 2 reliability (serial chain, NO embedding dep)

### 2.1 — Strict structured outputs  `[AI]`
- Scope: JSON-schema-enforced output via OpenRouter native support; replace
  fragile `{...}` extraction.
- Done: malformed-JSON path effectively eliminated; tests cover schema rejection.
- Depends: none. **Do first in chain.**

### 2.2 — Model cascade  `[AI]`
- Scope: cheap model (Haiku) for easy tickets, escalate to Sonnet on low
  confidence. Route via OpenRouter. MEASURE escalation rate first — if >40%
  escalate, overhead eats savings; report the measurement before full rollout.
- Done: cascade live with logged escalation rate; cost drop demonstrated.
- Depends: 2.1.

### 2.3 — Confidence score + needs-review lane  `[AI]`
- Scope: request confidence in structured output; route low-confidence
  categorizations to a review lane instead of auto-committing. Calibrate against
  override history (ground truth).
- Done: review lane populated by threshold; threshold calibrated, not guessed.
- Depends: 2.2 (shares escalation trigger).

---

## KEYSTONE (dispatch ASAP, parallel with Wave C)

### 2.4 — Local embedding layer  `[AI]`
- Scope: `sentence-transformers` (`all-MiniLM-L6-v2`, CPU, offline) + `sqlite-vec`
  in the existing SQLite DB. Embeddings computed on ingest. **Pin `sqlite-vec`**
  (pre-v1, breaking changes).
- Done: embeddings stored + queryable; fully offline; honors #4 (parts[] only)
  and #6 (no cache bust); pinned dependency versions committed.
- Depends: none. **Gates 2.5, 2.6, 3.1, 3.3. Highest priority to start.**

---

## WAVE D — Phase 2/3 fan-out (ALL depend on 2.4 merged)

### 2.5 — Few-shot categorization from confirmed overrides  `[AI]`
- Scope: retrieve 2–3 nearest confirmed override examples per category, inject
  into prompt. Uses the confirmed-label corpus already captured.
- Done: few-shot examples retrieved from embeddings; measurable consistency gain.
- Depends: 2.4.

### 2.6 — RAG draft replies  `[AI]`
- Scope: ground drafts in resolved tickets + playbooks. Retrieve `parts[]` /
  operator notes ONLY (#4).
- Done: drafts cite retrieved historical context; no `internal_notes[]` leakage.
- Depends: 2.4.

### 3.1 — Recurring-issue clustering  `[AI]`
- Scope: BERTopic / HDBSCAN over embeddings; periodic background job over
  resolved tickets (NOT per-request). HDBSCAN outlier handling; c-TF-IDF labels.
- Done: clusters produced offline; outliers flagged not force-fit.
- Depends: 2.4. **Gates 3.2.**

### 3.3 — AI playbook auto-match on ticket open  `[AI]`
- Scope: semantic auto-match — suggest most-relevant playbook on open. Ticket
  sees playbooks for its EFFECTIVE category (#13).
- Done: top playbook suggested on open; respects effective-category scoping.
- Depends: 2.4.

---

## WAVE E

### 3.2 — "What should I build a playbook for" ⭐  `[AI]`
- Scope: rank clusters (3.1) with NO matching playbook by frequency. Join cluster
  output against playbooks-by-category. Pure local logic.
- Done: ranked gap list; feeds existing playbooks system.
- Depends: 3.1.

---

## PHASE 4 — on demand (not auto-dispatched)

### 4.1 — Parked / snoozed state (T106): `parked_at` + `parked_until` columns. M–L.
### 4.2 — Structured `non_actionable_kind` column (T107)  `[X-PKG]`: enum
  `auto_reply`/`thanks`/`spam`/`out_of_office`; additive migration; one PR across
  backend+webapp+extension (#2).
### 4.3 — Webhook + SSE live updates (T100): push instead of poll. L. Only when
  polling feels stale.
### 4.4 — Bulk actions in extension popup (T105): mirror webapp bulk bar. M.

---

## ROBUSTNESS — continuous side-channel (reserve 1 agent slot)

### R.1 — Intercom payload snapshot tests + unknown-`renderable_type` logging.
### R.2 — Webapp E2E race test: `silentRefresh()` vs in-flight optimistic mutation.
### R.3 — NFR perf integration tests: cold ≤15s (NFR-001), warm ≤3s (NFR-002).
### R.4 — Latency histogram / p95 in `metrics.py` (pairs with R.3 + 1.3).

---

## OUT OF SCOPE — never dispatch
Multi-user/auth/`tenant_id` (T103); leaderboards; CSAT; SLA escalation chains;
autonomous action agents; multi-channel/voice; cloud/Docker/CI/CD/hosted obs.

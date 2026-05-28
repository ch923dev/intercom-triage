# Roadmap

> Forward-looking feature plan for the Intercom triage tool. Synthesized 2026-05-27 from a three-track review: an internal engineering audit, web research on the state of AI support triage, and a spec/plan/tasks gap analysis. Source-of-truth requirements live in `spec.md` / `plan.md` / `tasks.md`; this file sequenced *what to build next* and *why*.

> ## ✅ STATUS — this roadmap is now an execution LOG, not a forward plan
>
> **As of 2026-05-28, Phases 0–3 + 4.1 + R.1 + R.4 are SHIPPED to `main`.** What was a forward plan got executed almost in full. The work landed in code ahead of the source-of-truth docs; the **2026-05-28 reconciliation** wrote it back into `spec.md` v1.7 (US-022..US-039, FR-043..FR-061, NFR-009), `plan.md` v1.7 (§15–§18), and `tasks.md` v1.6 (Phases 15–18, T142–T160; T106/T102 marked `✓`). See the execution ledger below for per-item status + commit. The phase tables further down are kept verbatim as the original plan of record.
>
> **Still open:** Phase 4.3 (webhook + SSE / T100), 4.4 (popup bulk / T105); robustness R.2 (webapp race test), R.3 (perf NFR tests). These are the live backlog.
>
> The original subagent dispatch artifacts that drove this execution are archived under [`docs/roadmap-execution/`](roadmap-execution/) — `TASK_CONTRACTS.md` (per-item contracts) + `DEPENDENCY_SCHEDULE.md` (wave/dependency graph).

## Execution ledger (2026-05-28)

| Roadmap | Item | Status | Task | Commit |
|---------|------|--------|------|--------|
| 0.1 | Doc sync | ✅ done | — | spec v1.6 backfilled US-019/FR-037 etc.; this reconciliation closes the rest |
| 0.2 | Priority + sentiment + multi-label | ✅ shipped | T142 | `784832f` |
| 0.3 | Aging / SLA indicators | ✅ shipped | T143 | `ee99ca5` |
| 0.4 | Keyboard-driven triage | ✅ shipped | T144 | `5630f47` |
| 0.5 | Debt cleanup | ◐ partial | — | folded into feature PRs; `.env` token line is operator-only (audit #2) |
| 1.1 | Saved views / smart filters | ✅ shipped | T145 | `e93084c` |
| 1.2 | Priority-sorted queue | ✅ shipped | T146 | `fe4fa95` |
| 1.3 | Stats dashboard | ✅ shipped | T147 | `c3b9565` |
| 1.4 | Token / cost meter | ✅ shipped | T148 (T102) | `a3074f5` |
| 1.5 | Snippets / canned-response | ✅ shipped | T149 | `86125b1` |
| 1.6 | Bulk pre-flight diff | ✅ shipped | T150 | `58d70a6` |
| 2.1 | Strict structured outputs | ✅ shipped | T151 | `d6a77cf` |
| 2.2 | Model cascade (opt-in) | ✅ shipped | T152 | `6892a31` |
| 2.3 | Confidence + needs-review lane | ✅ shipped | T153 | `4c354c3` |
| 2.4 | Local embedding layer (keystone) | ✅ shipped | T154 | `d917ebd` |
| 2.5 | Few-shot categorization | ✅ shipped | T155 | `e7a2288` |
| 2.6 | RAG draft replies | ✅ shipped | T156 | `cd45ec7` |
| 3.1 | Recurring-issue clustering | ✅ shipped | T157 | `db8272d` |
| 3.2 | Playbook-gap detection ⭐ | ✅ shipped | T158 | `790cf59` |
| 3.3 | Playbook auto-match | ✅ shipped | T159 | `a2de64f` |
| 4.1 | Parked / snoozed state | ✅ shipped | T106 | `889c0f1`, `87522a2` |
| 4.2 | `non_actionable_kind` column | ✅ shipped | T107 | branch `feat/t107-non-actionable-kind` |
| 4.3 | Webhook + SSE live updates | ◯ open | T100 | — |
| 4.4 | Bulk actions in popup | ◯ open | T105 | — |
| R.1 | Payload snapshot tests + unknown-type logging | ✅ shipped | — | `25e7f42` — live capture (workspace j3dxf22l) found event types 21/26/31 unmapped → false unknown-type warns; added to skip set + zero-dep full-output snapshot harness for `normalizeConversation` |
| R.2 | Webapp E2E race test | ◯ open | — | — |
| R.3 | NFR perf integration tests | ◯ open | — | NFR-001/002 still unguarded |
| R.4 | Latency p95 histogram | ✅ shipped | T160 | `ffb28c5` |
| R.5 | Image-only message content loss | ✅ shipped | — | text-less parts carrying `uploads[]` now synthesize an `[attachment: …]` placeholder body (extension-only, no contract change) instead of being dropped; covered by behavioral + snapshot tests |

## Where the project stood (when this was written, 2026-05-27)

The codebase was feature-complete and bug-clean against spec v1.5. The May 2026 audit found **zero open critical/high defects** (all remediated through commit `f0fa441`), the traceability matrix was fully `✓`, and the three-package architecture held its 13 cross-package invariants. That meant this roadmap was about **new capability and small debt cleanup, not remediation** — and that capability has since shipped (see ledger).

Two facts shape everything below:

1. **The constraint is the product.** Single operator, one machine, no auth, no cloud, no multi-tenancy (`CLAUDE.md` scope guardrails). Every item here is filtered for fit. Genuinely-useful-but-out-of-scope ideas (team leaderboards, CSAT surveys, autonomous action agents, multi-channel) are noted and *not* recommended.
2. **A local embedding layer is the keystone.** `sentence-transformers` (`all-MiniLM-L6-v2`, ~80 MB, CPU, offline) + `sqlite-vec` (a zero-dependency vector extension to the SQLite DB we already have) is one piece of infrastructure that unlocks four separate high-value features: RAG draft replies, few-shot categorization from confirmed labels, recurring-issue clustering, and playbook-gap detection. Build it once (Phase 2), harvest it repeatedly (Phase 3).

### Invariant guardrails for everything AI/embedding-related

- **Invariant #4** — embed and retrieve only customer-visible `parts[]` + operator notes. **Never** `internal_notes[]`. This applies to RAG, few-shot, and clustering equally.
- **Invariant #6** — the AI cache key is the content signature (last customer-visible part timestamp). Embedding/clustering jobs must not bust it.
- **Invariant #13** — playbooks are durable operator knowledge, not cache. Anything that reads/writes playbooks keeps them survivable across re-sync.

---

## Phase 0 — Quick wins (days)

Low-risk, no new infrastructure. Several extend the *existing* single AI call or are pure presentation. Ship these first to clear the deck.

| ID | Item | Why | Effort | Notes |
|----|------|-----|--------|-------|
| 0.1 | **Doc sync** — mark Phase 14 (Playbooks, T130–T141) `✓` in `tasks.md`; backfill the missing `FR-037` / `US-019` text into `spec.md` | The matrix references requirement IDs the spec never defines; Playbooks ship in code but read as unbuilt. A future session will mis-read scope. | S | `tasks.md:152-163,229-235` |
| 0.2 | **Priority + sentiment + multi-label in the existing call** | Today the board is category-only. Adding `urgency`/`priority`/`sentiment` to the *same* structured response lets the operator work the queue top-down. No extra token cost, no new call. | S | Extend the categorization schema; respects cache key (#6) |
| 0.3 | **Aging / SLA indicators on cards** | Color cards by time-since-last-customer-message so tickets stop silently rotting. Single-operator "SLA" = personal aging targets, not contractual. | S | Pure webapp; timestamps already on the wire (#5) |
| 0.4 | **Keyboard-driven triage** (`j`/`k` navigate, `e` resolve, key-to-category, `/` search) | Biggest day-to-day throughput win for a solo operator working a queue — never touch the mouse. | M | Pure webapp keybindings; NFR-007 already wants this |
| 0.5 | **Debt cleanup** — remove dead `_ResolverState.fallback_category_id`; align title truncation (code caps 120, schema allows 200); delete dead `INTERCOM_ACCESS_TOKEN` line from `.env` | Trivial correctness/clarity. | S | `pipeline.py:196`, `tickets.py:350` vs `schemas.py:383` |

---

## Phase 1 — Operator throughput + first analytics (1–2 weeks)

UX and visibility. All pure-stack work, no AI infra. Builds directly on Phase 0's priority signal.

| ID | Item | Why | Effort | Notes |
|----|------|-----|--------|-------|
| 1.1 | **Saved views / smart filters** (by category, age, urgency, resolution source) | Define "my morning queue" (urgent + unresolved + >4h old) in one click instead of re-filtering each session. | M | Client-side presets persisted locally; backend already returns the fields |
| 1.2 | **Priority-sorted queue** | Consumes 0.2's score — sort/group the board by urgency so the operator drains top-down. | S | Depends on 0.2 |
| 1.3 | **Stats dashboard** — category breakdown, volume trend, resolution-source mix, time-to-resolve distribution | `spec.md §8` defines four success metrics but nothing aggregates them. `metrics.py` counters are the raw inputs; this is the rollup. | M | Group-by over local SQLite; ties to `resolved_source` (#10) |
| 1.4 | **Token / cost meter** (T102) | Surface OpenRouter spend per day. A solo operator paying for their own API calls wants the number visible. | M | Add usage counters to `metrics.py`; feeds 1.3 |
| 1.5 | **Snippet / canned-response manager** | Playbooks are durable *knowledge*; snippets with variable slots (`{{customer_name}}`) cover high-frequency short replies playbooks over-serve. | M | Extend playbooks or add a lighter table; keep durable (#13) |
| 1.6 | **Bulk pre-flight diff** ("12 will resolve, 3 skipped") | Makes the existing bulk path safe and legible. | S | Extends current bulk; keep `MAX_BULK_IDS` synced (#9) |

---

## Phase 2 — The embedding keystone + smarter AI (2–4 weeks)

The highest-value phase. Stand up the local embedding layer, then immediately cash it in on categorization quality and draft replies. Also land two cheap AI-reliability wins that don't need embeddings.

| ID | Item | Why | Effort | Notes |
|----|------|-----|--------|-------|
| 2.1 | **Strict structured outputs (JSON-schema-enforced)** | Schema-enforced output produces valid JSON ~100% of the time vs. fragile `{...}` extraction. OpenRouter supports it natively. | S | Cheapest reliability win; do before/with 2.2 |
| 2.2 | **Model cascade** — cheap model (e.g. Haiku) for easy tickets, escalate to Sonnet on low confidence | Cascades cut LLM cost 45–85% at ~95% quality; most tickets are easy. | M | Route via OpenRouter. **Measure first** — if >40% escalate, overhead eats the savings |
| 2.3 | **Confidence score + "needs review" lane** | LLMs are confidently wrong; route low-confidence categorizations to a review lane instead of silently committing. We have ground truth (override history) to calibrate against. | M | Ask for confidence in the structured output; pairs with 2.2's escalation trigger |
| 2.4 | **Local embedding layer** — `sentence-transformers` + `sqlite-vec` | The keystone. Embeddings computed on ingest, stored in the existing SQLite DB. Heaviest new dependency (~80 MB model + torch/onnx) but fully offline, fits the no-cloud constraint. | L | Pin `sqlite-vec` (pre-v1, breaking changes). Honor #4/#6 |
| 2.5 | **Few-shot categorization from confirmed overrides** | Operator category overrides are gold-standard labels. Retrieve the 2–3 nearest confirmed examples per category and inject into the prompt — dozens of labels match large-model consistency. | M | Depends on 2.4; uses confirmed-label corpus we already capture |
| 2.6 | **RAG draft replies from resolved tickets + playbooks** | Grounding drafts in our own historical resolutions cuts hallucination and matches the operator's voice — far better than generic generation. | L | Depends on 2.4. Retrieve `parts[]`/operator notes only (#4) |

---

## Phase 3 — Insights harvested from embeddings (1–2 weeks on top of Phase 2)

Once 2.4 exists, these are mostly orchestration. Contains the single most differentiated, on-brand feature.

| ID | Item | Why | Effort | Notes |
|----|------|-----|--------|-------|
| 3.1 | **Recurring-issue clustering** (BERTopic / HDBSCAN over the embeddings) | Surfaces product bugs and repeat-question patterns — recognizes "app keeps crashing" ≈ "can't complete order." HDBSCAN flags outliers instead of forcing junk into clusters; c-TF-IDF auto-labels each cluster. | M | Periodic background job over resolved tickets, not per-request. Reuses 2.4's embeddings |
| 3.2 | **"What should I build a playbook for"** ⭐ | The standout feature. Rank clusters (3.1) that have *no* matching playbook by frequency. Turns analytics into action and feeds straight into the existing playbooks system. Mirrors Intercom's "content gap." | M | Join cluster output against playbooks-by-category; pure local logic |
| 3.3 | **AI playbook auto-match on ticket open** | Playbooks v1 = operator picks from a category-filtered list. The design doc names embedding/semantic auto-match as the natural v2. Suggest the most-relevant playbook automatically. | M | Depends on 2.4. A ticket sees playbooks for its *effective* category (#13) |

---

## Phase 4 — Workflow depth + live updates (heavier / optional)

Larger surface changes, some deferred since Phase 9 backlog. Pull forward individually as need appears; none block earlier phases.

| ID | Item | Why | Effort | Notes |
|----|------|-----|--------|-------|
| 4.1 | **Parked / snoozed state** (T106) | "Waiting on third party / customer / hold." Distinct from non-actionable (nothing to do) — parked = deferred action. Likely `parked_at` + `parked_until` columns. | M–L | UI shape TBD: own column vs. filter chip |
| 4.2 | **Structured `non_actionable_kind` column** (T107) ✅ | `auto_reply` / `thanks` / `spam` / `out_of_office` enables per-kind filtering + analytics (spam-wave detection). AI prompt already emits the kind tag — additive migration. | M | Cross-package (backend + webapp + extension) at API-contract level; HydratedTicket/#2 untouched |
| 4.3 | **Webhook + SSE live updates** (T100) | Biggest deferred feature: `conversation.user.created/replied` → push to webapp + popup instead of poll-on-open. | L | Heaviest; only worth it once volume makes polling feel stale |
| 4.4 | **Bulk actions in the extension popup** (T105) | Mirror the webapp bulk bar in the popup. Deferred because popup ergonomics are cramped. | M | Revisit if the popup's role expands |

---

## Robustness track (run in parallel, ongoing)

Not a phase — slot these alongside feature work to keep the foundation honest as it grows.

| ID | Item | Why | Effort |
|----|------|-----|--------|
| R.1 | **Intercom payload snapshot tests + unknown-`renderable_type` logging** ✅ **shipped 2026-05-28** (`25e7f42`) | The Ember-API scraper is reverse-engineered and fails silently on schema drift. Snapshot-test `normalizeConversation()`, log unknown types instead of skipping. Live capture instead found event types 21/26/31 unmapped → added to the skip set; fixtures kept synthetic (no PII), shape-matched to the capture. | M |
| R.2 | **Webapp E2E race test** — `silentRefresh()` vs. in-flight optimistic mutation | Confirms a background sync can't clobber an operator's pending override. Highest-risk untested path in the webapp. | M |
| R.3 | **NFR perf integration tests** — assert cold-fetch ≤15s (NFR-001), warm-fetch ≤3s (NFR-002) | Both SLAs are stated in `spec.md` with **zero** automated guard today. Add timed integration tests. | M |
| R.4 | **Latency histogram / p95 in `metrics.py`** | `plan.md §11` names this the next observability step once real workload appears. Pairs with R.3 and the 1.3 dashboard. | M |
| R.5 | **Image-only message content loss** — surface `uploads[]` when a part has no text | `normalizeConversation` drops a customer message that carries only an attachment (no text block): `blocksToPlainText` yields `''`, then `if (!body) continue` skips the whole part. Type 1/2/3 parts can carry `uploads[]`. Real content loss; surfaced during the R.1 live capture (2026-05-28). | M |

---

## Explicitly out of scope (noted, not recommended)

These came up in research as industry-standard but conflict with the single-operator local charter (`CLAUDE.md` "Don't"). Recorded so we don't re-litigate them:

- Multi-user / auth / per-user overrides / `tenant_id` (T103) — would reverse the v1 simplification.
- Team performance leaderboards, CSAT survey collection, contractual SLA escalation chains.
- Autonomous action-execution agents (Fin Procedures-level), multi-channel/voice.
- Cloud deployment, Docker, CI/CD, hosted observability.

---

## Suggested sequencing at a glance

```
Phase 0 (days)        quick wins · priority signal · keyboard · debt
   │
Phase 1 (1–2 wk)      saved views · priority sort · stats · cost meter · snippets
   │
Phase 2 (2–4 wk)      structured outputs · cascade · confidence ──┐
                      ★ embedding layer (keystone) ───────────────┤
                      few-shot categorization · RAG drafts ───────┘
   │
Phase 3 (1–2 wk)      clustering · ★ playbook-gap detection · auto-match
   │
Phase 4 (as needed)   parked state · non_actionable_kind · webhook/SSE · popup bulk

Robustness track ───── R.1–R.4 run alongside, continuously
```

Cross-package items (`non_actionable_kind`, any HydratedTicket/contract change) ship in **one PR** across backend + webapp + extension, per `CLAUDE.md`.

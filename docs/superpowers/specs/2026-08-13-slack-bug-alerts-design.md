# Early bug detection → Slack alerts — design spec

**Date:** 2026-08-13 · **Status:** approved (design), unimplemented · **Author:** Christian + Claude
**Type:** new capability — AI detection facet + outbound Slack delivery
**Standalone:** this doc is self-contained on purpose. The contract docs
(`docs/contract/spec.md` / `plan.md` / `tasks.md`) are **not** yet edited; the
exact text to fold into them is carried in
[`§12 Contract fold-in`](#12--contract-fold-in-not-yet-applied) so applying it
later is mechanical.
**Sibling doc:** [`../plans/2026-08-13-slack-bug-alerts.md`](../plans/2026-08-13-slack-bug-alerts.md)
— the task-by-task implementation plan.

---

## Goal

When a customer conversation reports a product bug, engineering hears about it in
Slack — **ranked**, **evidenced**, and **exactly once** — while it is still one
ticket instead of twenty.

Today a breakage surfaces only when an operator happens to read the ticket and
happens to relay it. The categorization pass already reads every conversation with
an LLM; it can render this judgment for free.

---

## Motivation

The AI pipeline already reads every conversation, assigns a category, writes a
summary, judges resolution state, and emits priority/sentiment/labels. Bug
detection is a **judgment on text the model has already been given** — the
marginal cost is a few output tokens, not a second call.

What the current board does *not* give engineering:

- **Push.** The board is pull-only. Nobody watches it out of hours.
- **A bug lens.** `priority=urgent` mixes "angry about billing" with "checkout
  500s". Priority measures operator urgency, not defect existence.
- **Evidence.** A relayed bug loses the customer's own words, which is the part an
  engineer can act on.

---

## Decisions (locked)

| # | Decision | Rationale |
|---|---|---|
| 1 | **Severity floor = `medium`** (`low` recorded, never posted) | Low-severity cosmetic reports are the highest-volume, lowest-value class. Shipping them by default is how a channel gets muted. |
| 2 | **One channel**, config is a plain string | Not a per-severity dict. Severity is conveyed by the message body. Fewer moving parts; a per-severity split is a config change later, not a schema change. |
| 3 | **No backfill** | Existing `ai_cache` rows keep a null verdict. Bugs surface naturally as new customer activity re-categorizes tickets. Zero token spend, zero Slack flood on enable. |
| 4 | **Bot token, post-only** | An incoming webhook returns the literal string `ok` — no message `ts` — making threaded severity updates structurally impossible. See §6. |
| 5 | **Dedup lives in the primary key**, not in application code | An `if already_alerted:` check races between sync cycles. Slack offers no idempotency key. See §3. |
| 6 | **Per-ticket alerts** for v1 | Grouping several tickets under one defect belongs to the existing embedding/cluster layer (US-037), not to a hash of AI-written title text. |
| 7 | **Detection rides the existing categorization call** | Zero extra AI cost; cache key untouched. See §2. |
| 8 | **The confidence floor is an admitted guess** | Unlike `review_confidence_threshold` (calibrated by `backend/tests/test_review_calibration.py`), no labelled bug corpus exists. Intended path: run detect-only, read `GET /bug-alerts`, calibrate, *then* enable delivery. |

---

## Non-goals (v1)

- **Cross-ticket grouping / fingerprinting.** Hashing an AI-written bug title does
  not match differently-worded reports of one defect. Real grouping is the
  `ticket_embeddings` / `TicketCluster` layer's job.
- **Interactive Slack buttons / slash commands.** They need a public request URL,
  which collides with the repo's no-deploy-config rule. Dismissal lives on our own
  API.
- **A webapp Bugs view.** API surface first; board surface is a later slice.
- **A `Settings` DB toggle.** Env-gated for v1; a team-wide toggle on the singleton
  `settings` row is a follow-up.
- **Inbound Slack anything.** No request URL, no event subscriptions, no public
  ingress added by this feature.

---

## 1 · Shape of the feature

Three moving parts, deliberately decoupled:

```
categorization call ──► bug verdict (5th facet, cached on ai_cache)
                             │
                    post-commit record pass
                             │
                             ▼
                   bug_alerts row  (PK = ticket_id)
                             │
                    posted_at IS NULL  ──►  the outbox
                             │
                    background delivery loop  (never inside SYNC_LOCK)
                             │
                             ▼
                    Slack chat.postMessage  ──► slack_ts stored
                             │
                    severity later rises? ──► thread_ts reply
```

The split is the design. Detection is cheap and synchronous; delivery is slow,
network-bound, and must never touch the ingest path.

---

## 2 · Detection as a fifth facet

The bug verdict is added to the **single existing categorization call** — the same
pattern as the triage facets (`priority`/`sentiment`/`labels`, T142) and
`non_actionable_kind` (T107). Three new fields on the JSON response object:

| Field | Type | Meaning |
|---|---|---|
| `bug_severity` | `"low"` \| `"medium"` \| `"high"` \| `null` | `null` = not a bug |
| `bug_confidence` | float `0..1` | model's self-reported confidence |
| `bug_evidence` | string, ≤200 chars | verbatim customer quote that triggered the flag |

Consequences, all load-bearing:

- **Zero extra AI cost.** No second request, no second model, no new client.
- **Cache key untouched** (invariant #6). The verdict is cached on `ai_cache`
  alongside the categorization result and reused on warm fetches. A teammate note
  still does not bust the cache.
- **Fallbacks carry no verdict.** `CategorizationResult.fallback = True` is never
  cached (invariant #7) and must never synthesize a bug verdict — a parse failure
  is not evidence of a bug.
- **`parse_response` stays tolerant.** A missing / malformed / out-of-vocabulary
  severity degrades to "not a bug" for that ticket only. `normalize_bug_severity`
  coerces to the enum or `None`, mirroring `_parse_non_actionable_kind`
  (`app/ai/pipeline.py:188`).
- **Evidence comes from `parts[]` only** (invariant #4). The prompt never sees
  `internal_notes[]`, so the evidence field inherits that by construction.

### The `max_tokens` landmine

`app/clients/openrouter.py:141` hardcodes `"max_tokens": 400` in the request body,
and `complete()` is **shared with playbook drafting** (`app/services/playbooks.py`
draft + draft-reply). Room for the evidence quote is made by adding a `max_tokens`
**parameter** (default 400) and passing the larger value from the categorization
path only. Raising the constant would silently lengthen and re-price playbook
drafts.

> **Accuracy caveat.** Adding a fifth judgment to one prompt can shift
> categorization quality, and the AI tests use canned responses — they cannot
> detect that drift. Same blind spot that let the `json_schema` → 400 regression
> ship green (T151 amendment). Validate against live traffic, not the suite.

### Stale comments to fix while here

Two in-code comments still claim the categorization call sends strict
`json_schema`; T151 reverted that to `json_object`
(`CATEGORIZATION_RESPONSE_FORMAT` at `app/ai/prompt.py:156`):

- `app/clients/openrouter.py` `complete()` docstring, ~`:124-129`
- `app/ai/pipeline.py:_complete`, ~`:492-495`

---

## 3 · Data model — the primary key *is* the dedup guarantee

```
bug_alerts
  ticket_id          TEXT  PK          -- one row per ticket, forever
  severity           TEXT  NOT NULL    -- low | medium | high (CHECK)
  confidence         REAL  NOT NULL
  evidence           TEXT              -- verbatim customer quote, nullable
  occurrences        INT   NOT NULL 1  -- re-detections, not reposts
  first_detected_at  DATETIME NOT NULL
  last_detected_at   DATETIME NOT NULL
  posted_at          DATETIME          -- NULL = undelivered  → the outbox
  posted_severity    TEXT              -- delivery truth, not model truth
  slack_channel      TEXT
  slack_ts           TEXT              -- parent message id, for threading
  dismissed_at       DATETIME          -- permanent suppression
```

Plus three additive columns on `ai_cache`: `bug_severity`, `bug_confidence`,
`bug_evidence`. Pre-existing rows carry NULL (decision 3 — no backfill).

Design points that are decisions, not details:

- **Dedup is a DB constraint, not an application check.** `PK = ticket_id` makes a
  duplicate row impossible. An `if already_alerted:` guard races between two sync
  cycles; a unique constraint cannot. Slack offers no idempotency key of its own,
  so this table is the only place dedup can live. Insert-or-bump is one upsert:
  conflict on the PK → `occurrences += 1`, refresh `last_detected_at`.
- **Identity is the ticket, and only the ticket.** Not severity, not
  `occurrences`, not AI-written title text — any of which would forge a fresh
  identity on the next sync and repost.
- **`posted_at IS NULL` is the outbox.** No queue table, no broker. It survives
  restart, and a Slack outage self-heals on the next delivery pass.
- **`posted_severity` is delivery truth, deliberately separate from `severity`
  (model truth).** Escalation is `severity > posted_severity`; a downgrade or a
  re-detection at equal severity posts nothing.
- **No FK to `tickets`** — the id is Intercom-owned, matching `followups` and
  `ticket_cluster_members`.
- Migration **0027** (head is 0026), forward-only, `batch_alter_table` for SQLite.

### Why not the obvious alternatives

| Alternative | Why rejected |
|---|---|
| "Have I sent this?" check in the record pass | Races between concurrent sync cycles. TOCTOU. |
| Slack message dedup key | Slack has no idempotency key. `chat.postMessage` will happily post twice. |
| Hash of the AI bug title as identity | AI-written text varies run to run → new hash → repost. |
| A queue table / broker | `posted_at IS NULL` already *is* a durable queue, with no new infra and no new failure mode. |
| Reuse `tickets` columns | Board-state bloat, and the alert lifecycle (posted/dismissed/threaded) is not ticket state. |

---

## 4 · Record / deliver split

**Record** — post-commit hook in `app/services/tickets.py:ingest_tickets`, cloning
the `_embed_ingested_tickets` shape (`app/services/tickets.py:286-321`): runs
after `commit()`, owns its transaction, catches broad `Exception` →
`rollback()` + `logger.warning(exc_info=True)`. A failure to record must never
fail an ingest.

**Deliver** — a background loop (the fifth, alongside `_cache_sweep_loop` /
`_attachment_sweep_loop` / `_clustering_loop` / `_intercom_poll_loop` in
`app/main.py`), interval-gated and default-off like the Intercom poller. Selects
`posted_at IS NULL AND dismissed_at IS NULL`, severity-desc, bounded per pass.

Why split at all: **no Slack HTTP call may occur inside `SYNC_LOCK`.** A slow or
hanging Slack request would stall the whole sync cycle, and Slack's ~1 msg/sec
per-channel budget makes a burst of alerts inherently slow. The split also makes
retries free — an undelivered row is simply still there next pass.

Counts are reported through `metrics`, **not** on `SyncResponse`: that schema's key
set is asserted exactly in `backend/tests/test_sync_api.py:41`, and it is the wrong
layer anyway (a sync response should not describe Slack).

---

## 5 · Alert lifecycle

| Event | Effect |
|---|---|
| First detection ≥ floor | Row inserted, `posted_at` NULL → in the outbox |
| Re-detection, same/lower severity | `occurrences += 1`, `last_detected_at` refreshed. **No post.** |
| Re-detection, higher severity | `severity` raised. Delivery pass sees `severity > posted_severity` → **threaded reply**, `posted_severity` updated |
| Detection below floor | Recorded (readable via API), never posted |
| Delivery succeeds | `slack_ts`, `slack_channel`, `posted_severity`, `posted_at` stored |
| Delivery fails | Row untouched → retried next pass, across restarts |
| Operator dismisses | `dismissed_at` set → never posted again |
| Slack unconfigured | Detection + recording continue; delivery disabled |

---

## 6 · Slack transport

`app/clients/slack.py`, built to the house style of `clients/openrouter.py` /
`clients/intercom.py`: injectable `httpx.AsyncClient`, `_owns_http` + `aclose()`,
retry on `{429, 500, 502, 503, 504}`, 3 attempts, jittered exponential backoff,
`Retry-After` honored, `SlackError` / `SlackAuthError`.

- **Bot token + `chat.postMessage`, never an incoming webhook.** A webhook returns
  the literal string `ok` — no message `ts` — which makes `thread_ts` replies and
  `chat.update` structurally impossible. Scopes: `chat:write` (+
  `chat:write.public` to post to a channel the bot has not joined).
- **Slack returns HTTP 200 with `{"ok": false, "error": "..."}`** on application
  errors. The client checks the **body**, not the status code. `invalid_auth` /
  `channel_not_found` are permanent → do not retry; `ratelimited` → retry.
- Escalation posts with `thread_ts = slack_ts` so the update lands under the
  original card instead of as a new alert.
- Rate budget ~1 msg/sec/channel → delivery is bounded per pass, not burst.

### Security

- `slack_bot_token` is a **`SecretStr`** in `AppConfig`. Note the existing
  `openrouter_api_key` (`app/config.py:45`) and `intercom_access_token`
  (`:56`) are plain `str`; the new secret does not repeat that.
- Surfaced on `/health` as `slack_configured`, but **not** added to
  `missing_secrets` (`app/config.py:208`): an unconfigured Slack is a disabled
  feature, not a degraded service.
- A gitleaks rule for `xoxb-` tokens is added to the existing `.gitleaks.toml`.
- **Evidence quotes are never logged.** `logged_call` takes identifiers only;
  alert log lines carry `ticket_id`, severity, and outcome. This is NFR-006
  extended to a new field.

---

## 7 · API surface

- `GET /bug-alerts?severity=&delivered=` — recorded verdicts with evidence,
  occurrence count, and delivery state.
- `POST /bug-alerts/{ticket_id}/dismiss` — permanent suppression.

Auth-gated like every other router (invariant #15) — the new path is added to the
`backend/tests/test_auth_required.py:15` parametrize list, which is the enforcement
mechanism for that invariant.

This endpoint is what makes **detect-only operation** useful: the operator reads
real verdicts and calibrates the confidence floor before Slack is ever wired up
(decision 8).

---

## 8 · Config

New `# ── Slack bug alerts ─────` block in `AppConfig`:

| Setting | Default | Notes |
|---|---|---|
| `slack_bot_token` | `""` (SecretStr) | empty = delivery off |
| `slack_bug_channel` | `""` | plain string — one channel (decision 2) |
| `bug_alerts_enabled` | `False` | master switch for detection + recording |
| `bug_alert_min_severity` | `"medium"` | the floor (decision 1) |
| `bug_alert_min_confidence` | `0.6` | an admitted guess (decision 8) |
| `bug_alert_poll_interval_seconds` | `0` | `0` = delivery loop off |
| `bug_alert_max_per_cycle` | `10` | bounds a burst against Slack's rate budget |

Note `intercom_poll_interval_seconds` also defaults to `0` — early detection is
not early if nobody presses Sync. Worth enabling the poller alongside this feature.

---

## 9 · Invariants touched

| Invariant | Effect |
|---|---|
| #2 `HydratedTicket` spans two packages | **Untouched.** Bug alerts are board/alert state, not conversation shape. No webapp type change in v1. |
| #4 `parts[]` vs `internal_notes[]` | **Upheld by construction** — evidence is drawn from the prompt, which never sees `internal_notes[]`. |
| #6 cache key = content signature | **Untouched.** The verdict is cached *value*, not key input. |
| #7 fallbacks never cached | **Upheld** — a fallback carries no verdict, and a verdict is never synthesized. |
| #15 auth on every route | New `/bug-alerts` router gets `get_current_user` + the `test_auth_required` parametrize entry. |
| NFR-006 never log conversation bodies | **Extended** to `bug_evidence`. |

No new invariant is needed; #4/#6/#7/#15 already cover the risky edges.

---

## 10 · Testing

- **Parser:** verdict present / absent / malformed severity / out-of-vocabulary
  severity / evidence over length → coerced or `None`, never raises.
- **Fallback:** a fallback result carries no verdict and is not cached.
- **Cache round-trip:** verdict survives `set_cached` → `get_cached` at all three
  `app/services/cache.py` sites (`:48` read reconstruction, `:79` insert branch,
  `:96` update branch).
- **Dedup:** two record passes over the same ticket → one row, `occurrences == 2`.
- **Floor:** `low` recorded, not queued; `medium`/`high` queued.
- **Escalation:** `medium` delivered then `high` detected → threaded reply,
  `posted_severity` updated. Downgrade → nothing.
- **Outage:** Slack raising → row still `posted_at IS NULL`, retried next pass.
- **Ingest isolation:** record pass raising → ingest still succeeds.
- **Auth:** `/bug-alerts` returns 401 unauthenticated.
- **Not testable by the suite:** categorization-quality drift from the fifth
  prompt facet (canned responses). Live traffic only.

---

## 11 · Slice plan

**Slice 1 — detect + record.** No Slack, no token needed. Ships the verdict,
migration 0027, and the record pass. Immediately useful: run it, read
`GET /bug-alerts`, calibrate the floor.

**Slice 2 — deliver.** Slack client, delivery loop, read + dismiss router.

Task-by-task detail: [`../plans/2026-08-13-slack-bug-alerts.md`](../plans/2026-08-13-slack-bug-alerts.md).

---

## 12 · Contract fold-in (not yet applied)

Repo rule (`CLAUDE.md` → "Don't"): the surface area is not extended without
`spec.md` / `plan.md` / `tasks.md` updates first. This design deliberately keeps
the contract docs **untouched** so the feature can be reviewed standalone. When it
is greenlit, apply exactly this:

### spec.md → v2.2

- Header version bump + changelog paragraph.
- §2 Scope, append: **Outbound Slack alerts for early-detected product bugs**
  (one-way, post-only).
- New **US-044 — Early bug detection alerted to Slack**, acceptance bullets per
  §1–§7 above.
- **FR-075** — detection facet (the three fields, cached, no second call, cache key
  unchanged, fallback carries no verdict, pre-existing rows null).
- **FR-076** — record: one row per ticket keyed by ticket id, duplicate impossible
  by construction rather than by application check; repeat → occurrence bump;
  post-commit; failure never fails ingest.
- **FR-077** — deliver: undelivered rows posted to one configured channel,
  severity-desc, bounded per pass; `ts` stored before marking delivered; escalation
  → threaded reply; downgrade/equal → nothing; dismissed → never.
- **FR-078** — decoupling: no Slack call inside a sync cycle; outage leaves rows
  undelivered not lost; resumes after restart; unconfigured Slack disables delivery
  only.
- **FR-079** — `GET /bug-alerts` (filterable) + `POST /bug-alerts/{ticket_id}/dismiss`,
  both authenticated.
- **NFR-015** — Slack token is a server-side secret; missing token disables
  delivery, reported by `/health`, not fatal, does not mark degraded.
- **NFR-016** — evidence quotes never logged; alert log lines carry identifiers,
  severity, outcome only.
- §7 Decisions — five bullets: transport, dedup, grouping, confidence floor
  (explicitly a guess, unlike `review_confidence_threshold`), backfill.

> Row format: FR/NFR table rows are `| ID | text | US-xxx |`. Enum lists inside a
> row escape the pipe inside backticks — `` (`low`\|`medium`\|`high`) `` — matching
> FR-043 / FR-062.

### plan.md → v2.1

New **§20 — Early bug detection → Slack alerts**, carrying §2 (detection facet +
the `max_tokens` caveat), §3 (the DDL block + the dedup reasoning), §4 (record /
deliver split), §6 (post-only Slack client), §7 (read + dismiss), §8 (config), and
the non-goals as "deliberately deferred". Cite migration 0027 and T173–T178.

### tasks.md → v2.1

New **Phase 22 — Early bug detection → Slack alerts**, two slices:

| Task | Scope |
|---|---|
| T173 | Bug verdict as fifth facet; `max_tokens` **parameter**; `normalize_bug_severity`; fix the two stale `json_schema` comments |
| T174 | Migration 0027 — three `ai_cache` columns (all three `cache.py` sites) + the `bug_alerts` table |
| T175 | `services/bug_alerts.py:record_bug_alerts` post-commit pass; insert-or-bump upsert; counts via `metrics` not `SyncResponse` |
| T176 | `clients/slack.py` post-only; body-not-status error check; `SecretStr`; `xoxb-` gitleaks rule |
| T177 | Delivery loop (fifth bg loop, default off); Block Kit message; escalation threading |
| T178 | `GET /bug-alerts` + dismiss; add `"/bug-alerts"` to `test_auth_required.py` parametrize |

Traceability rows to add:

```
| US-044 | T173, T174, T175, T176, T177, T178 |
| FR-075 | T173 |
| FR-076 | T174, T175 |
| FR-077 | T176, T177 |
| FR-078 | T175, T177 |
| FR-079 | T178 |
| NFR-015 | T176 |
| NFR-016 | T176 |
```

> Pre-existing, unrelated: the traceability matrix has no rows for US-001..US-005
> / US-007..US-014. It has always started at FR-001. Not introduced here.

---

## Touch-point summary

| File | Change |
|---|---|
| `backend/app/ai/prompt.py` | `SYSTEM_PROMPT` — three fields on all three response options + a BUG rules block |
| `backend/app/ai/pipeline.py` | `ParsedAssignment` + `CategorizationResult` fields, `normalize_bug_severity`, `parse_response`, all `_fallback`/build sites; fix stale `_complete` comment |
| `backend/app/clients/openrouter.py` | `max_tokens` parameter (default 400); fix stale docstring |
| `backend/app/models.py` | `AiCache` three columns + new `BugAlert` model |
| `backend/alembic/versions/0027_*.py` | new revision, `batch_alter_table` |
| `backend/app/services/cache.py` | three sites — `:48`, `:79`, `:96` |
| `backend/app/services/bug_alerts.py` | **new** — record + query + dismiss + deliver-one |
| `backend/app/services/tickets.py` | post-commit `record_bug_alerts` at both `_embed_ingested_tickets` call sites (`:359`, `:442`) |
| `backend/app/clients/slack.py` | **new** — post-only client |
| `backend/app/routers/bug_alerts.py` | **new** — read + dismiss |
| `backend/app/main.py` | fifth background loop + router registration |
| `backend/app/config.py` | Slack bug-alerts config block |
| `backend/app/routers/health.py` | `slack_configured` |
| `.gitleaks.toml` | `xoxb-` rule |
| `backend/tests/test_auth_required.py` | `"/bug-alerts"` in the parametrize list |
| `docs/contract/*` | **deferred** — see §12 |

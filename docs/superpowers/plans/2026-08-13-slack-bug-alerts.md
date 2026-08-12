# Early Bug Detection → Slack Alerts Implementation Plan

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax for tracking. Implement
> task-by-task, running the gate after each. **Nothing in this plan is authorized
> yet** — the feature is design-approved and unimplemented as of 2026-08-13.

**Goal:** When a conversation reports a product bug, engineering hears about it in
Slack — ranked, evidenced, exactly once — while it is still one ticket.

**Architecture:** The bug verdict is a **fifth facet** on the existing
categorization call (zero extra AI cost, cache key untouched). Verdicts are recorded
in a `bug_alerts` table whose **primary key is the dedup guarantee** and whose
`posted_at IS NULL` rows **are the outbox**. A background delivery loop — never
inside `SYNC_LOCK` — posts each one to one Slack channel via a post-only bot-token
client, and posts a threaded reply when severity later rises.

**Tech Stack:** FastAPI + async SQLAlchemy 2.0 + Alembic + SQLite (Postgres-swappable);
`httpx` for the Slack client. Backend-only — no webapp change in v1.

**Source spec:** [`../specs/2026-08-13-slack-bug-alerts-design.md`](../specs/2026-08-13-slack-bug-alerts-design.md)

**Standalone:** contract docs (`docs/contract/spec.md` / `plan.md` / `tasks.md`) are
deliberately **not** edited yet. The exact fold-in text lives in the design doc §12.
Task 10 applies it.

---

## Conventions for every task

- Backend: `from __future__ import annotations` at top; `naive_utcnow()` for the DB
  clock; services raise `HTTPException`; services own commits; ruff + mypy strict.
- **Run the gate from `backend/` using the venv python, not global python312** —
  bare `ruff` 0.9.3 / Pillow 10.1.0 drift off pins and produce phantom failures:
  ```
  ruff check app tests && ruff format --check app tests && mypy app && pytest -q
  ```
- Commit after each task. Branch first (we are on `main`):
  `git checkout -b feat/slack-bug-alerts`.
- **Do not put model-constraint tests in `tests/test_models.py`** — staging that file
  blocks commits (pre-existing `create_all` hook issue). Use a new file.

## Execution waves (dependencies)

```
SLICE 1 — detect + record (no Slack, no token needed)
  Task 1 (prompt+parser)  →  Task 2 (models+migration 0027)  →  Task 3 (cache)
                                                              →  Task 4 (record pass)
SLICE 2 — deliver
  Task 5 (slack client)  →  Task 6 (delivery service)  →  Task 7 (bg loop + config)
                                                       →  Task 8 (router)
  Task 9 (live validation — manual)  →  Task 10 (contract docs)  →  Task 11 (gate + PR)
```

Slice 1 is independently shippable and immediately useful: run it, read
`GET /bug-alerts` (or the DB) for a week, calibrate the confidence floor, *then* do
slice 2.

---

# SLICE 1 — detect + record

## Task 0: Branch

- [ ] **Step 1: Create the feature branch**

```bash
git checkout -b feat/slack-bug-alerts
```

---

## Task 1: Bug verdict as a fifth facet (prompt + parser)

**Files:**
- Modify: `backend/app/ai/prompt.py` (`SYSTEM_PROMPT` ~`:21-90`, rules block ~`:110-135`)
- Modify: `backend/app/ai/pipeline.py` (`ParsedAssignment` ~`:44`, `CategorizationResult` ~`:63`, `parse_response` ~`:199`, all three build sites `:226`/`:245`/`:266`, all four result sites `:309`/`:327`/`:351`/`:377`, `_complete` ~`:480`)
- Modify: `backend/app/clients/openrouter.py` (`complete()` ~`:111-142`)
- Test: `backend/tests/test_bug_verdict_parse.py` (new)

- [ ] **Step 1: Write the failing parser tests (RED)**

Cover: verdict present at each severity; `bug_severity` absent → `None`;
out-of-vocabulary severity (`"critical"`, `"HIGH"`, `""`, `5`) → `None` (case-insensitive
match on the three known values, everything else `None`); `bug_confidence` non-numeric
→ `None`; `bug_evidence` over 200 chars → truncated; evidence present with
`bug_severity=None` → verdict dropped entirely. **`parse_response` must never raise**
on any of these.

- [ ] **Step 2: Add the three fields to `ParsedAssignment` and `CategorizationResult`**

```python
# ParsedAssignment
bug_severity: BugSeverity | None = None
bug_confidence: float | None = None
bug_evidence: str | None = None

# CategorizationResult — same three, same defaults
```

`BugSeverity = Literal["low", "medium", "high"]`. Defaults are `None` everywhere, so
**a fallback result carries no verdict by construction** (invariant #7).

- [ ] **Step 3: Add `normalize_bug_severity`**

Mirror `_parse_non_actionable_kind` (`pipeline.py:188`): coerce a `str` to the enum
case-insensitively, return `None` for anything else. Drop `bug_confidence` /
`bug_evidence` when severity is `None` — no severity means no bug, so the other two
fields are meaningless.

- [ ] **Step 4: Thread the verdict through `parse_response` and all build sites**

`parse_response` reads the three keys once, then passes them into each of the three
`ParsedAssignment(...)` constructions (`:226`, `:245`, `:266`), exactly as
`non_actionable_kind` is threaded today. Then each `CategorizationResult(...)` site
(`:309`, `:327`, `:351`, `:377`) forwards them — **except any fallback path, which
leaves them `None`.**

- [ ] **Step 5: `max_tokens` as a parameter on `OpenRouterClient.complete`**

```python
async def complete(
    self,
    *,
    model: str,
    messages: list[dict[str, str]],
    ticket_id: str | None = None,
    response_format: dict[str, Any] | None = None,
    max_tokens: int = 400,          # ← new
) -> str:
```

and in the body, `"max_tokens": max_tokens` (was the literal `400` at `:141`).

> **Why a parameter, not a bigger constant.** `complete()` is shared with playbook
> drafting (`app/services/playbooks.py` draft + draft-reply). Raising the constant
> silently lengthens and re-prices those. Only `pipeline._complete` passes the larger
> value (~550).

- [ ] **Step 6: Fix the two stale `json_schema` comments**

Both claim the categorization call sends strict `json_schema`; T151 reverted that to
`json_object` (`CATEGORIZATION_RESPONSE_FORMAT`, `app/ai/prompt.py:156`):
- `app/clients/openrouter.py` docstring, ~`:124-129`
- `app/ai/pipeline.py:_complete`, ~`:492-495`

- [ ] **Step 7: Extend `SYSTEM_PROMPT`**

Add the three fields to **all three** response options (A/B/C — `:36`, `:52`, `:70`
regions), and a BUG rules block alongside the existing RESOLUTION / TRIAGE blocks:

```
BUG rules (add these THREE fields to EVERY response object):
- "bug_severity": is the customer reporting a PRODUCT DEFECT — something that
  behaves other than as designed? Not a question, not a feature request, not a
  billing dispute, not user error.
    "high"   — data loss/corruption, security exposure, an outage, payments
               broken, or a core flow unusable with no workaround.
    "medium" — a feature is broken or wrong for this customer but a workaround
               exists, or it affects a non-core flow.
    "low"    — cosmetic, a typo, a slow/awkward behavior, or a rare edge case.
    null     — NOT a bug report. This is the default; prefer null when unsure.
- "bug_confidence": <float 0..1> how sure you are this is a real product defect.
- "bug_evidence": the customer's OWN WORDS that show the defect — one verbatim
  quote, <=200 chars, copied exactly from the conversation, no paraphrase and no
  commentary. Use "" when bug_severity is null.
```

Bias to `null` is deliberate: a false positive costs channel trust, a false negative
costs one delayed ticket.

- [ ] **Step 8: Pass the larger `max_tokens` from `_complete` only**

In `pipeline._complete` (`~:490`), add `max_tokens=550` to the `client.complete(...)`
call. Leave every other caller alone.

- [ ] **Step 9: Run the gate (GREEN)**

> **Accuracy caveat — read this.** The AI tests use canned responses, so they
> **cannot** detect that a fifth judgment degraded categorization quality. This is
> the same blind spot that let the `json_schema` → 400 regression ship green (T151).
> Task 9 is the real check; do not treat a green suite as validation of prompt quality.

---

## Task 2: Models + migration 0027

**Files:**
- Modify: `backend/app/models.py` (`AICacheEntry` ~`:130`; new `BugAlert` class)
- Create: `backend/alembic/versions/0027_add_bug_alerts.py`
- Test: `backend/tests/test_bug_alerts_model.py` (new — **not** `test_models.py`, see Conventions)

- [ ] **Step 1: Write the failing constraint tests (RED)**

Assert: `severity` outside `{low, medium, high}` → `IntegrityError`; a second insert
with the same `ticket_id` → `IntegrityError`; `evidence` over 200 chars →
`IntegrityError`; `occurrences` defaults to 1.

- [ ] **Step 2: Three additive columns on `AICacheEntry`**

`bug_severity: Mapped[str | None]`, `bug_confidence: Mapped[float | None]`,
`bug_evidence: Mapped[str | None]` — all nullable, mirroring how
`ai_resolution_verdict` / `non_actionable_kind` sit on the same model. Pre-existing
rows carry NULL (design decision 3 — no backfill).

- [ ] **Step 3: New `BugAlert` model**

Copy the shape of `Followup` (`app/models.py:358` — PK `ticket_id`, **no FK**,
"the ticket id is owned by Intercom"):

```python
class BugAlert(Base):
    """One AI-detected product-bug report per ticket (US-044).

    `ticket_id` is the PK, and that IS the dedup guarantee — a duplicate Slack
    post is impossible by construction rather than by an application-level
    "have I sent this?" check, which would race between two sync cycles. Slack
    offers no idempotency key of its own, so this row is the only place dedup
    can live. No FK: the ticket id is owned by Intercom (cf. `followups`).

    `posted_at IS NULL` IS the outbox — no queue table, no broker. It survives
    restart and self-heals after a Slack outage. `posted_severity` is delivery
    truth, deliberately separate from `severity` (model truth): escalation is
    `severity > posted_severity`.
    """

    __tablename__ = "bug_alerts"

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence: Mapped[str | None] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(default=1, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_detected_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    posted_at: Mapped[datetime | None] = mapped_column(DateTime)
    posted_severity: Mapped[str | None] = mapped_column(Text)
    slack_channel: Mapped[str | None] = mapped_column(Text)
    slack_ts: Mapped[str | None] = mapped_column(Text)
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('low','medium','high')",
            name="bug_alerts_severity_check",
        ),
        CheckConstraint(
            "posted_severity IS NULL OR posted_severity IN ('low','medium','high')",
            name="bug_alerts_posted_severity_check",
        ),
        CheckConstraint(
            "evidence IS NULL OR length(evidence) <= 200",
            name="bug_alerts_evidence_len_check",
        ),
        CheckConstraint("occurrences >= 1", name="bug_alerts_occurrences_check"),
        Index("ix_bug_alerts_outbox", "posted_at", "dismissed_at"),
    )
```

- [ ] **Step 4: Migration 0027**

Model it on `0026_add_ai_cache_subject.py` — `revision = "0027"`,
`down_revision = "0026"`, `batch_alter_table` for the `ai_cache` columns (mandatory on
SQLite), `op.create_table` for `bug_alerts` with the CHECK constraints named as above.
Forward-only; `downgrade()` drops the table and the three columns.

> **Serialize this.** The Alembic chain is linear with sequential numeric prefixes.
> Only one session adds a migration at a time (CLAUDE.md → Parallel sessions). If
> another branch has taken 0027, renumber.

- [ ] **Step 5: Apply + gate**

```bash
alembic upgrade head && alembic current
```

---

## Task 3: Cache round-trip — all three sites

**Files:**
- Modify: `backend/app/services/cache.py` (`:42-51` read reconstruction, `:79-82` insert branch, `:96-99` update branch)
- Test: `backend/tests/test_bug_verdict_cache.py` (new)

- [ ] **Step 1: Write the failing round-trip test (RED)**

`set_cached` a result with a `high` verdict → `get_cached` returns all three fields
intact. Then `set_cached` the same ticket with `bug_severity=None` → the update branch
clears all three (a bug that stops being reported must not stick).

- [ ] **Step 2: Assign the three fields at all three sites**

Exactly mirroring `ai_resolution_verdict` / `non_actionable_kind`:
- `:42` — the `CategorizationResult(...)` reconstruction (with the same
  `# type: ignore[arg-type]` treatment the sibling `Literal` fields need)
- `:79` — the insert branch
- `:96` — the update branch

> **All three or nothing.** Missing the read site means a warm cache hit silently
> drops the verdict; missing the update branch means a stale verdict outlives the
> report. This is the same class of miss as the `subject` cache-hit title wipe that
> migration 0026 exists to fix.

- [ ] **Step 3: Gate**

---

## Task 4: Record pass (post-commit, ingest-safe)

**Files:**
- Create: `backend/app/services/bug_alerts.py`
- Modify: `backend/app/services/tickets.py` (call sites at `:359` and `:442`, beside `_embed_ingested_tickets`)
- Modify: `backend/app/config.py` (new config block)
- Test: `backend/tests/test_bug_alerts_record.py` (new)

- [ ] **Step 1: Write the failing tests (RED)**

- Two record passes over the same ticket → **one** row, `occurrences == 2`,
  `last_detected_at` advanced, `first_detected_at` unchanged.
- `low` severity → recorded but (later) never queued; `medium`/`high` → queued.
- Below `bug_alert_min_confidence` → not recorded.
- `bug_alerts_enabled=False` → no-op.
- **Record pass raising → `ingest_tickets` still returns normally** (the invariant that
  matters most here).
- An already-dismissed ticket re-detected → `occurrences` bumps, `dismissed_at`
  stays set.

- [ ] **Step 2: Config block**

```python
    # ── Slack bug alerts ──────────────────────────────────────────────────────
    # Detection rides the existing categorization call (zero extra AI cost).
    # An unconfigured Slack disables DELIVERY only — detection and recording
    # continue, readable via GET /bug-alerts. The token is a SecretStr (the
    # older openrouter/intercom keys are plain str; do not copy that).
    slack_bot_token: SecretStr = SecretStr("")
    slack_bug_channel: str = ""
    bug_alerts_enabled: bool = False
    bug_alert_min_severity: Literal["low", "medium", "high"] = "medium"
    bug_alert_min_confidence: float = Field(default=0.6, ge=0.0, le=1.0)
    bug_alert_poll_interval_seconds: int = Field(default=0, ge=0)
    bug_alert_max_per_cycle: int = Field(default=10, ge=1)
```

Plus a `slack_configured` property. **Do not add Slack to `missing_secrets`**
(`config.py:208`) — an unconfigured Slack is a disabled feature, not a degraded
service.

> `bug_alert_min_confidence` is an **admitted guess** — unlike
> `review_confidence_threshold`, which is calibrated by
> `backend/tests/test_review_calibration.py`. No labelled bug corpus exists yet.

- [ ] **Step 3: `record_bug_alerts`**

```python
async def record_bug_alerts(
    session: AsyncSession,
    results: dict[str, CategorizationResult],
    config: AppConfig,
) -> None:
    """Best-effort record pass over a just-ingested batch.

    Runs AFTER ingest has already committed, in its own transaction, so a
    failure can never roll back or break ingest — the worst case is a missing
    alert row that the next sync refills. Mirrors `_embed_ingested_tickets`.
    """
```

Body: early-return when `not config.bug_alerts_enabled`; filter to verdicts at or
above `bug_alert_min_severity` **and** `bug_alert_min_confidence`; **insert-or-bump in
one upsert** (`sqlite_on_conflict_do_update` / `ON CONFLICT (ticket_id) DO UPDATE` —
never SELECT-then-INSERT, which reintroduces the race the PK exists to prevent). On
conflict: `occurrences = occurrences + 1`, refresh `last_detected_at`, raise `severity`
+ refresh `confidence`/`evidence` when the new severity is higher; leave `posted_*` and
`dismissed_at` alone. Then `commit()`; `metrics.incr("bug_alerts_recorded_total", n)`.

Wrap the whole body in `try/except Exception` → `await session.rollback()` +
`logger.warning(..., exc_info=True)`, exactly as `_embed_ingested_tickets` does
(`tickets.py:317-321`).

- [ ] **Step 4: Wire both call sites**

Immediately after each `await _embed_ingested_tickets(session, hydrated, config)`
(`tickets.py:359` and `:442`), add
`await record_bug_alerts(session, results, config)`. **Post-commit, both sites** —
missing the second means the `POST /tickets/ingest` path silently never records.

- [ ] **Step 5: Counts via `metrics`, never `SyncResponse`**

`backend/tests/test_sync_api.py:41` asserts `SyncResponse`'s exact key set
(`{"received","categorized","skipped_known","closed_detected"}`). Adding a key breaks
it, and a sync response is the wrong layer to describe Slack anyway.

- [ ] **Step 6: Gate. Slice 1 is now shippable.**

---

# SLICE 2 — deliver

## Task 5: Slack client (post-only)

**Files:**
- Create: `backend/app/clients/slack.py`
- Modify: `.gitleaks.toml` (repo root — `xoxb-` rule)
- Modify: `backend/app/routers/health.py` (`slack_configured`)
- Test: `backend/tests/test_slack_client.py` (new)

- [ ] **Step 1: Write the failing tests (RED)**

- HTTP 200 + `{"ok": true, "ts": "1723...", "channel": "C..."}` → returns the `ts`.
- **HTTP 200 + `{"ok": false, "error": "channel_not_found"}` → raises, no retry.**
  Slack signals application errors with a 200; a status-code check would treat this
  as success and mark the row delivered.
- `{"ok": false, "error": "invalid_auth"}` → `SlackAuthError`, no retry.
- `{"ok": false, "error": "ratelimited"}` → retried.
- HTTP 429 with `Retry-After` → honored.
- `thread_ts` passed → present in the request body.
- **Evidence text never appears in any log record** (assert on `caplog`).

- [ ] **Step 2: Build the client to house style**

Mirror `clients/openrouter.py` / `clients/intercom.py`: injectable
`httpx.AsyncClient`, `_owns_http` + `aclose()`, retry on `{429, 500, 502, 503, 504}`,
3 attempts, jittered exponential backoff, `Retry-After` honored, `SlackError` /
`SlackAuthError`. One method:

```python
async def post_message(
    self, *, channel: str, text: str, blocks: list[dict[str, Any]] | None = None,
    thread_ts: str | None = None,
) -> str:   # returns the message `ts`
```

- **Bot token + `chat.postMessage`, never an incoming webhook.** A webhook returns the
  literal string `ok` — no `ts` — which makes `thread_ts` replies structurally
  impossible. Required scopes: `chat:write` (+ `chat:write.public` for a channel the
  bot has not joined).
- **Check the body, not the status.** `{"ok": false}` at HTTP 200 is the normal Slack
  failure shape. `invalid_auth` / `channel_not_found` are permanent → do not retry.
- `logged_call("slack.post_message", ticket_id=...)` — **identifiers only. Never log
  `text`, `blocks`, or evidence** (NFR-016 extends NFR-006 to this field).

- [ ] **Step 3: `xoxb-` gitleaks rule + `/health.slack_configured`**

Add the rule to the existing `.gitleaks.toml`. Add `slack_configured` to the health
payload — but **not** to `missing_secrets`.

- [ ] **Step 4: Gate**

---

## Task 6: Delivery service

**Files:**
- Modify: `backend/app/services/bug_alerts.py`
- Test: `backend/tests/test_bug_alerts_deliver.py` (new)

- [ ] **Step 1: Write the failing tests (RED)**

- Undelivered `high` + `medium` → `high` posted first (severity-desc).
- Success → `slack_ts`, `slack_channel`, `posted_severity`, `posted_at` all set.
- **Slack raising → row still `posted_at IS NULL`**, retried next pass, nothing lost.
- `medium` delivered, then `high` detected → **threaded reply** (`thread_ts == slack_ts`),
  `posted_severity` becomes `high`, **no new top-level message**.
- Delivered `high`, then `medium` detected → **nothing posted.**
- Same severity re-detected → nothing posted.
- `dismissed_at` set → skipped.
- `bug_alert_max_per_cycle` respected.
- `low` row → never selected (below floor).

- [ ] **Step 2: `deliver_pending_bug_alerts`**

Select `posted_at IS NULL AND dismissed_at IS NULL AND severity >= floor`,
severity-desc then `first_detected_at` asc, `LIMIT bug_alert_max_per_cycle`. Also
select escalation rows: `posted_at IS NOT NULL AND dismissed_at IS NULL AND
severity > posted_severity`. Per row: build the message, post, then **store `ts`
before marking delivered** (a crash between them leaves the row in the outbox — a
duplicate post is the acceptable failure, an alert lost forever is not; the ordering
choice is deliberate). Per-row `try/except` so one bad channel does not stall the rest.

- [ ] **Step 3: Message body (Block Kit)**

Severity rank + emoji, ticket title, the customer quote in a fenced block, the
category, confidence, occurrence count, and a link to the Intercom conversation
(built from `intercom_workspace_app_id`, as `HydratedTicket.url` is). Escalation reply
is a short "⬆️ escalated medium → high" line, not the whole card again.

- [ ] **Step 4: Gate**

---

## Task 7: Background delivery loop

**Files:**
- Modify: `backend/app/main.py` (loops at `:49`-`:175`, task wiring at `:231`-`:255`)
- Test: extend `backend/tests/test_bug_alerts_deliver.py`

- [ ] **Step 1: `_bug_alert_delivery_loop`**

The fifth loop, cloning `_intercom_poll_loop` (`main.py:137`): interval-gated by
`bug_alert_poll_interval_seconds`, **default 0 = off**, broad `except Exception` →
log + continue (a loop that dies on one error is a silent outage), own session per
pass.

- [ ] **Step 2: Wire the task**

Start it only when `config.bug_alert_poll_interval_seconds > 0` **and** Slack is
configured, following the `intercom_poll_task` conditional at `:252`. Cancel + await
on shutdown like the others.

> **No Slack call inside `SYNC_LOCK`.** This loop must never be invoked from
> `run_sync_cycle` or `ingest_tickets`. A hanging Slack request would stall the whole
> sync cycle, and Slack's ~1 msg/sec/channel budget makes a burst inherently slow.

- [ ] **Step 3: Gate**

---

## Task 8: Read + dismiss router

**Files:**
- Create: `backend/app/routers/bug_alerts.py`
- Modify: `backend/app/routers/__init__.py`, `backend/app/main.py` (`include_router` block), `backend/app/schemas.py`
- Modify: `backend/tests/test_auth_required.py` (`:15` parametrize list)
- Test: `backend/tests/test_bug_alerts_api.py` (new)

- [ ] **Step 1: Write the failing tests (RED)**

`GET /bug-alerts` unauthenticated → **401**; authenticated → rows with evidence,
occurrences, delivery state; `?severity=high` and `?delivered=false` filter;
`POST /bug-alerts/{id}/dismiss` → `dismissed_at` set, subsequent delivery pass skips
it; dismiss on an unknown ticket → 404.

- [ ] **Step 2: Router + schema**

`GET /bug-alerts?severity=&delivered=` and `POST /bug-alerts/{ticket_id}/dismiss`.
Thin router → `services/bug_alerts.py`. `get_current_user` dependency (invariant #15).
`BugAlertSchema` on `schemas.py` — **not** on `HydratedTicket` (invariant #2 untouched;
alerts are alert-state, not conversation shape).

- [ ] **Step 3: Add `"/bug-alerts"` to the `test_auth_required.py` parametrize list**

That list is the enforcement mechanism for invariant #15. A new router that skips it
is a security regression that no other test catches.

- [ ] **Step 4: Register the router**

`routers/__init__.py` + the `include_router` block in `main.py`.

> **Serialize this.** The router registry is a known parallel-session conflict point
> (CLAUDE.md). Coordinate the insert.

- [ ] **Step 5: Gate**

---

## Task 9: Live validation (manual — not automatable)

The suite cannot prove any of this. Do it before Task 10.

- [ ] **Step 1: Detection quality against real traffic**

With `bug_alerts_enabled=True` and delivery off, run a real sync (needs
`INTERCOM_ACCESS_TOKEN`; note `intercom_poll_interval_seconds` defaults to 0 — press
Sync or enable the poller). Then read `GET /bug-alerts` and check by hand:
- Are the flagged tickets actually bug reports? (false-positive rate)
- Are obvious bugs being missed? (false-negative rate)
- Is `bug_evidence` a **real verbatim quote**, or paraphrase?
- Is the severity split sane, or is everything `medium`?

- [ ] **Step 2: Categorization drift check**

Compare categories/summaries on the same tickets before and after the prompt change.
**The canned-response AI tests cannot see this** — same blind spot as the T151
`json_schema` → 400 regression. If categorization degraded, the fifth facet is too
much for one call and detection needs its own (paid) call.

- [ ] **Step 3: Calibrate the floor**

Pick `bug_alert_min_confidence` from the observed distribution. Only now enable
delivery.

- [ ] **Step 4: Slack end-to-end**

Real token, real channel: one post lands; force a re-sync → **no duplicate**; raise a
severity → threaded reply under the original; revoke the token → rows stay in the
outbox and self-heal when it is restored.

---

## Task 10: Contract docs

**Files:** `docs/contract/spec.md`, `docs/contract/plan.md`, `docs/contract/tasks.md`

- [ ] **Step 1: Apply design doc §12 verbatim**

The exact fold-in text (spec v2.2 — US-044 / FR-075..079 / NFR-015-016 / §2 scope /
§7 decisions; plan v2.1 — §20; tasks v2.1 — Phase 22 T173–T178 + 8 traceability rows)
lives in
[`../specs/2026-08-13-slack-bug-alerts-design.md`](../specs/2026-08-13-slack-bug-alerts-design.md) §12.

- [ ] **Step 2: Row format**

FR/NFR rows are `| ID | text | US-xxx |`. Enum lists inside a row escape the pipe
inside backticks — `` (`low`\|`medium`\|`high`) `` — matching FR-043 / FR-062. Insert
FR-075 **after** FR-074, not before (an anchor-on-FR-074 Edit inserts above it).

- [ ] **Step 3: Verify ids**

No duplicates, sorted, no gaps; every new id present in the traceability matrix.

> Pre-existing and unrelated: the matrix has no rows for US-001..US-005 /
> US-007..US-014. It has always started at FR-001. Do not "fix" that here.

- [ ] **Step 4: Update `docs/PROJECT.md` + `docs/FEATURES.md`**

Data model gains `bug_alerts`; API surface gains the `/bug-alerts` group; FEATURES
gains a capability entry. `docs/README.md`'s table list needs `bug_alerts` too.

---

## Task 11: Cross-package gate + PR

- [ ] **Step 1: Backend gate, venv python**

```
ruff check app tests && ruff format --check app tests && mypy app && pytest -q
```

- [ ] **Step 2: Webapp gate — should be untouched**

No webapp change in v1. Run it anyway to prove that:
`npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`

- [ ] **Step 3: Migration check**

`alembic upgrade head` from a clean DB, then `alembic current` → `0027`. Confirm one
head (`alembic heads`).

- [ ] **Step 4: Open the PR**

Cross-package invariants to state as unchanged in the description: #2
(`HydratedTicket`), #4 (`parts[]` vs `internal_notes[]`), #6 (cache key), #7
(fallbacks never cached), #15 (auth on every route).

---

## Self-review notes

- **The dedup claim rests entirely on the PK.** If a future refactor makes
  `bug_alerts` keyed on anything else — a surrogate id, a `(ticket_id, severity)`
  pair — the dedup guarantee is gone and Slack will repost. The docstring says so;
  keep it there.
- **`posted_severity` looks redundant with `severity` and is not.** Collapsing them
  loses the ability to tell "detected high" from "told Slack high", which is exactly
  what escalation compares.
- **Ordering inside delivery is deliberate:** post → store `ts` → mark delivered. A
  crash mid-way risks one duplicate post; the reverse ordering risks losing an alert
  permanently. Duplicate is the cheaper failure.
- **Slice 1 shipping alone is the point,** not a fallback. Detection quality is
  unknown until real traffic runs through it (Task 9), and a miscalibrated floor that
  never reaches Slack costs nothing.

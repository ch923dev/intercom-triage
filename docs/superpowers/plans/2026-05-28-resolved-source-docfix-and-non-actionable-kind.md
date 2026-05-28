# resolved_source doc-sync + #6 cache guard + non_actionable_kind Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three real findings from the 2026-05-28 integration audit: (F-1) the source-of-truth docs lag the live `resolved_source` value set, (F-2) invariant #6 (content-signature cache key) is code-correct but untested, and (T107 / roadmap 4.2) ship the structured `non_actionable_kind` column for per-kind filtering + analytics.

**Architecture:** Two independently-shippable PRs, in order.
- **PR-1 (warm-up):** doc-only edits + one backend test. Zero runtime risk, no cross-package surface.
- **PR-2 (cross-package):** additive `non_actionable_kind` enum on the AI categorization contract, stored on `tickets` + `ai_cache`, surfaced on `TicketSchema`, displayed in webapp + extension popup. Ships in ONE PR per the cross-package rule.

**Tech Stack:** Python 3.11 / FastAPI / async SQLAlchemy 2.0 / Alembic / pydantic v2 / pytest (backend); Vue 3 / Pinia / TypeScript / Vitest (webapp); plain ES modules (extension).

---

## Open decisions for T107 (confirm or veto before executing PR-2)

These were chosen by the audit, not by you. Override any before execution.

- **D1 — Kind value set:** `auto_reply | thanks | spam | out_of_office | other` (+ `NULL` = not non-actionable / unkinded). Matches the backlog stub in `docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md:329`.
- **D2 — AI emits a structured field**, not a parse of the `resolution_reason` prefix. The prompt today only *leads the free-text reason* with a kind word (`backend/app/ai/prompt.py:107-108`); parsing that prefix is brittle. PR-2 adds a first-class `non_actionable_kind` field to the JSON contract.
- **D3 — Storage:** `tickets.non_actionable_kind` + `ai_cache.non_actionable_kind` (both nullable text, CHECK-enumerated). Set only when `resolved_source = 'non_actionable'`. **Manual** non-actionable marks store `NULL` (no AI signal); only the AI auto-apply path stamps a kind.
- **D4 — invariant #2 does NOT apply.** `non_actionable_kind` is AI-derived board state that rides `TicketSchema`, exactly like the triage facets (T142) — NOT `HydratedTicket`. The extension's `normalizeConversation` is untouched. (The roadmap's "cross-package per #2" note at `tasks.md:203` is imprecise; this plan corrects it.)
- **D5 — Scope of surfaces:** webapp gets a kind label on the non-actionable chip + a per-kind filter on the Non-actionable column. Extension popup gets a read-only kind label on its non-actionable chip. **Stats-dashboard per-kind breakdown is deferred** to a follow-up (keeps PR-2 bounded); noted in §Follow-ups.

---

## File structure

**PR-1 touches:**
- `CLAUDE.md` (invariant #10 wording) — *shared single-source doc; serialize.*
- `backend/CLAUDE.md` (data-model note, if it repeats the value set)
- `plan.md` (§5 schema block, line ~291) — *shared single-source doc; serialize.*
- `spec.md` (FR-026 wording) — *shared single-source doc; serialize.*
- `backend/tests/test_ingest_api.py` (one new test)

**PR-2 touches (one PR):**
- Create: `backend/alembic/versions/0020_add_non_actionable_kind.py` — *Alembic chain head; only one session adds a migration at a time. Current head = 0019.*
- Modify: `backend/app/models.py` (`Ticket` + `AICacheEntry` columns + CHECKs)
- Modify: `backend/app/ai/pipeline.py` (`CategorizationResult`, `parse_response`, resolver, `_fallback`)
- Modify: `backend/app/ai/prompt.py` (JSON contract + verdict section)
- Modify: `backend/app/services/cache.py` (`set_cached` / `get_cached`)
- Modify: `backend/app/services/tickets.py` (`_maybe_auto_resolve_from_ai`, `_upsert_ticket`)
- Modify: `backend/app/services/resolution.py` (clear kind on reopen; manual mark leaves NULL)
- Modify: `backend/app/schemas.py` (`TicketSchema` field + `NonActionableKind` literal) — *3-package contract spine; serialize.*
- Modify: `webapp/src/types/api.ts` (`NonActionableKind` + `Ticket.non_actionable_kind`)
- Modify: `webapp/src/components/ResolutionChip.vue` (kind label)
- Modify: `webapp/src/stores/tickets.ts` + a filter surface for the Non-actionable column
- Modify: `extension/popup.js` (chip kind label, read-only)
- Modify docs: `spec.md` (new FR), `plan.md` (§ note), `tasks.md` (mark T107 ✓ + matrix), `CLAUDE.md` (invariant #10 addendum)
- Tests: `backend/tests/test_ai.py`, `backend/tests/test_cache.py`, `backend/tests/test_resolution_ingest.py`, `backend/tests/test_resolution_api.py`, `webapp/src/components/ResolutionChip.spec.ts`

---

# PR-1 — Doc sync + #6 cache guard (warm-up)

## Task 1: Sync `resolved_source` value set across single-source docs (F-1)

The live code allows **four** `resolved_source` values (`backend/app/models.py:665`): `manual`, `intercom_closed`, `non_actionable`, `ai_resolved` (`ai_resolved` added by migration `0012_add_ai_resolved_source.py`). Three docs lag.

**Files:**
- Modify: `CLAUDE.md` (invariant #10)
- Modify: `plan.md` (§5 schema-additions block)
- Modify: `spec.md` (FR-026)
- Modify: `backend/CLAUDE.md` (only if it restates the value set)

- [ ] **Step 1: Fix CLAUDE.md invariant #10**

In `CLAUDE.md:55`, change the value set from three to four:

```
10. **`tickets.resolved_at` ⇔ `resolved_source`** (XOR CheckConstraint). `resolved_source ∈ {'manual', 'intercom_closed', 'non_actionable', 'ai_resolved'}` (`ai_resolved` = AI auto-close under the operator's auto-resolve toggle; migration 0012). Non-actionable renders as its own Kanban column (webapp) / its own popup tab (extension) — split from Resolved at the view layer (`tickets.nonActionableTickets` / `pureResolvedTickets` getters); storage stays unified. Reopen path clears both.
```

- [ ] **Step 2: Fix plan.md §5 schema block**

In `plan.md:291`, change:

```
  -- check: resolved_source IN ('manual','intercom_closed') or null
```

to:

```
  -- check: resolved_source IN ('manual','intercom_closed','non_actionable','ai_resolved') or null
  -- (widened by migrations 0010 non_actionable, 0012 ai_resolved)
```

- [ ] **Step 3: Fix spec.md FR-026**

In `spec.md:496`, replace the FR-026 row text:

```
| FR-026 | Resolution source is one of four stored values: `manual` (operator action), `intercom_closed` (sync auto-resolve), `non_actionable` (FR-037), or `ai_resolved` (AI auto-close confirmed under the operator's auto-resolve setting). | US-015, US-016, US-017 |
```

- [ ] **Step 4: Check backend/CLAUDE.md for a stale restatement**

Run: `grep -n "resolved_source\|intercom_closed" backend/CLAUDE.md`
If a line enumerates the value set with fewer than four values, widen it to match Step 1. If it only says "`resolved_at` ⇔ `resolved_source` (XOR CheckConstraint)" without listing values, leave it.

- [ ] **Step 5: Verify no other doc states a stale set**

Run: `grep -rn "resolved_source ∈\|resolved_source IN" *.md backend docs/architecture.md`
Expected: every *current* source-of-truth file lists four values. (Historical files under `docs/superpowers/plans/` and `docs/superpowers/specs/` are point-in-time records — do NOT edit them; they correctly reflect the state at their date.)

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md plan.md spec.md backend/CLAUDE.md
git commit -m "docs: sync resolved_source value set to four (add ai_resolved)"
```

## Task 2: Test that an internal note does not bust the content-signature cache (F-2)

Invariant #6: the AI cache key is the last customer-visible part timestamp (`backend/app/services/tickets.py:_content_signature`, line 72-88), NOT Intercom's `updated_at`. An internal teammate note advances `updated_at` but must not bust the cache. The code is correct; no test exercises this exact scenario today (`test_cache.py` tests the cache *layer*; `test_resolution_ingest.py` only covers it incidentally).

**Files:**
- Test: `backend/tests/test_ingest_api.py` (new test, mirrors `test_ingest_warm_cache_skips_recategorization` at line 87)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ingest_api.py`:

```python
@pytest.mark.asyncio
async def test_internal_note_does_not_bust_content_signature_cache(
    app: FastAPI,
    client: AsyncClient,
) -> None:
    """Invariant #6 — the AI cache key is the last customer-visible part
    timestamp, not Intercom's updated_at. An internal teammate note advances
    updated_at but must NOT bust the cache: the re-ingest is a cache hit and
    skips the AI call (categorized == 0)."""
    app.state.openrouter = FakeOpenRouter({"C9": existing_assignment(1)})

    now = datetime.now(UTC)
    part_ts = now.isoformat()
    author = {"id": "u1", "name": "Customer", "email": "c@example.com", "type": "user"}
    admin = {"id": "a1", "name": "Agent", "email": "a@example.com", "type": "admin"}

    payload = {
        "id": "C9",
        "title": "Need help",
        "state": "open",
        "priority": None,
        "created_at": part_ts,
        "updated_at": part_ts,
        "author": author,
        "url": "https://app.intercom.com/x/C9",
        "parts": [{"author": author, "body": "please help", "created_at": part_ts}],
    }

    first = await client.post("/tickets/ingest", json=[payload])
    assert first.json()["categorized"] == 1

    # Second sync: an internal teammate note arrives and Intercom bumps
    # updated_at — but the customer-visible parts are unchanged, so the content
    # signature is identical and the cache must still hit.
    later = (now + timedelta(hours=1)).isoformat()
    payload_with_note = {
        **payload,
        "updated_at": later,
        "internal_notes": [
            {"author": admin, "body": "FYI internal", "created_at": later, "is_admin": True},
        ],
    }

    again = await client.post("/tickets/ingest", json=[payload_with_note])
    assert again.json()["categorized"] == 0  # cache hit — internal note did not bust it
```

- [ ] **Step 2: Run it and confirm it PASSES immediately**

Run: `cd backend; pytest -q tests/test_ingest_api.py::test_internal_note_does_not_bust_content_signature_cache -v`
Expected: PASS. (This is a *characterization* test — the behavior already works; the test pins it so a future change to `_content_signature` that starts keying on `updated_at` or folds in `internal_notes` will fail loudly.)

> If it unexpectedly FAILS (`categorized == 1`), STOP — that means #6 is actually broken in code, which would be a much larger finding than the audit reported. Re-read `_content_signature` and report before changing anything.

- [ ] **Step 3: Run the full backend gate**

Run: `cd backend; ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_ingest_api.py
git commit -m "test: pin invariant #6 — internal note must not bust content-signature cache"
```

---

# PR-2 — `non_actionable_kind` structured column (T107 / roadmap 4.2)

> Confirm the **Open decisions** block above before starting. Ships as ONE PR across backend + webapp + extension. Serialize the shared files (Alembic head, `schemas.py`, single-source docs) — do not split across parallel sessions.

## Task 3: Alembic migration — add `non_actionable_kind` to `tickets` + `ai_cache`

**Files:**
- Create: `backend/alembic/versions/0020_add_non_actionable_kind.py`

- [ ] **Step 1: Confirm the current head is 0019**

Run: `cd backend; alembic heads`
Expected: a single head, revision `0019`. If not a single head, STOP — resolve the fork first.

- [ ] **Step 2: Write the migration**

Create `backend/alembic/versions/0020_add_non_actionable_kind.py`. Use `batch_alter_table` for SQLite (same pattern as 0010/0018):

```python
"""Add non_actionable_kind to tickets + ai_cache (roadmap 4.2 / T107).

Structured kind for non-actionable tickets: auto_reply / thanks / spam /
out_of_office / other. AI-derived; nullable; only set when the ticket is
non-actionable. Additive — pre-existing rows carry NULL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None

_KINDS = ("auto_reply", "thanks", "spam", "out_of_office", "other")
_KIND_LIST = ",".join(f"'{k}'" for k in _KINDS)


def upgrade() -> None:
    with op.batch_alter_table("tickets", recreate="auto") as batch:
        batch.add_column(sa.Column("non_actionable_kind", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "tickets_non_actionable_kind_check",
            f"non_actionable_kind IS NULL OR (resolved_source = 'non_actionable' "
            f"AND non_actionable_kind IN ({_KIND_LIST}))",
        )
    with op.batch_alter_table("ai_cache", recreate="auto") as batch:
        batch.add_column(sa.Column("non_actionable_kind", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ai_cache_non_actionable_kind_check",
            f"non_actionable_kind IS NULL OR non_actionable_kind IN ({_KIND_LIST})",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_cache", recreate="auto") as batch:
        batch.drop_constraint("ai_cache_non_actionable_kind_check", type_="check")
        batch.drop_column("non_actionable_kind")
    with op.batch_alter_table("tickets", recreate="auto") as batch:
        batch.drop_constraint("tickets_non_actionable_kind_check", type_="check")
        batch.drop_column("non_actionable_kind")
```

- [ ] **Step 3: Add the matching SQLAlchemy columns + CHECKs to `models.py`**

In `backend/app/models.py`, on the `Ticket` model add (near the other resolution columns):

```python
    non_actionable_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
```

and in `Ticket.__table_args__` (after the `tickets_not_parked_and_resolved_check` block, around line 690) add:

```python
        CheckConstraint(
            "non_actionable_kind IS NULL OR (resolved_source = 'non_actionable' "
            "AND non_actionable_kind "
            "IN ('auto_reply','thanks','spam','out_of_office','other'))",
            name="tickets_non_actionable_kind_check",
        ),
```

On the `AICacheEntry` model add:

```python
    non_actionable_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
```

and in its `__table_args__`:

```python
        CheckConstraint(
            "non_actionable_kind IS NULL OR non_actionable_kind "
            "IN ('auto_reply','thanks','spam','out_of_office','other')",
            name="ai_cache_non_actionable_kind_check",
        ),
```

- [ ] **Step 4: Verify migration round-trips on a fresh DB**

Run: `cd backend; alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: clean upgrade → downgrade → upgrade with no errors.

- [ ] **Step 5: Verify schema smoke (in-memory create_all matches the model)**

Run: `cd backend; python -m app.models`
Expected: prints seeded categories with no SQLAlchemy error (proves the new columns + CHECKs are valid).

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0020_add_non_actionable_kind.py backend/app/models.py
git commit -m "feat(db): add non_actionable_kind column to tickets + ai_cache (T107)"
```

## Task 4: AI contract — prompt emits `non_actionable_kind`, parser validates it

**Files:**
- Modify: `backend/app/ai/prompt.py`
- Modify: `backend/app/ai/pipeline.py` (`CategorizationResult`, `parse_response`, `_fallback`)
- Test: `backend/tests/test_ai.py`

- [ ] **Step 1: Write the failing parser tests**

Add to `backend/tests/test_ai.py` (match the existing `parse_response` test style in that file):

```python
def test_parse_response_reads_non_actionable_kind() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"out of office",'
        '"confidence":0.9,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.95,"resolution_reason":"auto-reply: OOO",'
        '"non_actionable_kind":"auto_reply"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind == "auto_reply"


def test_parse_response_defaults_kind_to_other_when_missing() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"thanks",'
        '"confidence":0.9,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.9,"resolution_reason":"thanks"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind == "other"


def test_parse_response_kind_null_when_verdict_not_non_actionable() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"needs reply",'
        '"confidence":0.9,"resolution_verdict":"not_resolved",'
        '"resolution_confidence":0.4,"resolution_reason":"awaiting fix",'
        '"non_actionable_kind":"spam"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind is None  # kind is meaningless unless non_actionable


def test_parse_response_invalid_kind_falls_back_to_other() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"weird",'
        '"confidence":0.9,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.9,"resolution_reason":"?",'
        '"non_actionable_kind":"banana"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind == "other"
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd backend; pytest -q tests/test_ai.py -k non_actionable_kind -v`
Expected: FAIL — `CategorizationResult` has no attribute `non_actionable_kind`.

- [ ] **Step 3: Add the field + a literal type to `CategorizationResult`**

In `backend/app/ai/pipeline.py`, near the other resolution literals (top of file) add:

```python
NonActionableKind = Literal["auto_reply", "thanks", "spam", "out_of_office", "other"]
_NON_ACTIONABLE_KINDS: tuple[str, ...] = ("auto_reply", "thanks", "spam", "out_of_office", "other")
```

Add the field to the `CategorizationResult` dataclass (alongside `ai_resolution_verdict`, ~line 50/72):

```python
    non_actionable_kind: NonActionableKind | None = None
```

- [ ] **Step 4: Parse + normalize the kind in `parse_response`**

In `parse_response`, after the `resolution_verdict` is parsed, add a helper mirroring the existing `_parse_verdict` (pipeline.py:126-133):

```python
def _parse_non_actionable_kind(
    verdict: str | None, raw_kind: object
) -> NonActionableKind | None:
    # Kind is only meaningful for the non_actionable verdict.
    if verdict != "non_actionable":
        return None
    if isinstance(raw_kind, str) and raw_kind in _NON_ACTIONABLE_KINDS:
        return raw_kind  # type: ignore[return-value]
    # Missing or out-of-set kind on a non_actionable verdict → 'other'
    # (graceful: never abort the whole ticket over a soft sub-classification).
    return "other"
```

Wire it where the result is constructed:

```python
        non_actionable_kind=_parse_non_actionable_kind(
            typed_verdict, data.get("non_actionable_kind")
        ),
```

(`typed_verdict` is the already-validated verdict from `_parse_verdict`; `data` is the parsed JSON dict.)

- [ ] **Step 5: Keep `_fallback` kind-null**

In `_fallback` (pipeline.py ~357), do NOT set `non_actionable_kind` (it defaults to `None`). A fallback verdict is `not_resolved` and is never cached anyway (#7). Confirm by reading the function — no change needed if the default holds.

- [ ] **Step 6: Update the prompt JSON contract**

In `backend/app/ai/prompt.py`, in the JSON contract block(s) (lines 43/58/75/113) add the field after `resolution_reason`:

```
     "non_actionable_kind":   "auto_reply" | "thanks" | "spam" | "out_of_office" | "other" | null,
```

And extend the verdict instructions (after line 108) with:

```
- When (and only when) resolution_verdict is "non_actionable", also return
  non_actionable_kind: one of "auto_reply", "thanks", "spam", "out_of_office",
  "other". Use "other" when none fit. For any other verdict, set it to null.
```

- [ ] **Step 7: Run the parser tests**

Run: `cd backend; pytest -q tests/test_ai.py -k non_actionable_kind -v`
Expected: all 4 PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/ai/pipeline.py backend/app/ai/prompt.py backend/tests/test_ai.py
git commit -m "feat(ai): emit + parse structured non_actionable_kind (T107)"
```

## Task 5: Cache read/write carries `non_actionable_kind`

**Files:**
- Modify: `backend/app/services/cache.py` (`set_cached`, `get_cached`)
- Test: `backend/tests/test_cache.py`

- [ ] **Step 1: Write the failing round-trip test**

Add to `backend/tests/test_cache.py`:

```python
@pytest.mark.asyncio
async def test_cache_round_trip_non_actionable_kind(session: AsyncSession) -> None:
    """Cache write + read preserves non_actionable_kind so a warm fetch reuses
    it without a second AI call (#6)."""
    sig = datetime(2026, 5, 28, 12, 0)
    result = CategorizationResult(
        category_id=1,
        proposal_id=None,
        summary="ooo",
        confidence=0.9,
        ai_resolution_verdict="non_actionable",
        ai_resolution_confidence=0.95,
        ai_resolution_reason="auto-reply: OOO",
        non_actionable_kind="auto_reply",
    )
    await set_cached(session, "t-na", result, sig)
    await session.commit()

    cached = await get_cached(session, "t-na", sig, ttl_seconds=300)
    assert cached is not None
    assert cached.non_actionable_kind == "auto_reply"
```

- [ ] **Step 2: Run to confirm failure**

Run: `cd backend; pytest -q tests/test_cache.py::test_cache_round_trip_non_actionable_kind -v`
Expected: FAIL — `set_cached` does not persist the column / `get_cached` returns a result without it.

- [ ] **Step 3: Persist the column in `set_cached`**

In `backend/app/services/cache.py`, in `set_cached`, write `non_actionable_kind=result.non_actionable_kind` onto the `AICacheEntry` (mirror how `ai_resolution_verdict` is written).

- [ ] **Step 4: Read the column in `get_cached`**

In `get_cached`, include `non_actionable_kind` in the `CategorizationResult` it reconstructs from the row (mirror `ai_resolution_verdict`). Legacy rows return `None` naturally.

- [ ] **Step 5: Run the test**

Run: `cd backend; pytest -q tests/test_cache.py::test_cache_round_trip_non_actionable_kind -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/cache.py backend/tests/test_cache.py
git commit -m "feat(cache): round-trip non_actionable_kind through ai_cache (T107)"
```

## Task 6: Ingest auto-apply stamps `non_actionable_kind`; reopen clears it

**Files:**
- Modify: `backend/app/services/tickets.py` (`_maybe_auto_resolve_from_ai`, `_upsert_ticket`)
- Modify: `backend/app/services/resolution.py` (reopen clears the column; manual mark leaves NULL)
- Test: `backend/tests/test_resolution_ingest.py`, `backend/tests/test_resolution_api.py`

- [ ] **Step 1: Write the failing ingest test**

Add to `backend/tests/test_resolution_ingest.py` (use the file's existing ingest harness / settings-enable pattern — enable `ai_resolve_default=true` and a low threshold so the verdict auto-applies):

```python
@pytest.mark.asyncio
async def test_ai_non_actionable_verdict_stamps_kind(app, client) -> None:
    """When AI auto-resolves a ticket as non_actionable, the structured kind is
    stamped on the ticket row and surfaced on GET /tickets."""
    # Enable AI auto-resolve at a low threshold.
    await client.put("/settings", json={
        "lookback_unit": "hours", "lookback_value": 24, "states": ["open"],
        "include_category_ids": None, "mute_alarms": False,
        "ai_resolve_default": True, "ai_resolve_confidence_threshold": 0.5,
    })
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"OOO bounce",'
        '"confidence":0.9,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.97,"resolution_reason":"auto-reply: OOO",'
        '"non_actionable_kind":"auto_reply"}'
    )
    app.state.openrouter = FakeOpenRouter({"NA1": raw})

    await client.post("/tickets/ingest", json=[_hydrated("NA1")])

    row = (await client.get("/tickets?resolved=true")).json()[0]
    assert row["resolved_source"] == "non_actionable"
    assert row["non_actionable_kind"] == "auto_reply"
```

(Reuse `_hydrated` / `FakeOpenRouter` / `existing_assignment` imports already present in the resolution-ingest test module; if `_hydrated` is not in that module, import it from `tests.test_ingest_api` or inline the payload.)

- [ ] **Step 2: Run to confirm failure**

Run: `cd backend; pytest -q tests/test_resolution_ingest.py::test_ai_non_actionable_verdict_stamps_kind -v`
Expected: FAIL — `non_actionable_kind` is `None` / missing on the response.

- [ ] **Step 3: Stamp the kind in `_maybe_auto_resolve_from_ai`**

In `backend/app/services/tickets.py:_maybe_auto_resolve_from_ai` (lines 154-193), after the existing `row.resolved_source = (...)` assignment (line 190-192), set the kind only on the non-actionable branch:

```python
    row.resolved_source = (
        "ai_resolved" if result.ai_resolution_verdict == "resolved" else "non_actionable"
    )
    row.non_actionable_kind = (
        result.non_actionable_kind
        if result.ai_resolution_verdict == "non_actionable"
        else None
    )
    clear_parked(row)
```

- [ ] **Step 4: Handle the new-row closed/AI branches in `_upsert_ticket`**

In `_upsert_ticket` (lines 218-275): the `intercom_closed` branches (new row line 241-243, update line 250-253) must NOT set a kind — `intercom_closed` is not `non_actionable`. Leave `non_actionable_kind` unset there (defaults to NULL). The `_maybe_auto_resolve_from_ai` call already handles the AI path for both new and existing rows. No extra code needed beyond Step 3; confirm by reading the branches.

- [ ] **Step 5: Clear the kind on reopen + manual-mark stays NULL**

In `backend/app/services/resolution.py`:
- In the reopen path (clears `resolved_at` + `resolved_source`), also set `row.non_actionable_kind = None` so the CHECK (`kind only when source = non_actionable`) holds.
- In `mark_non_actionable`, do NOT set a kind — manual marks have no AI signal (D3). The column stays NULL. (CHECK permits NULL with `resolved_source = 'non_actionable'`.)
- Also clear it in `set_override`'s drag-out reopen (`backend/app/services/tickets.py:113-116`): add `ticket.non_actionable_kind = None` alongside the `resolved_at`/`resolved_source` clear.

- [ ] **Step 6: Write the failing reopen test**

Add to `backend/tests/test_resolution_api.py`:

```python
@pytest.mark.asyncio
async def test_reopen_clears_non_actionable_kind(app, client) -> None:
    # Seed an AI-non-actionable ticket (reuse Task 6 Step 1 setup or a direct
    # row insert with resolved_source='non_actionable', non_actionable_kind='spam').
    ...  # arrange a non-actionable ticket with kind='spam'
    await client.post("/tickets/NA2/reopen")
    row = (await client.get("/tickets")).json()[0]
    assert row["resolved_source"] is None
    assert row["non_actionable_kind"] is None
```

- [ ] **Step 7: Run the resolution tests**

Run: `cd backend; pytest -q tests/test_resolution_ingest.py tests/test_resolution_api.py -k "non_actionable" -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/tickets.py backend/app/services/resolution.py backend/tests/test_resolution_ingest.py backend/tests/test_resolution_api.py
git commit -m "feat(ingest): stamp non_actionable_kind on AI auto-resolve; clear on reopen (T107)"
```

## Task 7: Surface `non_actionable_kind` on `TicketSchema`

**Files:**
- Modify: `backend/app/schemas.py` (`TicketSchema` + a `NonActionableKind` literal) — *contract spine; serialize.*
- Test: `backend/tests/test_ingest_api.py` (extend an existing GET assertion) — covered by Task 6 Step 1 already asserting the field on `GET /tickets`.

- [ ] **Step 1: Add the literal + field**

In `backend/app/schemas.py`, near the other resolution literals add:

```python
NonActionableKind = Literal["auto_reply", "thanks", "spam", "out_of_office", "other"]
```

On `TicketSchema` (the `GET /tickets` board row — NOT `HydratedTicket`) add:

```python
    non_actionable_kind: NonActionableKind | None = None
```

- [ ] **Step 2: Confirm the board composition fills it**

The board response is built from the `Ticket` ORM row (`from_attributes=True`). Since `Ticket.non_actionable_kind` now exists (Task 3), `TicketSchema.model_validate(row)` picks it up automatically. Verify there is no manual field-by-field construction in `GET /tickets` that would drop it — grep:

Run: `grep -n "TicketSchema(" backend/app/services/tickets.py backend/app/routers/tickets.py`
If the schema is built positionally/explicitly anywhere, add `non_actionable_kind=row.non_actionable_kind`. If it uses `model_validate` / `from_attributes`, no change.

- [ ] **Step 3: Run the gate**

Run: `cd backend; ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
Expected: all green (Task 6 Step 1's `GET /tickets` assertion now passes end-to-end).

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat(api): surface non_actionable_kind on TicketSchema (T107)"
```

## Task 8: Webapp — type, chip label, per-kind filter

**Files:**
- Modify: `webapp/src/types/api.ts`
- Modify: `webapp/src/components/ResolutionChip.vue`
- Modify: `webapp/src/stores/tickets.ts` (per-kind filter getter for the Non-actionable column)
- Test: `webapp/src/components/ResolutionChip.spec.ts`

- [ ] **Step 1: Add the type**

In `webapp/src/types/api.ts` add (near `ResolvedSource`, line ~20):

```ts
export type NonActionableKind = 'auto_reply' | 'thanks' | 'spam' | 'out_of_office' | 'other'
```

and on `interface Ticket`:

```ts
  non_actionable_kind: NonActionableKind | null
```

- [ ] **Step 2: Write the failing chip test**

In `webapp/src/components/ResolutionChip.spec.ts` add a case asserting that a non-actionable ticket with `non_actionable_kind: 'spam'` renders a kind-labelled chip (e.g. `Non-actionable · Spam`), and one with `null` renders the plain `Non-actionable` label. Follow the existing spec's mount + props pattern.

- [ ] **Step 3: Run to confirm failure**

Run: `cd webapp; npx vitest run src/components/ResolutionChip.spec.ts`
Expected: FAIL.

- [ ] **Step 4: Render the kind label**

In `webapp/src/components/ResolutionChip.vue`, when the chip is the non-actionable resolved variant, append a human label derived from `non_actionable_kind`:

```ts
const KIND_LABELS: Record<NonActionableKind, string> = {
  auto_reply: 'Auto-reply',
  thanks: 'Thanks',
  spam: 'Spam',
  out_of_office: 'Out of office',
  other: 'Other',
}
```

Show `Non-actionable · {{ KIND_LABELS[kind] }}` when `non_actionable_kind` is set, else `Non-actionable`. Keep the existing muted-gray token; do not add new tokens.

- [ ] **Step 5: Add a per-kind filter getter**

In `webapp/src/stores/tickets.ts`, add a getter that filters `nonActionableTickets` by an active kind (client-side, mirrors the existing view-layer split). Wire a small chip-row on the Non-actionable column header (reuse the existing filter-chip styling) so the operator can narrow by kind. Keep it presentation-only — no backend call.

- [ ] **Step 6: Run webapp gate**

Run: `cd webapp; npm run lint && npm run typecheck && npm test`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add webapp/src/types/api.ts webapp/src/components/ResolutionChip.vue webapp/src/stores/tickets.ts webapp/src/components/ResolutionChip.spec.ts
git commit -m "feat(webapp): non_actionable_kind chip label + per-kind filter (T107)"
```

## Task 9: Extension popup — read-only kind label

**Files:**
- Modify: `extension/popup.js`

- [ ] **Step 1: Render the kind on the non-actionable chip**

In `extension/popup.js`, where the resolved/non-actionable chip is rendered for a card, when `ticket.non_actionable_kind` is present append the same human label (`Auto-reply` / `Thanks` / `Spam` / `Out of office` / `Other`). The field already arrives on `GET /tickets`; no `intercom.js` / `normalizeConversation` change (invariant #2 untouched — D4). Match the existing `node(tag, className, text)` DOM pattern.

- [ ] **Step 2: Manual verify (no automated extension gate)**

Run the backend + webapp, then:
- `chrome://extensions` → reload unpacked.
- Sync a workspace that has an auto-reply / OOO ticket (or seed one), enable AI auto-resolve.
- Open popup → the non-actionable card chip reads e.g. `Non-actionable · Auto-reply`.
- Reopen it → chip reverts to open state, no kind.

- [ ] **Step 3: Commit**

```bash
git add extension/popup.js
git commit -m "feat(extension): show non_actionable_kind on popup chip (T107)"
```

## Task 10: Docs + traceability

**Files:**
- Modify: `spec.md` (new FR + US acceptance), `plan.md` (note), `tasks.md` (mark T107 ✓ + matrix), `CLAUDE.md` (invariant #10 addendum), `docs/ROADMAP.md` (ledger 4.2 → shipped)

- [ ] **Step 1: spec.md** — add an FR for the structured kind (e.g. FR-062) referencing US-019, and append a kind clause to US-019 acceptance: "A non-actionable ticket carries an optional structured kind (auto_reply / thanks / spam / out_of_office / other); the AI sets it on auto-apply, manual marks leave it null." Add the FR→task row to the traceability matrix.

- [ ] **Step 2: plan.md** — extend §8c (or the non-actionable note) with: `tickets.non_actionable_kind` + `ai_cache.non_actionable_kind`, AI-derived, nullable, set only when `resolved_source='non_actionable'`, migration 0020.

- [ ] **Step 3: tasks.md** — change `T107 — Structured non_actionable_kind column. (roadmap 4.2 — open, cross-package)` (line 203) to `T107 ✓ — ...` with the commit range, and add matrix rows. Correct the "cross-package per #2" framing — note #2 does NOT apply (rides TicketSchema, not HydratedTicket).

- [ ] **Step 4: CLAUDE.md** — add to invariant #10 (or a sibling note): non-actionable tickets may carry a structured `non_actionable_kind` on `tickets` + `ai_cache`; AI-derived, board-state only (not on `HydratedTicket`); cleared on reopen with the resolution pair.

- [ ] **Step 5: docs/ROADMAP.md** — flip the 4.2 ledger row (line 38) from `◯ open` to `✅ shipped` with the commit.

- [ ] **Step 6: Full cross-package gate (/qa-all equivalent)**

Run backend gate and webapp gate:
```bash
cd backend && ruff check app tests && ruff format --check app tests && mypy app && pytest -q
cd ../webapp && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```
Expected: all green. Extension verified manually in Task 9.

- [ ] **Step 7: Commit**

```bash
git add spec.md plan.md tasks.md CLAUDE.md docs/ROADMAP.md
git commit -m "docs: ship T107 — structured non_actionable_kind (roadmap 4.2)"
```

---

## Self-review notes

- **Spec coverage:** F-1 → Task 1; F-2 → Task 2; T107 (migration / AI / cache / ingest / schema / webapp / extension / docs) → Tasks 3–10. The non-actionable design doc's "out of scope: per-kind column" (line 314) is exactly what T107 now adds — consistent.
- **Type consistency:** the kind set `auto_reply | thanks | spam | out_of_office | other` is identical in the migration (`_KINDS`), `models.py` CHECKs, `pipeline.py:NonActionableKind`, `schemas.py:NonActionableKind`, `webapp/src/types/api.ts:NonActionableKind`. The CHECK couples `non_actionable_kind` to `resolved_source = 'non_actionable'` on `tickets`; `ai_cache` has no `resolved_source` so its CHECK only enumerates values.
- **Invariant guards held:** #2 untouched (no HydratedTicket change — D4); #6 untouched (kind rides the existing categorization result; cache key still the content signature); #7 untouched (`_fallback` leaves kind null and fallbacks aren't cached); #10/#11 extended cleanly (kind cleared on every reopen path, CHECK enforces coupling).
- **Shared-file serialization:** Alembic head 0019→0020 (one migration), `schemas.py` TicketSchema, and the single-source docs are all edited in PR-2 only; no parallel session should touch them concurrently. No router-registry change (no new endpoint — manual marks reuse the existing `/non-actionable` route).

## Follow-ups (out of scope, noted)

- Per-kind breakdown in the stats dashboard (`GET /stats` `resolution_mix` → split non-actionable by kind) — natural next step for the "spam-wave detection" analytics value; deferred to keep PR-2 bounded.
- Operator-chosen kind on the manual `/non-actionable` action (currently NULL by design D3) — only if a real need appears.

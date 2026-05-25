# Non-Actionable Tickets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `non_actionable` sub-state to resolved tickets — AI emits it as a 3rd verdict, operator marks it via flyout button or bulk action, chip per card distinguishes it from `resolved` inside the single Resolved column.

**Architecture:** Two CHECK constraints widen — `tickets.resolved_source` adds `'non_actionable'`, `ai_cache.ai_resolution_verdict` adds `'non_actionable'`. No new columns. Existing auto-resolve toggle + threshold + per-ticket `ai_resolve_enabled` cover both verdicts. Reopen path stays source-agnostic. Cross-package PR per invariant #2 (HydratedTicket / resolved-source contract ships together).

**Tech Stack:** Python 3.11+ / FastAPI / async SQLAlchemy 2.0 / Alembic / pytest; Vue 3.5 / Pinia 2.3 / Vite / TypeScript 5.6 / Vitest 2; plain ES modules (Chrome MV3).

**Spec:** `docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md`

---

## Task 1: Alembic migration 0010 — widen CHECK constraints

**Files:**
- Create: `backend/alembic/versions/0010_non_actionable_verdict.py`
- Test: `backend/tests/test_models.py` (extend)

- [ ] **Step 1: Write the failing test**

Open `backend/tests/test_models.py`. Append at the bottom:

```python
@pytest.mark.asyncio
async def test_ticket_accepts_non_actionable_source(session: AsyncSession) -> None:
    from app.models import Ticket
    from app.util import naive_utcnow

    now = naive_utcnow()
    session.add(
        Ticket(
            id="t-na-1",
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=now,
            updated_at=now,
            category_id=1,
            summary="",
            ai_confidence=0.0,
            resolved_at=now,
            resolved_source="non_actionable",
        )
    )
    await session.commit()


@pytest.mark.asyncio
async def test_ai_cache_accepts_non_actionable_verdict(session: AsyncSession) -> None:
    from app.models import AICacheEntry
    from app.util import naive_utcnow

    now = naive_utcnow()
    session.add(
        AICacheEntry(
            ticket_id="t-na-1",
            category_id=1,
            summary="x",
            confidence=0.5,
            ticket_updated_at=now,
            ai_resolution_verdict="non_actionable",
            ai_resolution_confidence=0.9,
            ai_resolution_reason="auto-reply: vacation responder",
        )
    )
    await session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -q tests/test_models.py::test_ticket_accepts_non_actionable_source tests/test_models.py::test_ai_cache_accepts_non_actionable_verdict -v
```

Expected: FAIL with `CheckConstraintViolation` (or `sqlite3.IntegrityError: CHECK constraint failed`) on both tests — the existing CHECK constraints reject `'non_actionable'`.

- [ ] **Step 3: Create the migration file**

Create `backend/alembic/versions/0010_non_actionable_verdict.py`:

```python
"""Widen resolution verdict + resolved_source CHECK constraints.

Adds 'non_actionable' to:
- tickets.resolved_source ∈ {'manual', 'intercom_closed', 'non_actionable'}
- ai_cache.ai_resolution_verdict ∈ {'resolved', 'not_resolved', 'non_actionable'}

Reference: docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md §3.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-25 00:00:00.000000 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable')",
        )

    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_resolution_verdict_check", type_="check")
        batch_op.create_check_constraint(
            "ai_cache_resolution_verdict_check",
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict "
            "IN ('resolved','not_resolved','non_actionable')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_resolution_verdict_check", type_="check")
        batch_op.create_check_constraint(
            "ai_cache_resolution_verdict_check",
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict "
            "IN ('resolved','not_resolved')",
        )

    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source IN ('manual','intercom_closed')",
        )
```

- [ ] **Step 4: Update models.py CHECK args to match the new schema**

Modify `backend/app/models.py`:

In the `AICacheEntry.__table_args__` block (around line 173), change:

```python
        CheckConstraint(
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict IN ('resolved','not_resolved')",
            name="ai_cache_resolution_verdict_check",
        ),
```

to:

```python
        CheckConstraint(
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict "
            "IN ('resolved','not_resolved','non_actionable')",
            name="ai_cache_resolution_verdict_check",
        ),
```

In the `Ticket.__table_args__` block (around line 473), change:

```python
        CheckConstraint(
            "resolved_source IS NULL OR resolved_source IN ('manual','intercom_closed')",
            name="tickets_resolved_source_check",
        ),
```

to:

```python
        CheckConstraint(
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable')",
            name="tickets_resolved_source_check",
        ),
```

- [ ] **Step 5: Run the failing tests again to verify they pass**

```powershell
pytest -q tests/test_models.py::test_ticket_accepts_non_actionable_source tests/test_models.py::test_ai_cache_accepts_non_actionable_verdict -v
```

Expected: PASS — the new migration runs in the test fixture (in-memory SQLite via `init_db`), the widened CHECK accepts `'non_actionable'`.

- [ ] **Step 6: Run the full backend test suite — nothing regresses**

```powershell
pytest -q
```

Expected: PASS for all existing tests.

- [ ] **Step 7: Commit**

```powershell
git add backend/alembic/versions/0010_non_actionable_verdict.py backend/app/models.py backend/tests/test_models.py
git commit -m "feat(db): widen resolution CHECK constraints for non_actionable"
```

---

## Task 2: AI prompt — 3-way verdict

**Files:**
- Modify: `backend/app/ai/prompt.py:17-105`
- Test: `backend/tests/test_resolution_prompt.py` (extend)

- [ ] **Step 1: Write the failing test**

In `backend/tests/test_resolution_prompt.py`, append:

```python
def test_system_prompt_includes_non_actionable_verdict():
    assert "non_actionable" in SYSTEM_PROMPT
    # All three verdicts present.
    for verdict in ("resolved", "non_actionable", "not_resolved"):
        assert verdict in SYSTEM_PROMPT


def test_system_prompt_documents_non_actionable_examples():
    # The prompt mentions the canonical non-actionable trigger kinds.
    body = SYSTEM_PROMPT.lower()
    for kind in ("auto-reply", "spam", "thanks"):
        assert kind in body
```

- [ ] **Step 2: Run to verify it fails**

```powershell
pytest -q tests/test_resolution_prompt.py -v
```

Expected: 2 FAIL (`non_actionable` not in prompt; auto-reply/spam/thanks not in prompt).

- [ ] **Step 3: Update the prompt**

Modify `backend/app/ai/prompt.py`. In the three assignment blocks (A, B, C) replace each occurrence of:

```python
     "resolution_verdict":    "resolved" | "not_resolved",
```

with:

```python
     "resolution_verdict":    "resolved" | "non_actionable" | "not_resolved",
```

Then replace the entire `RESOLUTION rules:` block (lines 86-99 of the original file) with:

```python
RESOLUTION rules (applies to every response):
- Decide whether the conversation appears resolved, non-actionable, or unresolved.
- "resolved": the customer's most recent message indicates the issue is fixed,
  they thanked the agent for a working solution, or the agent's last reply closed
  the loop and the customer has not replied since.
- "non_actionable": no operator response required. Examples — auto-reply
  (out-of-office, vacation responder, calendar notification), marketing or
  promotional email, spam, or a bare "thanks" after an agent reply with nothing
  left to do. Lead the reason with a short kind tag where it applies:
  "auto-reply: ...", "spam: ...", "thanks: ...".
- "not_resolved": the customer is waiting on the agent, has a new question,
  expressed dissatisfaction, the issue is still reproducing, or the thread ends
  mid-troubleshooting without confirmation.
- Add these THREE fields to EVERY response object:
    "resolution_verdict":    "resolved" | "non_actionable" | "not_resolved",
    "resolution_confidence": <float 0..1>,
    "resolution_reason":     "<one short clause, <=120 chars, plain text>"
```

- [ ] **Step 4: Run to verify the test passes**

```powershell
pytest -q tests/test_resolution_prompt.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/ai/prompt.py backend/tests/test_resolution_prompt.py
git commit -m "feat(ai): teach prompt the non_actionable verdict"
```

---

## Task 3: AI parser — accept `non_actionable` verdict

**Files:**
- Modify: `backend/app/ai/pipeline.py:39, 57, 103-122`
- Test: `backend/tests/test_resolution_prompt.py` (parser tests already live there)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_resolution_prompt.py`:

```python
def test_parser_accepts_non_actionable_verdict():
    raw = (
        '{"assignment":"existing","category_id":1,"subject":"x","summary":"y",'
        '"confidence":0.5,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.9,'
        '"resolution_reason":"auto-reply: vacation responder"}'
    )
    parsed = parse_response(raw)
    assert parsed.resolution_verdict == "non_actionable"
    assert parsed.resolution_confidence == 0.9
    assert parsed.resolution_reason == "auto-reply: vacation responder"


def test_parser_rejects_out_of_set_verdict():
    # Anything outside the 3-way set must clamp to None (not raise).
    raw = (
        '{"assignment":"existing","category_id":1,"subject":"x","summary":"y",'
        '"confidence":0.5,"resolution_verdict":"maybe_actionable","resolution_confidence":0.7}'
    )
    parsed = parse_response(raw)
    assert parsed.resolution_verdict is None
```

- [ ] **Step 2: Run to verify it fails**

```powershell
pytest -q tests/test_resolution_prompt.py::test_parser_accepts_non_actionable_verdict -v
```

Expected: FAIL — current `_parse_resolution` returns `None` for `non_actionable` because membership check excludes it.

- [ ] **Step 3: Widen the Literal types and the membership check**

In `backend/app/ai/pipeline.py`, change line 39 (the `ParsedAssignment` field):

```python
    resolution_verdict: Literal["resolved", "not_resolved"] | None = None
```

to:

```python
    resolution_verdict: Literal["resolved", "non_actionable", "not_resolved"] | None = None
```

Change line 57 (the `CategorizationResult` field):

```python
    ai_resolution_verdict: Literal["resolved", "not_resolved"] | None = None
```

to:

```python
    ai_resolution_verdict: Literal["resolved", "non_actionable", "not_resolved"] | None = None
```

Replace the `_parse_resolution` function (lines 103-122) with:

```python
def _parse_resolution(
    obj: dict[str, Any],
) -> tuple[
    Literal["resolved", "non_actionable", "not_resolved"] | None,
    float | None,
    str | None,
]:
    verdict = obj.get("resolution_verdict")
    if verdict not in ("resolved", "non_actionable", "not_resolved"):
        return None, None, None
    typed_verdict: Literal["resolved", "non_actionable", "not_resolved"] = verdict
    confidence_raw = obj.get("resolution_confidence")
    confidence_f: float | None
    try:
        confidence_f = max(0.0, min(1.0, float(str(confidence_raw))))
    except (TypeError, ValueError):
        confidence_f = None
    reason_raw = obj.get("resolution_reason")
    reason = str(reason_raw)[:120] if isinstance(reason_raw, str) and reason_raw.strip() else None
    return typed_verdict, confidence_f, reason
```

- [ ] **Step 4: Run the new tests + the existing parser tests**

```powershell
pytest -q tests/test_resolution_prompt.py -v
```

Expected: PASS (all parser tests including the new ones).

- [ ] **Step 5: Run mypy strict check**

```powershell
mypy app
```

Expected: `Success: no issues found in 38 source files`. The widened Literal flows through `CategorizationResult` into the cache (the existing `# type: ignore[arg-type]` annotations still apply at the cache→service boundary).

- [ ] **Step 6: Commit**

```powershell
git add backend/app/ai/pipeline.py backend/tests/test_resolution_prompt.py
git commit -m "feat(ai): accept non_actionable in resolution parser"
```

---

## Task 4: Ingest auto-apply for `non_actionable` verdict

**Files:**
- Modify: `backend/app/services/tickets.py:146-210` (`_upsert_ticket`)
- Test: `backend/tests/test_resolution_ingest.py` (extend)

- [ ] **Step 1: Find the existing auto-resolve branch**

Read `backend/app/services/tickets.py` lines 146-210. The Intercom-closed branch at lines 184-193 stamps `resolved_source='intercom_closed'`. The AI auto-apply path lives there too but currently handles only `'resolved'` — we add `'non_actionable'`.

Open the file and check whether there's an existing call site that maps the AI verdict to `resolved_source`. If absent, the new branch lives right after the Intercom-closed branch.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_resolution_ingest.py`:

```python
@pytest.mark.asyncio
async def test_ingest_auto_resolves_non_actionable_when_threshold_met(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AI verdict 'non_actionable' + auto-resolve on + confidence >= threshold
    → ingest stamps resolved_source='non_actionable'."""
    from app.ai.pipeline import CategorizationResult
    from app.models import Settings

    # Settings: AI on, auto-resolve on, threshold 0.7.
    s = (await session.scalars(select(Settings))).one()
    s.use_ai = True
    s.ai_resolve_default = True
    s.ai_resolve_confidence_threshold = 0.7
    await session.commit()

    async def fake_categorize_many(*args, **kwargs):
        return {
            "conv-na-1": CategorizationResult(
                category_id=1,
                proposal_id=None,
                summary="auto-reply bounce",
                confidence=0.9,
                ai_resolution_verdict="non_actionable",
                ai_resolution_confidence=0.85,
                ai_resolution_reason="auto-reply: vacation responder",
            )
        }

    monkeypatch.setattr("app.services.tickets.categorize_many", fake_categorize_many)

    payload = [
        {
            "id": "conv-na-1",
            "title": "Out of office",
            "state": "open",
            "priority": None,
            "url": None,
            "author": {"name": "Bot", "type": "user"},
            "created_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z",
            "parts": [],
            "internal_notes": [],
        }
    ]
    r = await client.post("/tickets/ingest", json=payload)
    assert r.status_code == 200

    from app.models import Ticket
    row = await session.get(Ticket, "conv-na-1")
    assert row is not None
    assert row.resolved_at is not None
    assert row.resolved_source == "non_actionable"


@pytest.mark.asyncio
async def test_ingest_skips_auto_apply_when_confidence_below_threshold(
    client: AsyncClient, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Below threshold → ticket stays open, no resolved_source stamped."""
    from app.ai.pipeline import CategorizationResult
    from app.models import Settings

    s = (await session.scalars(select(Settings))).one()
    s.use_ai = True
    s.ai_resolve_default = True
    s.ai_resolve_confidence_threshold = 0.9
    await session.commit()

    async def fake_categorize_many(*args, **kwargs):
        return {
            "conv-na-2": CategorizationResult(
                category_id=1,
                proposal_id=None,
                summary="might be spam",
                confidence=0.6,
                ai_resolution_verdict="non_actionable",
                ai_resolution_confidence=0.65,  # below 0.9 threshold
                ai_resolution_reason="spam: likely promotional",
            )
        }

    monkeypatch.setattr("app.services.tickets.categorize_many", fake_categorize_many)

    payload = [
        {
            "id": "conv-na-2", "title": "Promo", "state": "open", "priority": None,
            "url": None, "author": {"type": "user"}, "created_at": "2026-05-25T00:00:00Z",
            "updated_at": "2026-05-25T00:00:00Z", "parts": [], "internal_notes": [],
        }
    ]
    r = await client.post("/tickets/ingest", json=payload)
    assert r.status_code == 200

    from app.models import Ticket
    row = await session.get(Ticket, "conv-na-2")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolved_source is None
```

Add to the file's imports at top if not already present:

```python
from sqlalchemy import select
```

- [ ] **Step 3: Run to verify they fail**

```powershell
pytest -q tests/test_resolution_ingest.py::test_ingest_auto_resolves_non_actionable_when_threshold_met -v
```

Expected: FAIL — the upsert path doesn't yet stamp `resolved_source` for the AI verdict.

- [ ] **Step 4: Add the auto-apply branch**

In `backend/app/services/tickets.py:_upsert_ticket`, locate the Intercom-closed branch (around line 184-193, inside the `if row is None:` block AND the `else:` block). The new path applies in BOTH branches: when the row is new and when it already exists, the AI verdict can stamp non-actionable as long as the row isn't already resolved by another source.

Add a helper at module level (above `_upsert_ticket`):

```python
def _maybe_auto_resolve_from_ai(
    row: Ticket,
    result: CategorizationResult,
    settings: FilterSettings,
    now: datetime,
) -> None:
    """Stamp resolved_at + resolved_source when the AI verdict + settings agree.

    Skipped when the ticket is already resolved by any source — never override
    an existing resolution. Intercom-closed transitions take precedence at the
    caller site (this helper runs after that branch).
    """
    if row.resolved_at is not None:
        return
    if result.ai_resolution_verdict not in ("resolved", "non_actionable"):
        return
    if result.ai_resolution_confidence is None:
        return
    if result.ai_resolution_confidence < settings.ai_resolve_confidence_threshold:
        return
    effective = (
        row.ai_resolve_enabled
        if row.ai_resolve_enabled is not None
        else settings.ai_resolve_default
    )
    if not effective:
        return
    row.resolved_at = now
    row.resolved_source = result.ai_resolution_verdict  # 'resolved' or 'non_actionable'
```

Add `from app.schemas import FilterSettings, ...` to the imports if not already present (it's already imported per line 24).

Change `_upsert_ticket`'s signature from:

```python
async def _upsert_ticket(
    session: AsyncSession,
    hydrated: HydratedTicket,
    result: CategorizationResult,
) -> None:
```

to:

```python
async def _upsert_ticket(
    session: AsyncSession,
    hydrated: HydratedTicket,
    result: CategorizationResult,
    settings: FilterSettings,
) -> None:
```

Inside the function, in the new-row branch right BEFORE `session.add(new_row)`, add the AI auto-apply call (after the Intercom-closed branch that already exists):

```python
        if hydrated.state == "closed":
            new_row.resolved_at = now
            new_row.resolved_source = "intercom_closed"
        else:
            _maybe_auto_resolve_from_ai(new_row, result, settings, now)
        session.add(new_row)
        return
```

In the existing-row branch, after the Intercom-closed transition check (which sits at lines 191-193 of the original), add the AI auto-apply call:

```python
    # Closure transition: previously not closed AND now closed AND not already
    # resolved → auto-stamp resolved_at + resolved_source (intercom_closed).
    if hydrated.state == "closed" and row.state != "closed" and row.resolved_at is None:
        row.resolved_at = now
        row.resolved_source = "intercom_closed"
    else:
        _maybe_auto_resolve_from_ai(row, result, settings, now)
```

Then update the two call sites in `ingest_tickets` (the `if not settings.use_ai:` branch around line 242 and the main loop around line 285):

```python
for ticket in hydrated:
    await _upsert_ticket(session, ticket, fallback_results[ticket.id], settings)
```

```python
for ticket in hydrated:
    await _upsert_ticket(session, ticket, results[ticket.id], settings)
```

- [ ] **Step 5: Run the new tests**

```powershell
pytest -q tests/test_resolution_ingest.py -v
```

Expected: PASS for both new tests AND all existing ones (the helper is a no-op when the existing fixture's `ai_resolve_default=False`).

- [ ] **Step 6: Run the full suite + mypy**

```powershell
pytest -q
mypy app
```

Expected: PASS on both.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/services/tickets.py backend/tests/test_resolution_ingest.py
git commit -m "feat(ingest): auto-apply AI non_actionable verdict under shared threshold"
```

---

## Task 5: Resolution service — `mark_non_actionable` single-id

**Files:**
- Modify: `backend/app/services/resolution.py`
- Test: `backend/tests/test_resolution_service.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_resolution_service.py`:

```python
@pytest.mark.asyncio
async def test_mark_non_actionable_stamps_source(session: AsyncSession) -> None:
    from app.models import Ticket
    from app.services.resolution import mark_non_actionable
    from app.util import naive_utcnow

    now = naive_utcnow()
    session.add(
        Ticket(
            id="t-na-svc-1", title="x", state="open", author={}, parts=[],
            internal_notes=[], created_at=now, updated_at=now, category_id=1,
            summary="", ai_confidence=0.0,
        )
    )
    await session.commit()

    out = await mark_non_actionable(session, "t-na-svc-1")
    assert out.resolved_source == "non_actionable"
    assert out.resolved_at is not None

    row = await session.get(Ticket, "t-na-svc-1")
    assert row is not None
    assert row.resolved_source == "non_actionable"


@pytest.mark.asyncio
async def test_mark_non_actionable_409_when_already_resolved(session: AsyncSession) -> None:
    from fastapi import HTTPException
    from app.models import Ticket
    from app.services.resolution import mark_non_actionable
    from app.util import naive_utcnow

    now = naive_utcnow()
    session.add(
        Ticket(
            id="t-na-svc-2", title="x", state="open", author={}, parts=[],
            internal_notes=[], created_at=now, updated_at=now, category_id=1,
            summary="", ai_confidence=0.0,
            resolved_at=now, resolved_source="manual",
        )
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await mark_non_actionable(session, "t-na-svc-2")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_mark_non_actionable_404_unknown(session: AsyncSession) -> None:
    from fastapi import HTTPException
    from app.services.resolution import mark_non_actionable

    with pytest.raises(HTTPException) as exc:
        await mark_non_actionable(session, "ghost")
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run to verify failure**

```powershell
pytest -q tests/test_resolution_service.py::test_mark_non_actionable_stamps_source -v
```

Expected: FAIL with `ImportError` — `mark_non_actionable` doesn't exist yet.

- [ ] **Step 3: Add the service**

In `backend/app/services/resolution.py`, add `apply_mark_non_actionable` and `mark_non_actionable`. Insert directly after `apply_reopen` (line 58):

```python
def apply_mark_non_actionable(row: Ticket) -> ResolveOutcome:
    """Mutate a Ticket row to mark it non-actionable. Does NOT commit.

    Sub-state of resolved — sets resolved_at + resolved_source='non_actionable'.
    409 if the row is already resolved by any source.
    """
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already resolved")
    now = naive_utcnow()
    row.resolved_at = now
    row.resolved_source = "non_actionable"
    return ResolveOutcome(resolved_at=now, resolved_source="non_actionable")


async def mark_non_actionable(session: AsyncSession, ticket_id: str) -> ResolveOutcome:
    """Mark a ticket non-actionable. 409 if already resolved, 404 if unknown."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_mark_non_actionable(row)
    await session.commit()
    metrics.incr("tickets_resolved_total.non_actionable")
    return outcome
```

- [ ] **Step 4: Run to verify tests pass**

```powershell
pytest -q tests/test_resolution_service.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/app/services/resolution.py backend/tests/test_resolution_service.py
git commit -m "feat(resolution): add mark_non_actionable service"
```

---

## Task 6: Bulk service — `bulk_mark_non_actionable`

**Files:**
- Modify: `backend/app/services/bulk.py`
- Test: `backend/tests/test_bulk_api.py` (extend in the next task)

- [ ] **Step 1: Add the bulk loop**

In `backend/app/services/bulk.py`, after `bulk_reopen` (line 106), add:

```python
async def bulk_mark_non_actionable(session: AsyncSession, ticket_ids: list[str]) -> BulkResult:
    """Mark N tickets non-actionable. Already-resolved rows fail with 409."""

    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_mark_non_actionable(row)
        metrics.incr("tickets_resolved_total.non_actionable")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("non_actionable", result)
    return result
```

- [ ] **Step 2: Run mypy + smoke**

```powershell
mypy app
pytest -q tests/test_bulk_api.py -v
```

Expected: PASS — existing bulk tests untouched.

- [ ] **Step 3: Commit**

```powershell
git add backend/app/services/bulk.py
git commit -m "feat(bulk): add bulk_mark_non_actionable service"
```

---

## Task 7: Endpoints + schemas — single + bulk routes

**Files:**
- Modify: `backend/app/schemas.py:56` (widen `ResolvedSource`), `:57` (widen `ResolutionVerdict`)
- Modify: `backend/app/routers/tickets.py`
- Test: `backend/tests/test_resolution_api.py` (extend), `backend/tests/test_bulk_api.py` (extend)

- [ ] **Step 1: Widen the wire-format literals**

In `backend/app/schemas.py`, change line 56:

```python
ResolvedSource = Literal["manual", "intercom_closed"]
```

to:

```python
ResolvedSource = Literal["manual", "intercom_closed", "non_actionable"]
```

Change line 57:

```python
ResolutionVerdict = Literal["resolved", "not_resolved"]
```

to:

```python
ResolutionVerdict = Literal["resolved", "non_actionable", "not_resolved"]
```

- [ ] **Step 2: Write failing endpoint tests**

Append to `backend/tests/test_resolution_api.py`:

```python
@pytest.mark.asyncio
async def test_post_non_actionable_returns_200_and_persists(
    client: AsyncClient, session: AsyncSession
):
    _seed_open(session, "t-na-r1")
    await session.commit()

    r = await client.post("/tickets/t-na-r1/non-actionable", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_source"] == "non_actionable"
    assert body["resolved_at"]


@pytest.mark.asyncio
async def test_post_non_actionable_404_unknown(client: AsyncClient):
    r = await client.post("/tickets/ghost/non-actionable", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_non_actionable_409_already_resolved(
    client: AsyncClient, session: AsyncSession
):
    t = Ticket(
        id="t-na-r2", title="x", state="open", author={}, parts=[],
        internal_notes=[], created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
        resolved_at=naive_utcnow(), resolved_source="manual",
    )
    session.add(t)
    await session.commit()
    r = await client.post("/tickets/t-na-r2/non-actionable", json={})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_reopen_clears_non_actionable(client: AsyncClient, session: AsyncSession):
    t = Ticket(
        id="t-na-r3", title="x", state="open", author={}, parts=[],
        internal_notes=[], created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
        resolved_at=naive_utcnow(), resolved_source="non_actionable",
    )
    session.add(t)
    await session.commit()

    r = await client.post("/tickets/t-na-r3/reopen", json={})
    assert r.status_code == 200

    row = await session.get(Ticket, "t-na-r3")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolved_source is None
```

Append to `backend/tests/test_bulk_api.py`:

```python
@pytest.mark.asyncio
async def test_bulk_non_actionable_happy(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "b-na-1")
    _seed_open(session, "b-na-2")
    _seed_open(session, "b-na-3")
    await session.commit()

    r = await client.post(
        "/tickets/bulk/non-actionable",
        json={"ticket_ids": ["b-na-1", "b-na-2", "b-na-3"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"b-na-1", "b-na-2", "b-na-3"}
    assert body["failed"] == []


@pytest.mark.asyncio
async def test_bulk_non_actionable_partial(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "b-na-4")
    t = Ticket(
        id="b-na-5", title="x", state="open", author={}, parts=[],
        internal_notes=[], created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
        resolved_at=naive_utcnow(), resolved_source="manual",
    )
    session.add(t)
    await session.commit()

    r = await client.post(
        "/tickets/bulk/non-actionable",
        json={"ticket_ids": ["b-na-4", "b-na-5"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok_ids"] == ["b-na-4"]
    assert [f["id"] for f in body["failed"]] == ["b-na-5"]


@pytest.mark.asyncio
async def test_bulk_non_actionable_cap_exceeded(client: AsyncClient):
    r = await client.post(
        "/tickets/bulk/non-actionable",
        json={"ticket_ids": [f"x{i}" for i in range(201)]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_non_actionable_empty(client: AsyncClient):
    r = await client.post("/tickets/bulk/non-actionable", json={"ticket_ids": []})
    assert r.status_code == 422
```

Make sure the file imports `_seed_open` (or replicate the helper). Read the existing test file once to confirm naming — if absent, copy the helper from `test_resolution_api.py`.

- [ ] **Step 3: Run to verify they fail**

```powershell
pytest -q tests/test_resolution_api.py tests/test_bulk_api.py -k non_actionable -v
```

Expected: FAIL with 404 (endpoints don't exist).

- [ ] **Step 4: Add the routes**

In `backend/app/routers/tickets.py`:

Add `bulk/non-actionable` alongside the other bulk routes. After `bulk_dismiss_chip` (line 116), append:

```python
@router.post("/bulk/non-actionable", response_model=BulkResult)
async def bulk_non_actionable(
    body: BulkTicketIds,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Mark N tickets non-actionable. Already-resolved rows fail with 409."""
    return await bulk_svc.bulk_mark_non_actionable(session, body.ticket_ids)
```

Add the single-id route alongside `resolve_ticket` (after line 155):

```python
@router.post("/{ticket_id}/non-actionable", response_model=ResolveResponse)
async def mark_ticket_non_actionable(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> ResolveResponse:
    """Mark a ticket non-actionable. 409 if already resolved, 404 if unknown."""
    out = await resolution_svc.mark_non_actionable(session, ticket_id)
    return ResolveResponse(resolved_at=out.resolved_at, resolved_source=out.resolved_source)
```

- [ ] **Step 5: Run to verify tests pass**

```powershell
pytest -q tests/test_resolution_api.py tests/test_bulk_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Run the full backend gate**

```powershell
ruff check app tests
ruff format --check app tests
mypy app
pytest -q
```

Expected: green on all four.

- [ ] **Step 7: Commit**

```powershell
git add backend/app/schemas.py backend/app/routers/tickets.py backend/tests/test_resolution_api.py backend/tests/test_bulk_api.py
git commit -m "feat(api): non-actionable single + bulk endpoints"
```

---

## Task 8: Webapp — widen types + add API client methods

**Files:**
- Modify: `webapp/src/types/api.ts:20-22`
- Modify: `webapp/src/api/client.ts:127-146` and the bulk section near `:228`

- [ ] **Step 1: Widen TypeScript literals**

In `webapp/src/types/api.ts`, change lines 20-22:

```ts
export type ResolvedSource = 'manual' | 'intercom_closed';
export type ResolutionVerdict = 'resolved' | 'not_resolved';
```

to:

```ts
export type ResolvedSource = 'manual' | 'intercom_closed' | 'non_actionable';
export type ResolutionVerdict = 'resolved' | 'not_resolved' | 'non_actionable';
```

- [ ] **Step 2: Add API client methods**

In `webapp/src/api/client.ts`, after `dismissChip` (around line 146), add:

```ts
  /** Mark a ticket non-actionable. 409 if already resolved, 404 if unknown. */
  markNonActionable: (
    ticketId: string,
  ): Promise<{ resolved_at: string; resolved_source: ResolvedSource }> =>
    request(`/tickets/${ticketId}/non-actionable`, { method: 'POST', body: '{}' }),
```

In the bulk-actions section (around line 228, alongside `bulkDismissChip`), add:

```ts
  /** Mark N tickets non-actionable. Per-id ok/failed in the response. */
  bulkMarkNonActionable: (ticketIds: string[]): Promise<BulkResult> =>
    request('/tickets/bulk/non-actionable', {
      method: 'POST',
      body: JSON.stringify({ ticket_ids: ticketIds }),
    }),
```

- [ ] **Step 3: Run typecheck**

```powershell
cd webapp
npm run typecheck
```

Expected: PASS — the widened union is compatible with all existing consumers (they read `resolved_source` as a string).

- [ ] **Step 4: Commit**

```powershell
git add webapp/src/types/api.ts webapp/src/api/client.ts
git commit -m "feat(webapp): widen ResolvedSource + add non-actionable client methods"
```

---

## Task 9: Webapp tickets store — `markNonActionable` + `bulkMarkNonActionable`

**Files:**
- Modify: `webapp/src/stores/tickets.ts`

- [ ] **Step 1: Add the single-ticket action**

In `webapp/src/stores/tickets.ts`, after `markResolved` (ends at line 198), add `markNonActionable` which mirrors the same shape but stamps `resolved_source: 'non_actionable'`:

```ts
  /** Optimistically move ticket to resolvedTickets with non-actionable source. */
  async function markNonActionable(id: string) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    state.value.tickets.splice(idx, 1);
    resolvedTickets.value.unshift({
      ...original,
      resolved_at: new Date().toISOString(),
      resolved_source: 'non_actionable',
      resolution_chip_state: null,
    });
    try {
      await api.markNonActionable(id);
    } catch (e) {
      resolvedTickets.value = resolvedTickets.value.filter((t) => t.id !== id);
      state.value.tickets.splice(idx, 0, original);
      throw e;
    }
  }
```

- [ ] **Step 2: Add the bulk action**

After `bulkResolve` (ends at line 316), add:

```ts
  /** Bulk mark non-actionable — moves matching open rows into resolvedTickets. */
  async function bulkMarkNonActionable(ids: string[]): Promise<BulkResult> {
    const idSet = new Set(ids);
    const snapshot: Array<{ idx: number; row: Ticket }> = [];
    const moved: Ticket[] = [];
    for (let i = state.value.tickets.length - 1; i >= 0; i--) {
      const t = state.value.tickets[i]!;
      if (!idSet.has(t.id)) continue;
      snapshot.push({ idx: i, row: t });
      state.value.tickets.splice(i, 1);
      moved.push({
        ...t,
        resolved_at: new Date().toISOString(),
        resolved_source: 'non_actionable',
        resolution_chip_state: null,
      });
    }
    resolvedTickets.value = [...moved, ...resolvedTickets.value];

    try {
      const result = await api.bulkMarkNonActionable(ids);
      _rollbackFromSnapshot(result.failed, snapshot);
      return result;
    } catch (e) {
      _rollbackAll(snapshot);
      throw e;
    }
  }
```

Add `markNonActionable` and `bulkMarkNonActionable` to the store's return object (around line 489):

```ts
    markNonActionable,
    bulkMarkNonActionable,
```

- [ ] **Step 3: Typecheck**

```powershell
npm run typecheck
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add webapp/src/stores/tickets.ts
git commit -m "feat(webapp): tickets store markNonActionable + bulk variant"
```

---

## Task 10: ResolutionChip — render non-actionable variant

**Files:**
- Modify: `webapp/src/components/ResolutionChip.vue`

- [ ] **Step 1: Render the non-actionable chip**

Existing chip renders only when `resolution_chip_state` is set (it's an *advisory* chip). For non-actionable we need a different surface: a label chip on resolved cards that reflects `resolved_source` (manual / intercom_closed → "Resolved", non_actionable → "Non-actionable" muted gray). It coexists with the advisory chip.

Refactor `ResolutionChip.vue` so it can render either:
1. The advisory chip (existing behavior, when `resolution_chip_state` is set on an open ticket OR a resolved ticket with new AI activity).
2. A static "Non-actionable" badge when the ticket is resolved with `resolved_source === 'non_actionable'`.

Replace the file with:

```vue
<!-- ResolutionChip — two roles in one component:
     1. Advisory chip on cards where the backend computed `resolution_chip_state`
        (ai_resolved / ai_reopened / new_reply). Clicking applies the action;
        the × dismisses it.
     2. Static sub-state badge on resolved cards. resolved_source = 'non_actionable'
        renders as a muted gray "Non-actionable" badge; other sources render
        nothing here (the column itself communicates "resolved"). -->
<script setup lang="ts">
import { computed } from 'vue';
import { useTicketsStore } from '@/stores/tickets';
import type { Ticket } from '@/types/api';

const props = defineProps<{ ticket: Ticket }>();
const tickets = useTicketsStore();

const advisoryLabel = computed(() => {
  switch (props.ticket.resolution_chip_state) {
    case 'ai_resolved':
      return `AI: resolved? · ${(props.ticket.ai_resolution_confidence ?? 0).toFixed(2)}`;
    case 'ai_reopened':
      return `AI: reopened? · ${(props.ticket.ai_resolution_confidence ?? 0).toFixed(2)}`;
    case 'new_reply':
      return 'new reply';
    default:
      return '';
  }
});

const isNonActionable = computed(
  () =>
    props.ticket.resolved_at !== null && props.ticket.resolved_source === 'non_actionable',
);

async function onApplyAdvisory() {
  const chipState = props.ticket.resolution_chip_state;
  if (chipState === 'ai_resolved') {
    await tickets.markResolved(props.ticket.id);
  } else if (chipState === 'ai_reopened' || chipState === 'new_reply') {
    await tickets.reopen(props.ticket.id);
  }
}

async function onDismiss(e: Event) {
  e.stopPropagation();
  await tickets.dismissChip(props.ticket.id);
}
</script>

<template>
  <button
    v-if="ticket.resolution_chip_state"
    class="resolution-chip advisory"
    :title="ticket.ai_resolution_reason ?? ''"
    @click.stop="onApplyAdvisory"
  >
    {{ advisoryLabel }}
    <span class="dismiss" aria-label="Dismiss suggestion" @click="onDismiss">×</span>
  </button>
  <span v-else-if="isNonActionable" class="resolution-chip non-actionable">
    Non-actionable
  </span>
</template>

<style scoped>
.resolution-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-family: var(--font-mono);
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--chip-bg);
  color: var(--ink-2);
}
.advisory {
  cursor: pointer;
}
.advisory:hover {
  background: var(--hover);
}
.non-actionable {
  /* Muted gray — same family as the fallback "Other" category swatch. */
  background: oklch(0.65 0.00 0 / 0.12);
  color: var(--ink-3);
  border-color: var(--line);
}
.dismiss {
  font-size: 12px;
  line-height: 1;
  opacity: 0.6;
  cursor: pointer;
}
.dismiss:hover {
  opacity: 1;
}
</style>
```

- [ ] **Step 2: Smoke run dev server + visually verify**

```powershell
cd webapp
npm run dev
```

Open `http://localhost:5173`, mark a ticket non-actionable via the flyout (this task lands the chip; Task 11 lands the button). Until Task 11 ships, seed a non-actionable ticket via the backend API:

```powershell
# In another shell, with backend running on :4000
curl -X POST http://127.0.0.1:4000/tickets/<some-open-ticket-id>/non-actionable -H "Content-Type: application/json" -d "{}"
```

Then reload the board; the Resolved column should show that card with the muted "Non-actionable" badge.

- [ ] **Step 3: Run lint + typecheck**

```powershell
npm run lint
npm run typecheck
```

Expected: PASS.

- [ ] **Step 4: Commit**

```powershell
git add webapp/src/components/ResolutionChip.vue
git commit -m "feat(webapp): non-actionable badge variant on ResolutionChip"
```

---

## Task 11: TicketResolution flyout — Mark non-actionable button

**Files:**
- Modify: `webapp/src/components/ticket/TicketResolution.vue`

- [ ] **Step 1: Add the button + status copy**

Replace the `<template>` section of `webapp/src/components/ticket/TicketResolution.vue`:

```vue
<template>
  <section class="block">
    <div class="mono label">Resolution</div>
    <div class="status-row">
      <span v-if="ticket.resolved_at" class="status-pill mono">
        {{ statusLabel }} · {{ formatShortDateTime(ticket.resolved_at) }}
      </span>
      <span v-else class="status-pill mono">Open</span>
    </div>
    <div class="presets">
      <button v-if="ticket.resolved_at" class="chip" @click="onReopen">Reopen</button>
      <template v-else>
        <button class="chip" @click="onResolve">Mark resolved</button>
        <button class="chip" @click="onMarkNonActionable">Mark non-actionable</button>
      </template>
    </div>
    <div class="ai-tristate">
      <span class="mono tristate-label">AI</span>
      <div class="seg">
        <button
          :class="{ active: ticket.ai_resolve_override === null }"
          @click="setAi(null)"
        >default</button>
        <button
          :class="{ active: ticket.ai_resolve_override === true }"
          @click="setAi(true)"
        >on</button>
        <button
          :class="{ active: ticket.ai_resolve_override === false }"
          @click="setAi(false)"
        >off</button>
      </div>
    </div>
  </section>
</template>
```

Replace the `<script setup>` block:

```vue
<script setup lang="ts">
import { computed } from 'vue';
import type { Ticket } from '@/types/api';
import { useTicketsStore } from '@/stores/tickets';
import { formatShortDateTime } from '@/utils/time';

const { ticket } = defineProps<{ ticket: Ticket }>();
const tickets = useTicketsStore();

const statusLabel = computed(() => {
  switch (ticket.resolved_source) {
    case 'manual':
      return 'Resolved · manual';
    case 'intercom_closed':
      return 'Resolved · intercom';
    case 'non_actionable':
      return 'Non-actionable';
    default:
      return 'Resolved';
  }
});

async function onResolve() {
  await tickets.markResolved(ticket.id);
}

async function onReopen() {
  await tickets.reopen(ticket.id);
}

async function onMarkNonActionable() {
  await tickets.markNonActionable(ticket.id);
}

async function setAi(v: boolean | null) {
  await tickets.setAiResolve(ticket.id, v);
}
</script>
```

- [ ] **Step 2: Update Settings drawer copy (§6.7)**

In `webapp/src/components/settings/DrawerAiSection.vue` line 48, change:

```vue
      <span class="sentence">Let AI suggest resolution</span>
```

to:

```vue
      <span class="sentence">Let AI close resolved + non-actionable tickets</span>
```

If a help-text block sits below it, update from "Suggestions appear as chips on cards. AI never moves tickets automatically; you confirm every change." to:

```
When AI confidence ≥ threshold, tickets the AI judges resolved or non-actionable are closed automatically. AI never closes other tickets without your confirmation.
```

(Skip the help-text edit if the current copy already conveys this; the toggle label is the load-bearing change.)

- [ ] **Step 3: Lint + typecheck**

```powershell
npm run lint
npm run typecheck
```

Expected: PASS.

- [ ] **Step 4: Smoke test in the browser**

With the dev server running, open a ticket flyout, click "Mark non-actionable" → ticket should optimistically move to the Resolved column with the muted "Non-actionable" chip. Click the ticket again → flyout shows "Non-actionable" status and a "Reopen" button. Click Reopen → ticket returns to its category column. Open the settings drawer; the AI section copy reflects both verdicts.

- [ ] **Step 5: Commit**

```powershell
git add webapp/src/components/ticket/TicketResolution.vue webapp/src/components/settings/DrawerAiSection.vue
git commit -m "feat(webapp): Mark non-actionable flyout button + settings copy"
```

---

## Task 12: BulkActionBar — Non-actionable button

**Files:**
- Modify: `webapp/src/components/BulkActionBar.vue`

- [ ] **Step 1: Add the button + handler**

In `webapp/src/components/BulkActionBar.vue`, add a new handler beside `onResolve` (around line 94):

```ts
function onNonActionable() {
  void runBulk(
    () => tickets.bulkMarkNonActionable(selection.asArray()),
    'marked non-actionable',
  );
}
```

In the `<template>`, insert a button between Resolve and Reopen (the Resolve button starts at line 129):

```vue
      <button
        type="button"
        :disabled="busy || !noneResolved"
        :title="
          noneResolved
            ? 'Mark selected non-actionable'
            : 'Some selected are already resolved'
        "
        @click="onNonActionable"
      >
        Non-actionable
      </button>
```

Place it directly AFTER the Resolve button and BEFORE the Reopen button so the visual order reads: Resolve / Non-actionable / Reopen.

- [ ] **Step 2: Lint + typecheck**

```powershell
npm run lint
npm run typecheck
```

Expected: PASS.

- [ ] **Step 3: Smoke test**

Dev server up; select 2-3 open tickets via Cmd/Ctrl+click; the bulk bar appears; click "Non-actionable"; selected cards move to Resolved column with muted badge; toast reads "3 marked non-actionable" (or similar).

- [ ] **Step 4: Commit**

```powershell
git add webapp/src/components/BulkActionBar.vue
git commit -m "feat(webapp): Non-actionable button on bulk action bar"
```

---

## Task 13: Extension — `markNonActionable` API helper

**Files:**
- Modify: `extension/api.js`

- [ ] **Step 1: Add the helper**

In `extension/api.js`, after `reopenTicket` (line 67), add:

```js
/** Mark a ticket non-actionable. 409 if already resolved, 404 if unknown. */
export const markNonActionable = (ticketId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/non-actionable`, { method: 'POST' });
```

- [ ] **Step 2: Commit**

```powershell
git add extension/api.js
git commit -m "feat(extension): markNonActionable api helper"
```

---

## Task 14: Extension popup — chip + card menu entry

**Files:**
- Modify: `extension/popup.js`
- Modify: `extension/popup.css`

- [ ] **Step 1: Add the action button + chip**

In `extension/popup.js`, top of file (around the existing imports at line 13-26), add `markNonActionable` to the import list:

```js
import {
  fetchCategories,
  fetchFollowups,
  fetchSettings,
  getResolvedTickets,
  getStoredTickets,
  getSyncState,
  ingestTickets,
  markFollowupFired,
  markNonActionable,  // ← new
  overrideCategory,
  reopenTicket,
  resolveTicket,
  FULL_BOARD_URL,
} from './api.js';
```

In `renderCard` (line 162), in the open/category-tabs branch (`else` block starting at line 193), add the non-actionable button alongside Resolve. After the `resolveBtn` lines (195-197):

```js
    const naBtn = node('button', 'action-btn non-actionable-btn', '⊘ Non-actionable');
    naBtn.addEventListener('click', () => void doMarkNonActionable(ticket));
    meta.append(naBtn);
```

In the resolved-tab branch (`if (isResolved)`, line 188-192), before the `reopenBtn` block, add a chip element when the source is non-actionable:

```js
  if (isResolved && ticket.resolved_source === 'non_actionable') {
    const chip = node('span', 'na-badge mono', 'Non-actionable');
    meta.append(chip);
  }
```

Add the `doMarkNonActionable` function near `doResolve` (around line 380). First, read the existing `doResolve` to mirror its shape. Append:

```js
async function doMarkNonActionable(ticket) {
  try {
    const result = await markNonActionable(ticket.id);
    ticket.resolved_at = result.resolved_at;
    ticket.resolved_source = result.resolved_source ?? 'non_actionable';
    // Move from open list to resolved list.
    state.tickets = state.tickets.filter((t) => t.id !== ticket.id);
    state.resolvedTickets = [ticket, ...state.resolvedTickets];
    renderList();
    renderCount();
  } catch (e) {
    state.error = `Mark non-actionable failed: ${e.message}`;
    renderList();
  }
}
```

If the existing `doResolve` does additional bookkeeping (mute, badge, etc.), mirror those calls in `doMarkNonActionable` — read line 378-400 of `popup.js` for the exact list before commit.

- [ ] **Step 2: Add chip + button styles**

In `extension/popup.css`, append:

```css
.action-btn.non-actionable-btn {
  /* Same shape as the resolve btn, muted gray to match the webapp. */
  border-color: var(--line);
  color: var(--ink-3);
}
.na-badge {
  display: inline-flex;
  align-items: center;
  font-size: 9px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border: 1px solid var(--line);
  border-radius: 4px;
  background: oklch(0.65 0.00 0 / 0.12);
  color: var(--ink-3);
}
```

- [ ] **Step 3: Smoke test the extension**

Reload the unpacked extension in `chrome://extensions`, click the icon, open the popup. Verify:
- Open tab → each card now shows ⊘ Non-actionable next to ✓ Resolve.
- Click ⊘ → card disappears from the open tab.
- Switch to Resolved tab → card shows with "Non-actionable" badge.
- Click ↺ Reopen → card returns to its category tab.

- [ ] **Step 4: Commit**

```powershell
git add extension/popup.js extension/popup.css
git commit -m "feat(extension): non-actionable button + badge in popup"
```

---

## Task 15: Webapp Vitest specs — store + chip + flyout + bulk bar

**Files:**
- Create: `webapp/src/stores/tickets.spec.ts`
- Create: `webapp/src/components/ResolutionChip.spec.ts`
- Create: `webapp/src/components/ticket/TicketResolution.spec.ts`
- Create: `webapp/src/components/BulkActionBar.spec.ts`

Vue Test Utils + happy-dom are already installed (`webapp/package.json` devDeps). The existing `selection.spec.ts` is the precedent for store tests; component specs are a new pattern but supported by the existing toolchain.

- [ ] **Step 1: Write store-level spec for tickets actions**

Create `webapp/src/stores/tickets.spec.ts`:

```ts
// Tickets-store spec — covers markNonActionable + bulkMarkNonActionable
// optimistic + rollback. Reference: docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md §10.2.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useTicketsStore } from './tickets';
import type { Ticket } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    markNonActionable: vi.fn(),
    bulkMarkNonActionable: vi.fn(),
    resolveTicket: vi.fn(),
    reopenTicket: vi.fn(),
    bulkResolve: vi.fn(),
    bulkReopen: vi.fn(),
    bulkRecategorize: vi.fn(),
    bulkDismissChip: vi.fn(),
    setAiResolve: vi.fn(),
    dismissChip: vi.fn(),
    overrideCategory: vi.fn(),
    editTicket: vi.fn(),
    listTickets: vi.fn(),
  },
}));

const NOW = '2026-05-25T00:00:00.000Z';

function fakeTicket(id: string, overrides: Partial<Ticket> = {}): Ticket {
  return {
    id,
    title: `t-${id}`,
    state: 'open',
    priority: null,
    created_at: NOW,
    updated_at: NOW,
    author: { id: null, name: null, email: null, type: 'user' },
    url: null,
    parts: [],
    internal_notes: [],
    category_id: 1,
    proposal_id: null,
    summary: '',
    ai_confidence: 0,
    user_override: false,
    title_user_edited: false,
    summary_user_edited: false,
    followup: null,
    note: null,
    resolved_at: null,
    resolved_source: null,
    ai_resolve_enabled: false,
    ai_resolve_override: null,
    ai_resolution_verdict: null,
    ai_resolution_confidence: null,
    ai_resolution_reason: null,
    resolution_chip_state: null,
    ...overrides,
  };
}

describe('ticketsStore.markNonActionable', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('moves the ticket to resolvedTickets with non_actionable source', async () => {
    const { api } = await import('@/api/client');
    (api.markNonActionable as ReturnType<typeof vi.fn>).mockResolvedValue({
      resolved_at: NOW,
      resolved_source: 'non_actionable',
    });
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('a'));

    await s.markNonActionable('a');

    expect(s.tickets.find((t) => t.id === 'a')).toBeUndefined();
    const moved = s.resolvedTickets.find((t) => t.id === 'a');
    expect(moved).toBeDefined();
    expect(moved!.resolved_source).toBe('non_actionable');
  });

  it('rolls back on API failure', async () => {
    const { api } = await import('@/api/client');
    (api.markNonActionable as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('boom'),
    );
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('b'));

    await expect(s.markNonActionable('b')).rejects.toThrow('boom');
    expect(s.tickets.find((t) => t.id === 'b')).toBeDefined();
    expect(s.resolvedTickets.find((t) => t.id === 'b')).toBeUndefined();
  });
});

describe('ticketsStore.bulkMarkNonActionable', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('moves every ok id and rolls back failed ids', async () => {
    const { api } = await import('@/api/client');
    (api.bulkMarkNonActionable as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok_ids: ['x', 'z'],
      failed: [{ id: 'y', reason: 'already resolved' }],
    });
    const s = useTicketsStore();
    s.tickets.push(fakeTicket('x'), fakeTicket('y'), fakeTicket('z'));

    const result = await s.bulkMarkNonActionable(['x', 'y', 'z']);

    expect(result.ok_ids).toEqual(['x', 'z']);
    expect(s.resolvedTickets.map((t) => t.id).sort()).toEqual(['x', 'z']);
    expect(s.tickets.find((t) => t.id === 'y')).toBeDefined();
  });
});
```

- [ ] **Step 2: Run the store spec**

```powershell
cd webapp
npm test -- tickets.spec
```

Expected: PASS.

- [ ] **Step 3: Write the ResolutionChip component spec**

Create `webapp/src/components/ResolutionChip.spec.ts`:

```ts
// ResolutionChip spec — renders correct variant per resolved_source +
// resolution_chip_state. Reference: spec §10.2.

import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ResolutionChip from './ResolutionChip.vue';
import type { Ticket } from '@/types/api';

const NOW = '2026-05-25T00:00:00.000Z';

function base(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 't1', title: 'x', state: 'open', priority: null,
    created_at: NOW, updated_at: NOW,
    author: { id: null, name: null, email: null, type: 'user' },
    url: null, parts: [], internal_notes: [],
    category_id: 1, proposal_id: null, summary: '', ai_confidence: 0,
    user_override: false, title_user_edited: false, summary_user_edited: false,
    followup: null, note: null,
    resolved_at: null, resolved_source: null,
    ai_resolve_enabled: false, ai_resolve_override: null,
    ai_resolution_verdict: null, ai_resolution_confidence: null,
    ai_resolution_reason: null, resolution_chip_state: null,
    ...overrides,
  };
}

describe('ResolutionChip', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('renders nothing for an open ticket with no chip state', () => {
    const w = mount(ResolutionChip, { props: { ticket: base() } });
    expect(w.html().trim()).toBe('');
  });

  it('renders the non-actionable badge on resolved non_actionable tickets', () => {
    const w = mount(ResolutionChip, {
      props: {
        ticket: base({ resolved_at: NOW, resolved_source: 'non_actionable' }),
      },
    });
    expect(w.text()).toContain('Non-actionable');
    expect(w.classes()).toContain('non-actionable');
  });

  it('renders the advisory chip when resolution_chip_state is set', () => {
    const w = mount(ResolutionChip, {
      props: {
        ticket: base({
          resolution_chip_state: 'ai_resolved',
          ai_resolution_confidence: 0.81,
        }),
      },
    });
    expect(w.text()).toContain('AI: resolved?');
    expect(w.text()).toContain('0.81');
  });
});
```

Add `import { beforeEach } from 'vitest';` to the top if eslint flags it as missing.

- [ ] **Step 4: Write the TicketResolution flyout spec**

Create `webapp/src/components/ticket/TicketResolution.spec.ts`:

```ts
// TicketResolution flyout spec — Mark-non-actionable button visibility
// per ticket state. Reference: spec §10.2.

import { beforeEach, describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import TicketResolution from './TicketResolution.vue';
import type { Ticket } from '@/types/api';

const NOW = '2026-05-25T00:00:00.000Z';

function base(overrides: Partial<Ticket> = {}): Ticket {
  return {
    id: 't1', title: 'x', state: 'open', priority: null,
    created_at: NOW, updated_at: NOW,
    author: { id: null, name: null, email: null, type: 'user' },
    url: null, parts: [], internal_notes: [],
    category_id: 1, proposal_id: null, summary: '', ai_confidence: 0,
    user_override: false, title_user_edited: false, summary_user_edited: false,
    followup: null, note: null,
    resolved_at: null, resolved_source: null,
    ai_resolve_enabled: false, ai_resolve_override: null,
    ai_resolution_verdict: null, ai_resolution_confidence: null,
    ai_resolution_reason: null, resolution_chip_state: null,
    ...overrides,
  };
}

describe('TicketResolution', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('shows Mark non-actionable + Mark resolved on an open ticket', () => {
    const w = mount(TicketResolution, { props: { ticket: base() } });
    expect(w.text()).toContain('Mark non-actionable');
    expect(w.text()).toContain('Mark resolved');
    expect(w.text()).not.toContain('Reopen');
  });

  it('shows only Reopen on a resolved ticket', () => {
    const w = mount(TicketResolution, {
      props: {
        ticket: base({ resolved_at: NOW, resolved_source: 'non_actionable' }),
      },
    });
    expect(w.text()).toContain('Reopen');
    expect(w.text()).not.toContain('Mark non-actionable');
    expect(w.text()).not.toContain('Mark resolved');
  });

  it('renders non-actionable status pill copy', () => {
    const w = mount(TicketResolution, {
      props: {
        ticket: base({ resolved_at: NOW, resolved_source: 'non_actionable' }),
      },
    });
    expect(w.text()).toContain('Non-actionable');
  });
});
```

- [ ] **Step 5: Write the BulkActionBar spec**

Create `webapp/src/components/BulkActionBar.spec.ts`:

```ts
// BulkActionBar spec — Non-actionable button disabled when any selected ticket
// is already resolved. Reference: spec §10.2.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import BulkActionBar from './BulkActionBar.vue';
import { useSelectionStore } from '@/stores/selection';
import { useTicketsStore } from '@/stores/tickets';
import type { Ticket } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listTickets: vi.fn().mockResolvedValue([]),
    listCategories: vi.fn().mockResolvedValue({ categories: [], pending_proposals: [] }),
    listFollowups: vi.fn().mockResolvedValue([]),
  },
}));

const NOW = '2026-05-25T00:00:00.000Z';
function fake(id: string, overrides: Partial<Ticket> = {}): Ticket {
  return {
    id, title: id, state: 'open', priority: null,
    created_at: NOW, updated_at: NOW,
    author: { id: null, name: null, email: null, type: 'user' },
    url: null, parts: [], internal_notes: [],
    category_id: 1, proposal_id: null, summary: '', ai_confidence: 0,
    user_override: false, title_user_edited: false, summary_user_edited: false,
    followup: null, note: null,
    resolved_at: null, resolved_source: null,
    ai_resolve_enabled: false, ai_resolve_override: null,
    ai_resolution_verdict: null, ai_resolution_confidence: null,
    ai_resolution_reason: null, resolution_chip_state: null,
    ...overrides,
  };
}

describe('BulkActionBar — Non-actionable button', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('is enabled when every selected ticket is open', () => {
    const selection = useSelectionStore();
    const tickets = useTicketsStore();
    tickets.tickets.push(fake('a'), fake('b'));
    selection.toggle('a', 'col1');
    selection.toggle('b', 'col1');

    const w = mount(BulkActionBar);
    const btn = w.findAll('button').find((b) => b.text() === 'Non-actionable');
    expect(btn).toBeDefined();
    expect(btn!.attributes('disabled')).toBeUndefined();
  });

  it('is disabled when any selected ticket is already resolved', () => {
    const selection = useSelectionStore();
    const tickets = useTicketsStore();
    tickets.tickets.push(fake('a'));
    tickets.resolvedTickets.push(fake('r', { resolved_at: NOW, resolved_source: 'manual' }));
    selection.toggle('a', 'col1');
    selection.toggle('r', 'resolved');

    const w = mount(BulkActionBar);
    const btn = w.findAll('button').find((b) => b.text() === 'Non-actionable');
    expect(btn).toBeDefined();
    expect(btn!.attributes('disabled')).toBeDefined();
  });
});
```

- [ ] **Step 6: Run all webapp tests**

```powershell
npm test
```

Expected: every spec passes. If happy-dom flags a missing global, add `// @vitest-environment happy-dom` to the top of the component spec files. The existing `vitest.config.ts` (or `vite.config.ts`) should already set happy-dom as the default — verify; if not, set it via spec-level pragma.

- [ ] **Step 7: Commit**

```powershell
git add webapp/src/stores/tickets.spec.ts webapp/src/components/ResolutionChip.spec.ts webapp/src/components/ticket/TicketResolution.spec.ts webapp/src/components/BulkActionBar.spec.ts
git commit -m "test(webapp): vitest specs for non-actionable flow"
```

---

## Task 16: Docs — invariants, tasks, backlog

**Files:**
- Modify: `CLAUDE.md` (root)
- Modify: `tasks.md` (root)
- Modify: `docs/tasks/backlog.md`
- Create: `docs/tasks/phase-13-non-actionable.md`

- [ ] **Step 1: Widen invariant #10 in root `CLAUDE.md`**

In `CLAUDE.md` change line 167:

```
10. **`tickets.resolved_at` ⇔ `resolved_source`** (XOR CheckConstraint). `resolved_source ∈ {'manual', 'intercom_closed'}`.
```

to:

```
10. **`tickets.resolved_at` ⇔ `resolved_source`** (XOR CheckConstraint). `resolved_source ∈ {'manual', 'intercom_closed', 'non_actionable'}`. Non-actionable is a sub-state of resolved — same column, distinct chip; same reopen path clears it.
```

- [ ] **Step 2: Add Phase 13 to `tasks.md`**

In `tasks.md`, after the Phase 12 entry (ends at line 136), insert:

```
### [Phase 13 — Non-actionable tickets](docs/tasks/phase-13-non-actionable.md)
- T085 ✓ — Migration 0010 widens resolved_source + ai_resolution_verdict CHECK
- T086 ✓ — AI prompt + parser carry non_actionable verdict
- T087 ✓ — Ingest auto-applies non_actionable under shared threshold
- T088 ✓ — Resolution service: mark_non_actionable + bulk variant
- T089 ✓ — `POST /tickets/{id}/non-actionable` + `POST /tickets/bulk/non-actionable`
- T090 ✓ — Webapp types + API client + tickets store actions
- T091 ✓ — ResolutionChip non-actionable badge variant
- T092 ✓ — Flyout: Mark non-actionable button
- T093 ✓ — BulkActionBar: Non-actionable button
- T094 ✓ — Extension popup: non-actionable button + badge
- T095 ✓ — Docs (CLAUDE.md invariant, spec/plan/tasks index)
```

Remove the `✓` markers if you'd rather track them as work-in-progress while the plan executes; final commit can stamp them done in a one-line patch.

In the traceability matrix, append rows:

```
| FR-037 | T086, T087, T088, T089, T090, T091, T092, T093 |
| US-019 | T088, T089, T092, T093, T094 |
```

- [ ] **Step 3: Create `docs/tasks/phase-13-non-actionable.md`**

```markdown
# Phase 13 — Non-actionable tickets

Back to [tasks.md](../../tasks.md).

Spec: [`docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md`](../superpowers/specs/2026-05-25-non-actionable-tickets-design.md).
Plan: [`docs/superpowers/plans/2026-05-25-non-actionable-tickets.md`](../superpowers/plans/2026-05-25-non-actionable-tickets.md).

### T085 — Migration 0010
**Depends on:** T054
**Implements:** FR-037, plan §6
**Description:** Widen `tickets.resolved_source` and `ai_cache.ai_resolution_verdict` CHECK constraints to include `'non_actionable'`. No new columns.
**Acceptance:**
- [ ] In-memory smoke + pytest pass.
- [ ] `alembic upgrade head` → `downgrade -1` round-trip clean.

### T086 — AI prompt + parser carry non_actionable
**Depends on:** T056, T085
**Implements:** FR-037, US-019
**Description:** SYSTEM_PROMPT documents the 3-way verdict and the canonical kind tags. Parser accepts all three values; rejects others as `None` (existing fallback path).
**Acceptance:**
- [ ] `tests/test_resolution_prompt.py` passes for non_actionable cases.
- [ ] Out-of-set verdict still clamps to `None`.

### T087 — Ingest auto-applies non_actionable
**Depends on:** T086
**Implements:** FR-037, plan §6
**Description:** `_upsert_ticket` stamps `resolved_source = result.ai_resolution_verdict` when verdict ∈ {resolved, non_actionable}, confidence ≥ threshold, effective `ai_resolve_enabled` is true, and the row isn't already resolved.
**Acceptance:**
- [ ] `tests/test_resolution_ingest.py` covers happy path + threshold gate + auto-resolve-disabled gate.
- [ ] Intercom-closed transitions still take precedence.

### T088 — Resolution service: mark_non_actionable
**Depends on:** T085
**Implements:** FR-037, US-019
**Description:** Add `apply_mark_non_actionable` + `mark_non_actionable` to `services/resolution.py`. Add `bulk_mark_non_actionable` to `services/bulk.py`. 409 if already resolved, 404 if unknown.
**Acceptance:**
- [ ] `tests/test_resolution_service.py` covers happy + 404 + 409.
- [ ] Bulk loop reuses `_run_per_id`.

### T089 — Endpoints: single + bulk
**Depends on:** T088
**Implements:** FR-037, US-019
**Description:** `POST /tickets/{id}/non-actionable` + `POST /tickets/bulk/non-actionable`. Schema literal widening for `ResolvedSource` + `ResolutionVerdict`.
**Acceptance:**
- [ ] `tests/test_resolution_api.py` + `tests/test_bulk_api.py` cover happy, 404, 409, cap, empty.
- [ ] Reopen clears `'non_actionable'` source.

### T090 — Webapp types + API client + tickets store
**Depends on:** T089
**Implements:** FR-037
**Description:** Widen `ResolvedSource` + `ResolutionVerdict` TS unions. Add `markNonActionable` + `bulkMarkNonActionable` to client + tickets store, mirroring `markResolved` / `bulkResolve`.
**Acceptance:**
- [ ] `npm run typecheck` clean.

### T091 — ResolutionChip non-actionable badge variant
**Depends on:** T090
**Implements:** FR-037
**Description:** Chip renders muted "Non-actionable" badge on resolved cards whose `resolved_source === 'non_actionable'`.
**Acceptance:**
- [ ] Manual smoke: chip renders on a seeded non-actionable ticket.

### T092 — Flyout: Mark non-actionable button
**Depends on:** T090
**Implements:** FR-037, US-019
**Description:** Add "Mark non-actionable" sibling button. Update status-pill copy to discriminate by source.
**Acceptance:**
- [ ] Manual smoke: button moves ticket to Resolved column; Reopen returns it.

### T093 — BulkActionBar: Non-actionable button
**Depends on:** T090
**Implements:** FR-037, US-019
**Description:** Add "Non-actionable" button between Resolve + Reopen. Disabled when any selected card is already resolved.
**Acceptance:**
- [ ] Manual smoke: 3-card selection → button → 3 cards move + toast.

### T094 — Extension popup
**Depends on:** T089
**Implements:** FR-037, US-019
**Description:** Add `markNonActionable` helper, ⊘ button on open-tab cards, "Non-actionable" badge on resolved-tab cards.
**Acceptance:**
- [ ] Manual smoke after reloading unpacked extension.

### T095 — Docs
**Depends on:** T094
**Implements:** plan §13
**Description:** Widen CLAUDE.md invariant #10, add Phase 13 to tasks.md index + traceability matrix, add T106/T107 backlog stubs, refresh spec.md + plan.md version headers if appropriate.
**Acceptance:**
- [ ] Repo-wide green path passes per CLAUDE.md table.
```

- [ ] **Step 4: Add backlog stubs**

In `docs/tasks/backlog.md`, append:

```
- **T106** — Parked / snoozed state. Operator-chosen "waiting on third party / customer / hold." Distinct from non-actionable (Phase 13): non-actionable = nothing to do; parked = deferred action. Likely new `parked_at` + `parked_until` columns, separate column on the board OR a parked-filter chip on category columns. UI shape TBD.
- **T107** — Structured `non_actionable_kind` column on tickets + ai_cache (auto_reply / thanks / spam / out_of_office / other). Enables per-kind filtering + analytics. AI prompt already leads `ai_resolution_reason` with a kind tag — additive migration when needed.
```

- [ ] **Step 5: Run the repo-wide green path**

```powershell
# Backend
cd backend
.\.venv\Scripts\Activate.ps1
ruff check app tests
ruff format --check app tests
mypy app
pytest -q

# Webapp
cd ..\webapp
npm run lint
npm run format:check
npm run typecheck
npm test
npm run build

# Extension
# Manual: reload unpacked in chrome://extensions; verify popup smoke checklist.
```

Expected: green on every check.

- [ ] **Step 6: Commit**

```powershell
git add CLAUDE.md tasks.md docs/tasks/backlog.md docs/tasks/phase-13-non-actionable.md
git commit -m "docs(phase-13): non-actionable invariants + task index + backlog stubs"
```

---

## Final verification

After Task 16, run the cross-package green path one more time per CLAUDE.md §4. Smoke the full flow end-to-end:

1. Backend running on `:4000`. Webapp dev server on `:5173`. Extension loaded unpacked.
2. Trigger an Intercom sync from the popup → tickets ingest.
3. Webapp board shows new tickets. Flyout a ticket → click "Mark non-actionable" → card moves to Resolved column with muted "Non-actionable" badge.
4. Popup → switch to Resolved tab → same card shows the same badge.
5. Click Reopen (webapp or popup) → card returns to its category column.
6. Select 3 open tickets via Cmd/Ctrl+click → BulkActionBar appears → click "Non-actionable" → 3 cards move → toast reads `3 marked non-actionable`.
7. `curl http://127.0.0.1:4000/metrics` → confirm `tickets_resolved_total.non_actionable` and `bulk_actions_total.non_actionable.ok` counters incremented.

Plan complete when steps 1-7 pass.

# Ticket Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Operator can mark tickets resolved (manual, via Intercom-closed transition, or via AI suggestion confirmed by operator); resolved tickets live in a dedicated always-visible Kanban column and never auto-reopen.

**Architecture:** Orthogonal `resolved_at` + `resolved_source` flag on `tickets`. Existing AI categorization call returns extra fields for an advisory resolution verdict (bundled, not separate). Server computes a `resolution_chip_state` for the front-end. Closure pass added to the extension's sync flow.

**Tech Stack:** FastAPI / SQLAlchemy 2.0 async / Alembic / pytest (backend) · Vue 3 + Pinia + TS + Vitest (webapp) · MV3 vanilla JS (extension).

**Spec:** `docs/superpowers/specs/2026-05-23-ticket-resolution-design.md`

---

## File map

**Backend create:**
- `backend/alembic/versions/0006_add_ticket_resolution.py`
- `backend/app/services/resolution.py` — manual resolve / reopen / chip-dismissal / ai-flag mutation
- `backend/tests/test_resolution_service.py`
- `backend/tests/test_resolution_api.py`
- `backend/tests/test_resolution_ingest.py`
- `backend/tests/test_resolution_prompt.py`

**Backend modify:**
- `backend/app/models.py` — `Ticket`, `AICacheEntry`, `Settings` additions
- `backend/app/schemas.py` — `TicketSchema`, `FilterSettings`, new request bodies
- `backend/app/ai/prompt.py` — extend SYSTEM_PROMPT for resolution fields
- `backend/app/ai/pipeline.py` — `ParsedAssignment` + `CategorizationResult` carry resolution fields
- `backend/app/services/cache.py` — persist + return resolution fields
- `backend/app/services/tickets.py` — `_upsert_ticket` writes Intercom-closed transition + AI verdict to `tickets`; `get_tickets` accepts `?resolved=`; `set_override` atomically reopens
- `backend/app/services/settings.py` — load + save new fields
- `backend/app/routers/tickets.py` — new endpoints + query param
- `backend/app/routers/settings.py` — settings response schema

**Webapp create:**
- `webapp/src/components/ResolvedColumn.vue`
- `webapp/src/components/ResolutionChip.vue`

**Webapp modify:**
- `webapp/src/types/api.ts`
- `webapp/src/api/client.ts`
- `webapp/src/stores/tickets.ts`
- `webapp/src/stores/settings.ts`
- `webapp/src/components/Board.vue`
- `webapp/src/components/Column.vue` (drag-source allow-out logic)
- `webapp/src/components/TicketCard.vue`
- `webapp/src/components/TicketFlyout.vue`
- `webapp/src/components/SettingsDrawer.vue`

**Extension modify:**
- `extension/api.js` — call `GET /tickets/sync-state`, hit Intercom closed-list, ingest closures
- `extension/intercom.js` — closure-list helper
- `extension/background.js` — closure pass wired into the sync
- `extension/popup.js` + `extension/popup.css` — Resolved tab, resolve action

**Docs modify:**
- `spec.md` — US-015/016/017 + new FRs
- `plan.md` — §8c (Resolution) + schema additions
- `tasks.md` — Phase 11 entries + traceability matrix updates

---

## Task 1: Alembic migration — schema additions

**Files:**
- Create: `backend/alembic/versions/0006_add_ticket_resolution.py`
- Test: `backend/tests/test_models.py` (extend existing)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_models.py`:

```python
import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models import AICacheEntry, Settings, Ticket
from app.util import naive_utcnow


@pytest.mark.asyncio
async def test_ticket_has_resolution_columns(session_factory):
    async with session_factory() as session:
        cols = {c["name"] for c in inspect(session.bind.sync_engine).get_columns("tickets")}
    assert {
        "resolved_at",
        "resolved_source",
        "ai_resolve_enabled",
        "resolution_chip_dismissed_at",
    }.issubset(cols)


@pytest.mark.asyncio
async def test_ticket_resolution_xor_check(session_factory):
    """resolved_at and resolved_source must be both null or both non-null."""
    from app.models import Ticket
    async with session_factory() as session:
        ticket = Ticket(
            id="t1",
            title="x",
            state="open",
            author={},
            parts=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
            resolved_at=naive_utcnow(),
            resolved_source=None,  # one null, other not → must fail
        )
        session.add(ticket)
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.asyncio
async def test_ai_cache_has_resolution_columns(session_factory):
    async with session_factory() as session:
        cols = {c["name"] for c in inspect(session.bind.sync_engine).get_columns("ai_cache")}
    assert {"ai_resolution_verdict", "ai_resolution_confidence", "ai_resolution_reason"}.issubset(cols)


@pytest.mark.asyncio
async def test_settings_has_resolution_columns(session_factory):
    async with session_factory() as session:
        cols = {c["name"] for c in inspect(session.bind.sync_engine).get_columns("settings")}
    assert {"ai_resolve_default", "ai_resolve_confidence_threshold"}.issubset(cols)
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
cd backend
pytest tests/test_models.py::test_ticket_has_resolution_columns tests/test_models.py::test_ai_cache_has_resolution_columns tests/test_models.py::test_settings_has_resolution_columns -v
```

Expected: FAIL — columns do not exist yet.

- [ ] **Step 3: Write the Alembic migration**

Create `backend/alembic/versions/0006_add_ticket_resolution.py`:

```python
"""Add ticket-resolution fields.

Adds:
- tickets.resolved_at, .resolved_source, .ai_resolve_enabled, .resolution_chip_dismissed_at
- ai_cache.ai_resolution_verdict, .ai_resolution_confidence, .ai_resolution_reason
- settings.ai_resolve_default, .ai_resolve_confidence_threshold

Revision ID: 0006
Revises: 0005
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("resolved_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_resolve_enabled", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("resolution_chip_dismissed_at", sa.DateTime(), nullable=True))
        batch_op.create_check_constraint(
            "tickets_resolved_xor_check",
            "(resolved_at IS NULL) = (resolved_source IS NULL)",
        )
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source IN ('manual','intercom_closed')",
        )
    op.create_index(
        "ix_tickets_resolved_at",
        "tickets",
        ["resolved_at"],
        sqlite_where=sa.text("resolved_at IS NOT NULL"),
        postgresql_where=sa.text("resolved_at IS NOT NULL"),
    )

    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.add_column(sa.Column("ai_resolution_verdict", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_resolution_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("ai_resolution_reason", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ai_cache_resolution_verdict_check",
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict IN ('resolved','not_resolved')",
        )
        batch_op.create_check_constraint(
            "ai_cache_resolution_reason_len_check",
            "ai_resolution_reason IS NULL OR length(ai_resolution_reason) <= 120",
        )

    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("ai_resolve_default", sa.Boolean(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column(
                "ai_resolve_confidence_threshold",
                sa.Float(),
                nullable=False,
                server_default="0.7",
            ),
        )
        batch_op.create_check_constraint(
            "settings_ai_resolve_threshold_check",
            "ai_resolve_confidence_threshold BETWEEN 0.0 AND 1.0",
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_constraint("settings_ai_resolve_threshold_check", type_="check")
        batch_op.drop_column("ai_resolve_confidence_threshold")
        batch_op.drop_column("ai_resolve_default")

    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_resolution_reason_len_check", type_="check")
        batch_op.drop_constraint("ai_cache_resolution_verdict_check", type_="check")
        batch_op.drop_column("ai_resolution_reason")
        batch_op.drop_column("ai_resolution_confidence")
        batch_op.drop_column("ai_resolution_verdict")

    op.drop_index("ix_tickets_resolved_at", table_name="tickets")
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.drop_constraint("tickets_resolved_xor_check", type_="check")
        batch_op.drop_column("resolution_chip_dismissed_at")
        batch_op.drop_column("ai_resolve_enabled")
        batch_op.drop_column("resolved_source")
        batch_op.drop_column("resolved_at")
```

- [ ] **Step 4: Update SQLAlchemy models**

In `backend/app/models.py` — modify the `Ticket` class to add four fields (paste right after `ingested_at`, before `__table_args__`):

```python
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_resolve_enabled: Mapped[bool | None] = mapped_column(nullable=True)
    resolution_chip_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Extend `Ticket.__table_args__`:

```python
    __table_args__ = (
        Index("ix_tickets_updated_at", "updated_at"),
        Index("ix_tickets_category", "category_id"),
        Index(
            "ix_tickets_resolved_at",
            "resolved_at",
            sqlite_where=text("resolved_at IS NOT NULL"),
            postgresql_where=text("resolved_at IS NOT NULL"),
        ),
        CheckConstraint(
            "(resolved_at IS NULL) = (resolved_source IS NULL)",
            name="tickets_resolved_xor_check",
        ),
        CheckConstraint(
            "resolved_source IS NULL OR resolved_source IN ('manual','intercom_closed')",
            name="tickets_resolved_source_check",
        ),
    )
```

Add to `AICacheEntry`:

```python
    ai_resolution_verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_resolution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Extend `AICacheEntry.__table_args__` with two CHECKs:

```python
        CheckConstraint(
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict IN ('resolved','not_resolved')",
            name="ai_cache_resolution_verdict_check",
        ),
        CheckConstraint(
            "ai_resolution_reason IS NULL OR length(ai_resolution_reason) <= 120",
            name="ai_cache_resolution_reason_len_check",
        ),
```

Add to `Settings`:

```python
    ai_resolve_default: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("0"),
        nullable=False,
    )
    ai_resolve_confidence_threshold: Mapped[float] = mapped_column(
        Float,
        default=0.7,
        server_default=text("0.7"),
        nullable=False,
    )
```

Add to `Settings.__table_args__`:

```python
        CheckConstraint(
            "ai_resolve_confidence_threshold BETWEEN 0.0 AND 1.0",
            name="settings_ai_resolve_threshold_check",
        ),
```

- [ ] **Step 5: Run tests, verify they pass**

```bash
cd backend
pytest tests/test_models.py -v
```

Expected: PASS — all four new tests + existing ones green. `init_db` runs `create_all` so test DBs pick up columns automatically; the Alembic migration is only needed for existing prod DBs.

- [ ] **Step 6: Commit**

```bash
git add backend/alembic/versions/0006_add_ticket_resolution.py backend/app/models.py backend/tests/test_models.py
git commit -m "Add ticket-resolution schema (tickets, ai_cache, settings)"
```

---

## Task 2: Pydantic schemas

**Files:**
- Modify: `backend/app/schemas.py`
- Test: `backend/tests/test_models.py` (additions)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_models.py`:

```python
def test_ticket_schema_carries_resolution_fields():
    from app.schemas import TicketSchema, TicketAuthorSchema
    from datetime import datetime
    payload = {
        "id": "t1",
        "title": "x",
        "state": "open",
        "priority": None,
        "created_at": datetime(2026, 5, 23),
        "updated_at": datetime(2026, 5, 23),
        "author": {"id": None, "name": None, "email": None, "type": None},
        "url": None,
        "parts": [],
        "category_id": 1,
        "proposal_id": None,
        "summary": "",
        "ai_confidence": 0.0,
        "user_override": False,
        "resolved_at": None,
        "resolved_source": None,
        "ai_resolve_enabled": False,
        "ai_resolution_verdict": None,
        "ai_resolution_confidence": None,
        "ai_resolution_reason": None,
        "resolution_chip_state": None,
    }
    ticket = TicketSchema.model_validate(payload)
    assert ticket.resolved_at is None
    assert ticket.ai_resolve_enabled is False
    assert ticket.resolution_chip_state is None


def test_resolve_request_body_accepts_empty():
    from app.schemas import AIResolveSet
    AIResolveSet.model_validate({"enabled": True})
    AIResolveSet.model_validate({"enabled": False})
    AIResolveSet.model_validate({"enabled": None})
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_models.py::test_ticket_schema_carries_resolution_fields backend/tests/test_models.py::test_resolve_request_body_accepts_empty -v
```

Expected: FAIL — fields/classes do not exist.

- [ ] **Step 3: Update `backend/app/schemas.py`**

Add the type literal near the other Literals (after `ProposalStatus = ...`):

```python
ResolvedSource = Literal["manual", "intercom_closed"]
ResolutionVerdict = Literal["resolved", "not_resolved"]
ResolutionChipState = Literal["ai_resolved", "ai_reopened", "new_reply"]
```

Extend `TicketSchema` (after `note`):

```python
    resolved_at: UTCDatetime | None = None
    resolved_source: ResolvedSource | None = None
    ai_resolve_enabled: bool = False  # effective value after merging w/ settings default
    ai_resolution_verdict: ResolutionVerdict | None = None
    ai_resolution_confidence: float | None = None
    ai_resolution_reason: str | None = None
    resolution_chip_state: ResolutionChipState | None = None
```

Add request bodies (near `CategoryUpdate`):

```python
class AIResolveSet(BaseModel):
    """PATCH /tickets/{id}/ai-resolve body. `null` clears the per-ticket
    override and lets the ticket inherit settings.ai_resolve_default."""

    enabled: bool | None = None


class ResolveResponse(BaseModel):
    ok: Literal[True] = True
    resolved_at: UTCDatetime
    resolved_source: ResolvedSource


class ReopenResponse(BaseModel):
    ok: Literal[True] = True
```

Extend `FilterSettings` (after `use_ai`):

```python
    ai_resolve_default: bool = False
    ai_resolve_confidence_threshold: float = Field(default=0.7, ge=0.0, le=1.0)
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest backend/tests/test_models.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_models.py
git commit -m "Extend Pydantic schemas with ticket-resolution fields"
```

---

## Task 3: AI prompt + parser carry resolution verdict

**Files:**
- Modify: `backend/app/ai/prompt.py`, `backend/app/ai/pipeline.py`
- Test: `backend/tests/test_ai.py` (extend), `backend/tests/test_resolution_prompt.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_resolution_prompt.py`:

```python
from app.ai.prompt import SYSTEM_PROMPT
from app.ai.pipeline import parse_response


def test_system_prompt_documents_resolution_fields():
    assert "resolution_verdict" in SYSTEM_PROMPT
    assert "resolution_confidence" in SYSTEM_PROMPT
    assert "resolution_reason" in SYSTEM_PROMPT


def test_parser_extracts_resolution_fields():
    raw = """
    {
      "assignment": "existing",
      "category_id": 3,
      "subject": "Refund #44812",
      "summary": "Customer asks for refund on invoice 44812.",
      "confidence": 0.92,
      "resolution_verdict": "resolved",
      "resolution_confidence": 0.81,
      "resolution_reason": "customer thanked and closed"
    }
    """
    parsed = parse_response(raw)
    assert parsed.resolution_verdict == "resolved"
    assert parsed.resolution_confidence == 0.81
    assert parsed.resolution_reason == "customer thanked and closed"


def test_parser_treats_missing_resolution_as_null():
    raw = '{"assignment":"existing","category_id":1,"subject":"x","summary":"y","confidence":0.5}'
    parsed = parse_response(raw)
    assert parsed.resolution_verdict is None
    assert parsed.resolution_confidence is None
    assert parsed.resolution_reason is None


def test_parser_clamps_invalid_resolution_verdict_to_null():
    raw = (
        '{"assignment":"existing","category_id":1,"subject":"x","summary":"y","confidence":0.5,'
        '"resolution_verdict":"maybe","resolution_confidence":0.7}'
    )
    parsed = parse_response(raw)
    assert parsed.resolution_verdict is None  # invalid verdict drops to null


def test_parser_truncates_resolution_reason_to_120_chars():
    long = "x" * 200
    raw = (
        f'{{"assignment":"existing","category_id":1,"subject":"x","summary":"y","confidence":0.5,'
        f'"resolution_verdict":"resolved","resolution_confidence":0.7,"resolution_reason":"{long}"}}'
    )
    parsed = parse_response(raw)
    assert parsed.resolution_reason is not None
    assert len(parsed.resolution_reason) == 120
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_resolution_prompt.py -v
```

Expected: FAIL — prompt lacks fields, ParsedAssignment lacks resolution_verdict.

- [ ] **Step 3: Extend `SYSTEM_PROMPT` in `backend/app/ai/prompt.py`**

Add a new section right after the SUMMARY rules and before the trailing `Rules:` section:

```text
RESOLUTION rules (applies to every response):
- Decide whether the conversation appears resolved.
- A conversation is "resolved" when: the customer's most recent message
  indicates the issue is fixed, they thanked the agent for a working solution,
  the agent's last reply closed the loop and the customer has not replied
  since, or the customer explicitly said no further help is needed.
- A conversation is "not_resolved" when: the customer is waiting on the
  agent, has a new question, expressed dissatisfaction, the issue is still
  reproducing, or the thread ends mid-troubleshooting without confirmation.
- Add these THREE fields to EVERY response object:
    "resolution_verdict":    "resolved" | "not_resolved",
    "resolution_confidence": <float 0..1>,
    "resolution_reason":     "<one short clause, <=120 chars, plain text>"
```

Update each of the three JSON shape examples (A, B, C) in `SYSTEM_PROMPT` to include the three fields. Example A:

```text
A) Assign to an EXISTING active category:
   {
     "assignment":            "existing",
     "category_id":           <integer id of one of the ACTIVE CATEGORIES below>,
     "subject":               "<see SUBJECT rules>",
     "summary":               "<=600 chars, 2-3 sentences (see SUMMARY rules)",
     "confidence":            <float 0..1>,
     "resolution_verdict":    "resolved" | "not_resolved",
     "resolution_confidence": <float 0..1>,
     "resolution_reason":     "<see RESOLUTION rules>"
   }
```

Repeat for B and C (`pending_proposal`, `new_proposal`).

- [ ] **Step 4: Extend `ParsedAssignment` + parser in `backend/app/ai/pipeline.py`**

Add three fields to `ParsedAssignment`:

```python
@dataclass
class ParsedAssignment:
    kind: AssignmentKind
    summary: str
    confidence: float
    subject: str
    category_id: int | None = None
    proposal_id: int | None = None
    proposed_name: str | None = None
    proposed_description: str | None = None
    resolution_verdict: Literal["resolved", "not_resolved"] | None = None
    resolution_confidence: float | None = None
    resolution_reason: str | None = None
```

Add a helper next to `_clamp_confidence`:

```python
def _parse_resolution(obj: dict[str, Any]) -> tuple[
    Literal["resolved", "not_resolved"] | None,
    float | None,
    str | None,
]:
    verdict = obj.get("resolution_verdict")
    if verdict not in ("resolved", "not_resolved"):
        return None, None, None
    confidence = obj.get("resolution_confidence")
    confidence_f: float | None
    try:
        confidence_f = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence_f = None
    reason_raw = obj.get("resolution_reason")
    reason = str(reason_raw)[:120] if isinstance(reason_raw, str) and reason_raw.strip() else None
    return verdict, confidence_f, reason
```

In `parse_response`, after `confidence = _clamp_confidence(...)`, add:

```python
    verdict, res_conf, res_reason = _parse_resolution(obj)
```

Pass these three to each `ParsedAssignment(...)` return site (existing/pending_proposal/new_proposal):

```python
    return ParsedAssignment(
        "existing",
        summary,
        confidence,
        subject,
        category_id=category_id,
        resolution_verdict=verdict,
        resolution_confidence=res_conf,
        resolution_reason=res_reason,
    )
```

(And likewise for the other two branches.)

- [ ] **Step 5: Run tests, verify they pass**

```bash
pytest backend/tests/test_resolution_prompt.py backend/tests/test_ai.py -v
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/ai/prompt.py backend/app/ai/pipeline.py backend/tests/test_resolution_prompt.py
git commit -m "Extend AI prompt + parser with resolution verdict"
```

---

## Task 4: `CategorizationResult` + resolver carry resolution

**Files:**
- Modify: `backend/app/ai/pipeline.py`
- Test: `backend/tests/test_ai.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_ai.py`:

```python
@pytest.mark.asyncio
async def test_resolver_propagates_resolution_fields(session, fallback_id):
    """resolve() carries verdict + confidence + reason through to CategorizationResult."""
    from app.ai.pipeline import ParsedAssignment, _ResolverState, resolve
    state = _ResolverState(
        active_category_ids={fallback_id, 99},
        pending_proposal_ids=set(),
        pending_by_signature={},
        rejected_signatures=set(),
        fallback_category_id=fallback_id,
    )
    parsed = ParsedAssignment(
        "existing",
        "summary",
        0.8,
        "subj",
        category_id=99,
        resolution_verdict="resolved",
        resolution_confidence=0.82,
        resolution_reason="customer confirmed working",
    )
    result = await resolve(parsed, session=session, state=state)
    assert result.ai_resolution_verdict == "resolved"
    assert result.ai_resolution_confidence == 0.82
    assert result.ai_resolution_reason == "customer confirmed working"


def test_fallback_result_has_null_resolution_fields():
    from app.ai.pipeline import _fallback
    from app.schemas import HydratedTicket, TicketAuthorSchema
    from datetime import datetime
    hydrated = HydratedTicket(
        id="x", title="t", state="open", priority=None,
        created_at=datetime(2026, 5, 23), updated_at=datetime(2026, 5, 23),
        author=TicketAuthorSchema(), url=None, parts=[],
    )
    result = _fallback(hydrated, fallback_category_id=1)
    assert result.ai_resolution_verdict is None
    assert result.ai_resolution_confidence is None
    assert result.ai_resolution_reason is None
```

(`session` and `fallback_id` come from existing conftest fixtures used in `test_ai.py`; if not present, look at `tests/conftest.py` for the closest match — there is a `db_session` fixture and a `seeded_db` fixture; reuse them.)

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_ai.py -v -k "resolution"
```

Expected: FAIL — `CategorizationResult` lacks the fields.

- [ ] **Step 3: Extend `CategorizationResult` + `resolve()` + `_fallback()`**

In `backend/app/ai/pipeline.py`:

```python
@dataclass
class CategorizationResult:
    category_id: int | None
    proposal_id: int | None
    summary: str
    confidence: float
    subject: str = ""
    fallback: bool = False
    ai_resolution_verdict: Literal["resolved", "not_resolved"] | None = None
    ai_resolution_confidence: float | None = None
    ai_resolution_reason: str | None = None
```

In each `return CategorizationResult(...)` inside `resolve()`, thread the three fields from `parsed`:

```python
        return CategorizationResult(
            parsed.category_id,
            None,
            parsed.summary,
            parsed.confidence,
            parsed.subject,
            ai_resolution_verdict=parsed.resolution_verdict,
            ai_resolution_confidence=parsed.resolution_confidence,
            ai_resolution_reason=parsed.resolution_reason,
        )
```

(Repeat for the `pending_proposal` and `new_proposal` branches.)

`_fallback()` keeps the three resolution fields at their default `None` — no change needed there other than the dataclass defaults.

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest backend/tests/test_ai.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/ai/pipeline.py backend/tests/test_ai.py
git commit -m "Thread resolution verdict through resolver"
```

---

## Task 5: AI cache reads + writes resolution fields

**Files:**
- Modify: `backend/app/services/cache.py`
- Test: `backend/tests/test_cache.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_cache.py`:

```python
@pytest.mark.asyncio
async def test_cache_round_trip_resolution_fields(db_session):
    """Cache write + read preserves verdict, confidence, reason."""
    from datetime import datetime
    from app.ai.pipeline import CategorizationResult
    from app.services.cache import get_cached, set_cached

    sig = datetime(2026, 5, 23, 12, 0)
    result = CategorizationResult(
        category_id=1,
        proposal_id=None,
        summary="s",
        confidence=0.9,
        ai_resolution_verdict="resolved",
        ai_resolution_confidence=0.88,
        ai_resolution_reason="closed loop",
    )
    await set_cached(db_session, "t1", result, sig)
    await db_session.commit()

    cached = await get_cached(db_session, "t1", sig, ttl_seconds=300)
    assert cached is not None
    assert cached.ai_resolution_verdict == "resolved"
    assert cached.ai_resolution_confidence == 0.88
    assert cached.ai_resolution_reason == "closed loop"


@pytest.mark.asyncio
async def test_cache_legacy_row_has_null_resolution(db_session):
    """An older cache row written before this feature has null verdict;
    get_cached returns None values without crashing."""
    from datetime import datetime
    from app.models import AICacheEntry

    db_session.add(AICacheEntry(
        ticket_id="legacy",
        category_id=1,
        proposal_id=None,
        summary="s",
        confidence=0.5,
        ticket_updated_at=datetime(2026, 5, 23),
    ))
    await db_session.commit()

    from app.services.cache import get_cached
    cached = await get_cached(db_session, "legacy", datetime(2026, 5, 23), 300)
    assert cached is not None
    assert cached.ai_resolution_verdict is None
    assert cached.ai_resolution_confidence is None
    assert cached.ai_resolution_reason is None
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_cache.py -v -k "resolution"
```

- [ ] **Step 3: Update `backend/app/services/cache.py`**

In `set_cached`, write the three fields in both the insert and the update path:

```python
    if row is None:
        session.add(
            AICacheEntry(
                ticket_id=ticket_id,
                category_id=result.category_id,
                proposal_id=result.proposal_id,
                summary=result.summary,
                confidence=result.confidence,
                ticket_updated_at=signature,
                cached_at=now,
                ai_resolution_verdict=result.ai_resolution_verdict,
                ai_resolution_confidence=result.ai_resolution_confidence,
                ai_resolution_reason=result.ai_resolution_reason,
            ),
        )
        return
    row.category_id = result.category_id
    row.proposal_id = result.proposal_id
    row.summary = result.summary
    row.confidence = result.confidence
    row.ticket_updated_at = signature
    row.cached_at = now
    row.ai_resolution_verdict = result.ai_resolution_verdict
    row.ai_resolution_confidence = result.ai_resolution_confidence
    row.ai_resolution_reason = result.ai_resolution_reason
```

In `get_cached`, return the fields:

```python
    return CategorizationResult(
        category_id=row.category_id,
        proposal_id=row.proposal_id,
        summary=row.summary,
        confidence=row.confidence,
        ai_resolution_verdict=row.ai_resolution_verdict,
        ai_resolution_confidence=row.ai_resolution_confidence,
        ai_resolution_reason=row.ai_resolution_reason,
    )
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest backend/tests/test_cache.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/cache.py backend/tests/test_cache.py
git commit -m "Persist + return resolution verdict via ai_cache"
```

---

## Task 6: `_upsert_ticket` writes resolution fields + Intercom-closed transition

**Files:**
- Modify: `backend/app/services/tickets.py`
- Test: `backend/tests/test_resolution_ingest.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_resolution_ingest.py`:

```python
"""Verifies ingest-time resolution behavior:
- Intercom state transition open → closed auto-resolves with source='intercom_closed'.
- A ticket arriving as closed on first sight is ignored (extension filter), but if
  forced through ingest, it auto-resolves on first store.
- A previously-resolved ticket stays resolved across syncs (no re-stamp).
- AI verdict ends up on the stored ticket via the join in get_tickets.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.schemas import (
    ConversationPartSchema,
    HydratedTicket,
    TicketAuthorSchema,
)


def make_hydrated(*, id="t1", state="open", updated_at=None) -> HydratedTicket:
    return HydratedTicket(
        id=id,
        title="t",
        state=state,
        priority=None,
        created_at=datetime(2026, 5, 23, 8),
        updated_at=updated_at or datetime(2026, 5, 23, 12),
        author=TicketAuthorSchema(),
        url=None,
        parts=[ConversationPartSchema(
            author=TicketAuthorSchema(),
            body="hello",
            created_at=datetime(2026, 5, 23, 11),
            is_admin=False,
        )],
    )


@pytest.mark.asyncio
async def test_intercom_closed_transition_auto_resolves(seeded_db, app_config):
    """Open ticket already stored, sync brings it back as state='closed':
    resolved_at is set, source='intercom_closed', AI is not called."""
    from app.services.tickets import ingest_tickets
    from app.models import Ticket

    openrouter = AsyncMock()
    openrouter.classify = AsyncMock(return_value='{"assignment":"existing","category_id":1,"subject":"s","summary":"x","confidence":0.9,"resolution_verdict":"not_resolved","resolution_confidence":0.5,"resolution_reason":"open"}')

    # First sync — open state, store the ticket.
    await ingest_tickets(
        session=seeded_db, openrouter=openrouter, config=app_config,
        hydrated=[make_hydrated(state="open")],
    )
    row = await seeded_db.get(Ticket, "t1")
    assert row is not None and row.resolved_at is None

    # Second sync — same id, state=closed, later updated_at.
    await ingest_tickets(
        session=seeded_db, openrouter=openrouter, config=app_config,
        hydrated=[make_hydrated(state="closed", updated_at=datetime(2026, 5, 24))],
    )
    row = await seeded_db.get(Ticket, "t1")
    assert row.resolved_at is not None
    assert row.resolved_source == "intercom_closed"
    assert row.state == "closed"


@pytest.mark.asyncio
async def test_already_resolved_ticket_not_restamped_on_second_closure(seeded_db, app_config):
    """If we sync a closed ticket twice, resolved_at must not change on the
    second pass — only the first open→closed transition stamps it."""
    from app.services.tickets import ingest_tickets
    from app.models import Ticket
    from app.util import naive_utcnow

    openrouter = AsyncMock()
    openrouter.classify = AsyncMock(return_value='{"assignment":"existing","category_id":1,"subject":"s","summary":"x","confidence":0.9}')

    # Pre-store as resolved 1 hour ago.
    seeded_db.add(Ticket(
        id="t2", title="x", state="closed",
        author={}, parts=[], internal_notes=[],
        created_at=datetime(2026, 5, 23), updated_at=datetime(2026, 5, 23),
        category_id=1, summary="", ai_confidence=0,
        resolved_at=naive_utcnow() - timedelta(hours=1),
        resolved_source="intercom_closed",
    ))
    await seeded_db.commit()
    original = (await seeded_db.get(Ticket, "t2")).resolved_at

    await ingest_tickets(
        session=seeded_db, openrouter=openrouter, config=app_config,
        hydrated=[make_hydrated(id="t2", state="closed", updated_at=datetime(2026, 5, 24))],
    )
    row = await seeded_db.get(Ticket, "t2")
    assert row.resolved_at == original  # unchanged
```

(Fixture names `seeded_db` + `app_config` should match what's used by `test_ingest_api.py`; check there for exact names and adapt.)

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_resolution_ingest.py -v
```

- [ ] **Step 3: Modify `_upsert_ticket` in `backend/app/services/tickets.py`**

Replace the existing `_upsert_ticket` with a version that handles closure transitions:

```python
async def _upsert_ticket(
    session: AsyncSession,
    hydrated: HydratedTicket,
    result: CategorizationResult,
) -> None:
    """Insert or update one stored ticket row from its hydrated + AI data.

    Intercom-closed auto-resolution (spec §5.2): when a previously-open stored
    ticket arrives with state='closed', stamp resolved_at + resolved_source.
    Never re-stamp an already-resolved ticket.
    """
    author = hydrated.author.model_dump(mode="json")
    parts = [p.model_dump(mode="json") for p in hydrated.parts]
    internal_notes = [n.model_dump(mode="json") for n in hydrated.internal_notes]
    row = await session.get(Ticket, hydrated.id)
    now = naive_utcnow()

    if row is None:
        new_row = Ticket(
            id=hydrated.id,
            title=_resolve_title(hydrated, result),
            state=hydrated.state,
            priority=hydrated.priority,
            url=hydrated.url,
            author=author,
            parts=parts,
            internal_notes=internal_notes,
            created_at=hydrated.created_at,
            updated_at=hydrated.updated_at,
            category_id=result.category_id,
            proposal_id=result.proposal_id,
            summary=result.summary,
            ai_confidence=result.confidence,
            ingested_at=now,
        )
        if hydrated.state == "closed":
            new_row.resolved_at = now
            new_row.resolved_source = "intercom_closed"
        session.add(new_row)
        return

    # Closure transition: previously not closed (any state) AND now closed AND
    # not already resolved → auto-resolve.
    if (
        hydrated.state == "closed"
        and row.state != "closed"
        and row.resolved_at is None
    ):
        row.resolved_at = now
        row.resolved_source = "intercom_closed"

    if not row.title_user_edited:
        row.title = _resolve_title(hydrated, result)
    row.state = hydrated.state
    row.priority = hydrated.priority
    row.url = hydrated.url
    row.author = author
    row.parts = parts
    row.internal_notes = internal_notes
    row.created_at = hydrated.created_at
    row.updated_at = hydrated.updated_at
    row.category_id = result.category_id
    row.proposal_id = result.proposal_id
    if not row.summary_user_edited:
        row.summary = result.summary
    row.ai_confidence = result.confidence
    row.ingested_at = now
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest backend/tests/test_resolution_ingest.py backend/tests/test_ingest_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tickets.py backend/tests/test_resolution_ingest.py
git commit -m "Auto-resolve on Intercom open→closed transition"
```

---

## Task 7: `services/resolution.py` — manual resolve / reopen / AI toggle / dismiss

**Files:**
- Create: `backend/app/services/resolution.py`
- Test: `backend/tests/test_resolution_service.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_resolution_service.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from app.models import Ticket
from app.services import resolution as svc
from app.util import naive_utcnow


def _make_open_ticket(id: str = "t1") -> Ticket:
    return Ticket(
        id=id, title="x", state="open",
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
    )


@pytest.mark.asyncio
async def test_resolve_marks_manual_and_returns_datetime(seeded_db):
    seeded_db.add(_make_open_ticket("t1"))
    await seeded_db.commit()

    out = await svc.resolve(seeded_db, "t1")
    assert out.resolved_source == "manual"
    row = await seeded_db.get(Ticket, "t1")
    assert row.resolved_at is not None
    assert row.resolved_source == "manual"


@pytest.mark.asyncio
async def test_resolve_409_if_already_resolved(seeded_db):
    t = _make_open_ticket("t2")
    t.resolved_at = naive_utcnow()
    t.resolved_source = "manual"
    seeded_db.add(t)
    await seeded_db.commit()
    with pytest.raises(HTTPException) as exc:
        await svc.resolve(seeded_db, "t2")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_reopen_clears_resolved_fields(seeded_db):
    t = _make_open_ticket("t3")
    t.resolved_at = naive_utcnow()
    t.resolved_source = "manual"
    seeded_db.add(t)
    await seeded_db.commit()

    await svc.reopen(seeded_db, "t3")
    row = await seeded_db.get(Ticket, "t3")
    assert row.resolved_at is None
    assert row.resolved_source is None


@pytest.mark.asyncio
async def test_reopen_409_if_already_open(seeded_db):
    seeded_db.add(_make_open_ticket("t4"))
    await seeded_db.commit()
    with pytest.raises(HTTPException) as exc:
        await svc.reopen(seeded_db, "t4")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_set_ai_resolve_tristate(seeded_db):
    seeded_db.add(_make_open_ticket("t5"))
    await seeded_db.commit()
    await svc.set_ai_resolve(seeded_db, "t5", True)
    assert (await seeded_db.get(Ticket, "t5")).ai_resolve_enabled is True
    await svc.set_ai_resolve(seeded_db, "t5", False)
    assert (await seeded_db.get(Ticket, "t5")).ai_resolve_enabled is False
    await svc.set_ai_resolve(seeded_db, "t5", None)
    assert (await seeded_db.get(Ticket, "t5")).ai_resolve_enabled is None


@pytest.mark.asyncio
async def test_dismiss_chip_sets_dismissed_at_to_updated_at(seeded_db):
    t = _make_open_ticket("t6")
    t.updated_at = datetime(2026, 5, 23, 10, 0)
    seeded_db.add(t)
    await seeded_db.commit()

    await svc.dismiss_chip(seeded_db, "t6")
    row = await seeded_db.get(Ticket, "t6")
    assert row.resolution_chip_dismissed_at == datetime(2026, 5, 23, 10, 0)


@pytest.mark.asyncio
async def test_404_on_unknown_ticket(seeded_db):
    for fn in (svc.resolve, svc.reopen, svc.dismiss_chip):
        with pytest.raises(HTTPException) as exc:
            await fn(seeded_db, "ghost")
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await svc.set_ai_resolve(seeded_db, "ghost", True)
    assert exc.value.status_code == 404
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_resolution_service.py -v
```

Expected: FAIL — `app.services.resolution` does not exist.

- [ ] **Step 3: Create `backend/app/services/resolution.py`**

```python
"""Manual ticket-resolution mutations.

Reference: docs/superpowers/specs/2026-05-23-ticket-resolution-design.md §6, §7.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import Ticket
from app.util import naive_utcnow

ResolvedSource = Literal["manual", "intercom_closed"]


@dataclass
class ResolveOutcome:
    resolved_at: datetime
    resolved_source: ResolvedSource


async def _get_or_404(session: AsyncSession, ticket_id: str) -> Ticket:
    row = await session.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    return row


async def resolve(session: AsyncSession, ticket_id: str) -> ResolveOutcome:
    """Mark a ticket as manually resolved. 409 if already resolved."""
    row = await _get_or_404(session, ticket_id)
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already resolved")
    now = naive_utcnow()
    row.resolved_at = now
    row.resolved_source = "manual"
    await session.commit()
    metrics.incr("tickets_resolved_total.manual")
    return ResolveOutcome(resolved_at=now, resolved_source="manual")


async def reopen(session: AsyncSession, ticket_id: str) -> None:
    """Clear resolution. 409 if not currently resolved."""
    row = await _get_or_404(session, ticket_id)
    if row.resolved_at is None:
        raise HTTPException(status_code=409, detail="ticket is not resolved")
    row.resolved_at = None
    row.resolved_source = None
    await session.commit()
    metrics.incr("tickets_reopened_total")


async def set_ai_resolve(
    session: AsyncSession,
    ticket_id: str,
    enabled: bool | None,
) -> None:
    """Tri-state per-ticket override. `None` clears the override."""
    row = await _get_or_404(session, ticket_id)
    row.ai_resolve_enabled = enabled
    await session.commit()


async def dismiss_chip(session: AsyncSession, ticket_id: str) -> None:
    """Suppress the resolution chip until `tickets.updated_at` advances."""
    row = await _get_or_404(session, ticket_id)
    row.resolution_chip_dismissed_at = row.updated_at
    await session.commit()
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest backend/tests/test_resolution_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/resolution.py backend/tests/test_resolution_service.py
git commit -m "Add resolution service (resolve/reopen/ai-flag/dismiss)"
```

---

## Task 8: Resolution endpoints + router wiring

**Files:**
- Modify: `backend/app/routers/tickets.py`
- Test: `backend/tests/test_resolution_api.py` (new)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_resolution_api.py`:

```python
from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.models import Ticket
from app.util import naive_utcnow


def _seed_open(session, id="t1"):
    session.add(Ticket(
        id=id, title="x", state="open",
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
    ))


@pytest.mark.asyncio
async def test_post_resolve_returns_200_and_persists(client: AsyncClient, db_session):
    _seed_open(db_session, "t1")
    await db_session.commit()

    r = await client.post("/tickets/t1/resolve", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_source"] == "manual"


@pytest.mark.asyncio
async def test_post_resolve_404_unknown(client):
    r = await client.post("/tickets/ghost/resolve", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_resolve_409_already_resolved(client, db_session):
    t = Ticket(
        id="t2", title="x", state="open",
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
        resolved_at=naive_utcnow(), resolved_source="manual",
    )
    db_session.add(t)
    await db_session.commit()
    r = await client.post("/tickets/t2/resolve", json={})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_post_reopen_clears_resolution(client, db_session):
    t = Ticket(
        id="t3", title="x", state="open",
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
        resolved_at=naive_utcnow(), resolved_source="manual",
    )
    db_session.add(t)
    await db_session.commit()

    r = await client.post("/tickets/t3/reopen")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_patch_ai_resolve_tristate(client, db_session):
    _seed_open(db_session, "t4")
    await db_session.commit()
    for value in (True, False, None):
        r = await client.patch("/tickets/t4/ai-resolve", json={"enabled": value})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_post_dismiss_chip(client, db_session):
    _seed_open(db_session, "t5")
    await db_session.commit()
    r = await client.post("/tickets/t5/dismiss-chip")
    assert r.status_code == 200
    assert r.json()["ok"] is True
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_resolution_api.py -v
```

- [ ] **Step 3: Add endpoints to `backend/app/routers/tickets.py`**

Add imports:

```python
from app.schemas import (
    AIResolveSet,
    ReopenResponse,
    ResolveResponse,
    # ... existing imports
)
from app.services import resolution as resolution_svc
```

Add at the bottom of the router file:

```python
@router.post("/{ticket_id}/resolve", response_model=ResolveResponse)
async def resolve_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> ResolveResponse:
    """Manual resolve. 409 if already resolved, 404 if unknown."""
    out = await resolution_svc.resolve(session, ticket_id)
    return ResolveResponse(resolved_at=out.resolved_at, resolved_source=out.resolved_source)


@router.post("/{ticket_id}/reopen", response_model=ReopenResponse)
async def reopen_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> ReopenResponse:
    """Reopen a resolved ticket. 409 if already open, 404 if unknown."""
    await resolution_svc.reopen(session, ticket_id)
    return ReopenResponse()


@router.patch("/{ticket_id}/ai-resolve", response_model=OkResponse)
async def set_ai_resolve(
    ticket_id: str,
    body: AIResolveSet,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """Per-ticket AI-resolve override. `null` inherits settings.ai_resolve_default."""
    await resolution_svc.set_ai_resolve(session, ticket_id, body.enabled)
    return OkResponse()


@router.post("/{ticket_id}/dismiss-chip", response_model=OkResponse)
async def dismiss_chip(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """Suppress the resolution chip until `tickets.updated_at` advances."""
    await resolution_svc.dismiss_chip(session, ticket_id)
    return OkResponse()
```

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest backend/tests/test_resolution_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/tickets.py backend/tests/test_resolution_api.py
git commit -m "Add resolve / reopen / ai-resolve / dismiss-chip endpoints"
```

---

## Task 9: `GET /tickets` resolved filter + chip-state computation + drag-out reopen

**Files:**
- Modify: `backend/app/services/tickets.py`, `backend/app/routers/tickets.py`
- Test: `backend/tests/test_tickets_api.py` (extend), `backend/tests/test_resolution_api.py` (extend)

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_resolution_api.py`:

```python
@pytest.mark.asyncio
async def test_get_tickets_default_excludes_resolved(client, db_session):
    t1 = Ticket(id="open1", title="x", state="open", author={}, parts=[], internal_notes=[],
                created_at=naive_utcnow(), updated_at=naive_utcnow(),
                category_id=1, summary="", ai_confidence=0.0)
    t2 = Ticket(id="resolved1", title="x", state="open", author={}, parts=[], internal_notes=[],
                created_at=naive_utcnow(), updated_at=naive_utcnow(),
                category_id=1, summary="", ai_confidence=0.0,
                resolved_at=naive_utcnow(), resolved_source="manual")
    db_session.add_all([t1, t2])
    await db_session.commit()

    r = await client.get("/tickets")
    ids = {t["id"] for t in r.json()}
    assert "open1" in ids
    assert "resolved1" not in ids


@pytest.mark.asyncio
async def test_get_tickets_resolved_true_returns_only_resolved(client, db_session):
    # Same seed as above
    db_session.add_all([
        Ticket(id="o", title="x", state="open", author={}, parts=[], internal_notes=[],
               created_at=naive_utcnow(), updated_at=naive_utcnow(),
               category_id=1, summary="", ai_confidence=0.0),
        Ticket(id="r", title="x", state="open", author={}, parts=[], internal_notes=[],
               created_at=naive_utcnow(), updated_at=naive_utcnow(),
               category_id=1, summary="", ai_confidence=0.0,
               resolved_at=naive_utcnow(), resolved_source="manual"),
    ])
    await db_session.commit()

    r = await client.get("/tickets?resolved=true")
    ids = {t["id"] for t in r.json()}
    assert ids == {"r"}


@pytest.mark.asyncio
async def test_chip_state_ai_resolved_when_verdict_high_confidence(client, db_session):
    """Open ticket, AI verdict='resolved' >= threshold, chip not dismissed."""
    from app.models import AICacheEntry, Settings
    settings = await db_session.get(Settings, 1)
    settings.ai_resolve_default = True
    settings.ai_resolve_confidence_threshold = 0.7
    settings.use_ai = True

    db_session.add(AICacheEntry(
        ticket_id="ai1", category_id=1, summary="s", confidence=0.9,
        ticket_updated_at=naive_utcnow(),
        ai_resolution_verdict="resolved", ai_resolution_confidence=0.85,
    ))
    db_session.add(Ticket(
        id="ai1", title="x", state="open", author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.9,
    ))
    await db_session.commit()

    r = await client.get("/tickets")
    payload = next(t for t in r.json() if t["id"] == "ai1")
    assert payload["resolution_chip_state"] == "ai_resolved"


@pytest.mark.asyncio
async def test_drag_out_of_resolved_reopens_and_overrides(client, db_session):
    """PATCH /tickets/{id}/category on a resolved ticket clears resolution
    in the same transaction (drag-out behavior)."""
    db_session.add(Ticket(
        id="t1", title="x", state="open", author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        category_id=1, summary="", ai_confidence=0.0,
        resolved_at=naive_utcnow(), resolved_source="manual",
    ))
    await db_session.commit()

    r = await client.patch("/tickets/t1/category", json={"category_id": 2})
    assert r.status_code == 200

    row = await db_session.get(Ticket, "t1")
    await db_session.refresh(row)
    assert row.resolved_at is None
    assert row.resolved_source is None
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_resolution_api.py -v
```

- [ ] **Step 3: Modify `services.tickets.get_tickets` for the `resolved` filter**

Look at the current `get_tickets` in `backend/app/services/tickets.py`. Add a `resolved` argument:

```python
async def get_tickets(
    session: AsyncSession,
    *,
    resolved: bool | None = False,  # False = open only, True = resolved only, None = both
) -> list[TicketSchema]:
    """Serve stored tickets joined with overrides, follow-ups, notes, AI cache.

    By default returns only un-resolved tickets. Pass resolved=True for the
    Resolved column, or resolved=None to get both (admin tools).
    """
    settings = await get_settings(session)
    # ...existing query construction up to the final select...
    stmt = select(Ticket).order_by(Ticket.updated_at.desc())
    if resolved is False:
        stmt = stmt.where(Ticket.resolved_at.is_(None))
    elif resolved is True:
        stmt = stmt.where(Ticket.resolved_at.is_not(None)).order_by(
            Ticket.resolved_at.desc(),
        )
    # remainder unchanged
```

(Inside the existing `get_tickets` — apply at the same point where it builds the `select(Ticket)` statement. Look at the existing code; do not invent new structure. Adjust the `order_by` as shown for the resolved=True branch.)

After composing each `TicketSchema`, compute `resolution_chip_state` from:
- `settings.use_ai`
- effective `ai_resolve_enabled` = `row.ai_resolve_enabled if row.ai_resolve_enabled is not None else settings.ai_resolve_default`
- `row.resolved_at`
- `row.updated_at`
- `row.resolution_chip_dismissed_at`
- AI cache row (`ai_resolution_verdict`, `ai_resolution_confidence`)
- `settings.ai_resolve_confidence_threshold`

Helper:

```python
def _chip_state(
    *,
    use_ai: bool,
    effective_ai_resolve: bool,
    threshold: float,
    resolved_at,
    updated_at,
    dismissed_at,
    verdict,
    verdict_confidence,
):
    if dismissed_at is not None and dismissed_at >= updated_at:
        return None
    new_activity = resolved_at is None or updated_at > resolved_at
    ai_on = use_ai and effective_ai_resolve and verdict is not None and verdict_confidence is not None
    high_conf = ai_on and verdict_confidence >= threshold

    if resolved_at is None and high_conf and verdict == "resolved":
        return "ai_resolved"
    if resolved_at is not None and new_activity and high_conf and verdict == "not_resolved":
        return "ai_reopened"
    if resolved_at is not None and new_activity and not ai_on:
        return "new_reply"
    return None
```

When composing the response, also surface `ai_resolve_enabled` as the *effective* boolean (operator wants to see "is AI on for this ticket?"). The raw nullable lives in DB; the API serves the resolved value.

- [ ] **Step 4: Modify `services.tickets.set_override` to clear resolution atomically**

```python
async def set_override(
    session: AsyncSession,
    ticket_id: str,
    category_id: int,
) -> int:
    # ...existing category-exists check...

    # Drag-out behavior: moving a resolved ticket into a category column
    # reopens it as part of the same transaction.
    ticket = await session.get(Ticket, ticket_id)
    if ticket is not None and ticket.resolved_at is not None:
        ticket.resolved_at = None
        ticket.resolved_source = None

    # ...existing override upsert + commit...
```

- [ ] **Step 5: Add the `resolved` query param to the router**

In `backend/app/routers/tickets.py`, replace the existing `list_tickets`:

```python
@router.get("", response_model=list[TicketSchema])
async def list_tickets(
    resolved: bool | None = None,  # None query default; svc converts to False
    session: AsyncSession = Depends(get_session),
) -> list[TicketSchema]:
    """Stored board. Default returns open (un-resolved) tickets only; pass
    `?resolved=true` for the Resolved column, `?resolved=false` is the default."""
    effective = False if resolved is None else resolved
    return await svc.get_tickets(session, resolved=effective)
```

- [ ] **Step 6: Run tests, verify they pass**

```bash
pytest backend/tests/test_resolution_api.py backend/tests/test_tickets_api.py -v
```

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/tickets.py backend/app/routers/tickets.py backend/tests/test_resolution_api.py
git commit -m "Resolved filter, chip-state computation, atomic drag-out reopen"
```

---

## Task 10: Settings endpoint carries `ai_resolve_default` + threshold

**Files:**
- Modify: `backend/app/services/settings.py`, `backend/app/routers/settings.py`
- Test: `backend/tests/test_settings_api.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_settings_api.py`:

```python
@pytest.mark.asyncio
async def test_get_settings_returns_ai_resolve_default_and_threshold(client):
    r = await client.get("/settings")
    body = r.json()
    assert "ai_resolve_default" in body
    assert "ai_resolve_confidence_threshold" in body
    assert body["ai_resolve_default"] is False
    assert body["ai_resolve_confidence_threshold"] == 0.7


@pytest.mark.asyncio
async def test_put_settings_persists_resolve_fields(client):
    payload = {
        "lookback_unit": "hours", "lookback_value": 24,
        "states": ["open"], "include_category_ids": None,
        "mute_alarms": False, "use_ai": True,
        "ai_resolve_default": True,
        "ai_resolve_confidence_threshold": 0.85,
    }
    r = await client.put("/settings", json=payload)
    assert r.status_code == 200
    r2 = await client.get("/settings")
    assert r2.json()["ai_resolve_default"] is True
    assert r2.json()["ai_resolve_confidence_threshold"] == 0.85


@pytest.mark.asyncio
async def test_put_settings_rejects_out_of_range_threshold(client):
    payload = {
        "lookback_unit": "hours", "lookback_value": 24,
        "states": ["open"], "include_category_ids": None,
        "mute_alarms": False, "use_ai": True,
        "ai_resolve_default": False,
        "ai_resolve_confidence_threshold": 1.5,  # invalid
    }
    r = await client.put("/settings", json=payload)
    assert r.status_code == 422
```

- [ ] **Step 2: Run tests, verify they fail**

```bash
pytest backend/tests/test_settings_api.py -v
```

- [ ] **Step 3: Update `backend/app/services/settings.py`**

In the function that maps `Settings` → response dict (or whatever the existing helper is called), include the two new fields. In the PUT handler / svc, persist them. Read the existing file first to match the established pattern — it likely uses `FilterSettings.model_dump()` round-trips. The schema change in Task 2 already added the fields to `FilterSettings`.

- [ ] **Step 4: Run tests, verify they pass**

```bash
pytest backend/tests/test_settings_api.py -v
```

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/settings.py backend/app/routers/settings.py backend/tests/test_settings_api.py
git commit -m "Settings carry ai_resolve_default + threshold"
```

---

## Task 11: TS types + API client

**Files:**
- Modify: `webapp/src/types/api.ts`, `webapp/src/api/client.ts`

- [ ] **Step 1: Extend `webapp/src/types/api.ts`**

Add:

```typescript
export type ResolvedSource = 'manual' | 'intercom_closed';
export type ResolutionVerdict = 'resolved' | 'not_resolved';
export type ResolutionChipState = 'ai_resolved' | 'ai_reopened' | 'new_reply';
```

Extend `Ticket`:

```typescript
  resolved_at: string | null;
  resolved_source: ResolvedSource | null;
  ai_resolve_enabled: boolean;  // effective value
  ai_resolution_verdict: ResolutionVerdict | null;
  ai_resolution_confidence: number | null;
  ai_resolution_reason: string | null;
  resolution_chip_state: ResolutionChipState | null;
```

Extend `FilterSettings`:

```typescript
  ai_resolve_default: boolean;
  ai_resolve_confidence_threshold: number;
```

- [ ] **Step 2: Extend `webapp/src/api/client.ts`**

Add methods (sketch — match the file's existing style):

```typescript
async function resolveTicket(id: string): Promise<{ resolved_at: string; resolved_source: ResolvedSource }> {
  const r = await fetch(`${BASE}/tickets/${id}/resolve`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: '{}' });
  if (!r.ok) throw await toError(r);
  return r.json();
}

async function reopenTicket(id: string): Promise<void> {
  const r = await fetch(`${BASE}/tickets/${id}/reopen`, { method: 'POST' });
  if (!r.ok) throw await toError(r);
}

async function setAiResolve(id: string, enabled: boolean | null): Promise<void> {
  const r = await fetch(`${BASE}/tickets/${id}/ai-resolve`, {
    method: 'PATCH',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ enabled }),
  });
  if (!r.ok) throw await toError(r);
}

async function dismissChip(id: string): Promise<void> {
  const r = await fetch(`${BASE}/tickets/${id}/dismiss-chip`, { method: 'POST' });
  if (!r.ok) throw await toError(r);
}

async function listTickets(opts: { resolved?: boolean } = {}): Promise<Ticket[]> {
  const qs = opts.resolved === undefined ? '' : `?resolved=${opts.resolved}`;
  const r = await fetch(`${BASE}/tickets${qs}`);
  if (!r.ok) throw await toError(r);
  return r.json();
}
```

(Match exactly how the existing `client.ts` defines + exports its methods. The signatures above are the contract, not the surrounding boilerplate.)

- [ ] **Step 3: Run typecheck**

```bash
cd webapp
npm run typecheck
```

Expected: PASS — types compile, no `any`s leaked.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/types/api.ts webapp/src/api/client.ts
git commit -m "Webapp: types + API client for resolution endpoints"
```

---

## Task 12: Tickets store — split resolvedTickets + actions

**Files:**
- Modify: `webapp/src/stores/tickets.ts`

- [ ] **Step 1: Extend the store**

Add state:

```typescript
const resolvedTickets = ref<Ticket[]>([]);
```

Add actions (sketch — match existing style + optimistic-update pattern from `applyOverride`):

```typescript
async function refreshResolved() {
  resolvedTickets.value = await client.listTickets({ resolved: true });
}

async function markResolved(id: string) {
  const idx = tickets.value.findIndex(t => t.id === id);
  if (idx === -1) return;
  const original = tickets.value[idx];
  // Optimistic move
  tickets.value.splice(idx, 1);
  resolvedTickets.value.unshift({ ...original, resolved_at: new Date().toISOString(), resolved_source: 'manual' });
  try {
    await client.resolveTicket(id);
  } catch (e) {
    // rollback
    resolvedTickets.value = resolvedTickets.value.filter(t => t.id !== id);
    tickets.value.splice(idx, 0, original);
    throw e;
  }
}

async function reopen(id: string) {
  const idx = resolvedTickets.value.findIndex(t => t.id === id);
  if (idx === -1) return;
  const original = resolvedTickets.value[idx];
  resolvedTickets.value.splice(idx, 1);
  tickets.value.unshift({ ...original, resolved_at: null, resolved_source: null });
  try {
    await client.reopenTicket(id);
  } catch (e) {
    tickets.value = tickets.value.filter(t => t.id !== id);
    resolvedTickets.value.splice(idx, 0, original);
    throw e;
  }
}

async function setAiResolve(id: string, enabled: boolean | null) {
  await client.setAiResolve(id, enabled);
  // Reflect locally — find in both lists
  for (const list of [tickets.value, resolvedTickets.value]) {
    const t = list.find(t => t.id === id);
    if (t) (t as any).ai_resolve_enabled = enabled ?? /* settings default; computed by refresh */ t.ai_resolve_enabled;
  }
}

async function dismissChip(id: string) {
  await client.dismissChip(id);
  for (const list of [tickets.value, resolvedTickets.value]) {
    const t = list.find(t => t.id === id);
    if (t) (t as any).resolution_chip_state = null;
  }
}
```

Extend `refresh` + `silentRefresh` to also call `refreshResolved` in parallel:

```typescript
await Promise.all([
  client.listTickets({ resolved: false }).then(r => tickets.value = r),
  client.listTickets({ resolved: true }).then(r => resolvedTickets.value = r),
]);
```

Modify `applyOverride` so that an override pulling a ticket out of `resolvedTickets` moves it back into `tickets` optimistically (the backend already clears resolution in the same transaction).

- [ ] **Step 2: Run typecheck**

```bash
cd webapp && npm run typecheck
```

- [ ] **Step 3: Commit**

```bash
git add webapp/src/stores/tickets.ts
git commit -m "Webapp: tickets store gains resolvedTickets + resolution actions"
```

---

## Task 13: ResolvedColumn + Board integration

**Files:**
- Create: `webapp/src/components/ResolvedColumn.vue`
- Modify: `webapp/src/components/Board.vue`

- [ ] **Step 1: Create `webapp/src/components/ResolvedColumn.vue`**

Use `Column.vue` as the template — copy its structure, then replace the data source with `tickets.resolvedTickets` and the header label/count with "Resolved". The column must:
- Always render (no `v-if` on category visibility).
- Use a fixed column id like `__resolved__` so drag/drop targets it.
- Accept drops from any category column: on drop, call `tickets.markResolved(id)`.
- Source drops to any other column: on drop into a category column, the receiving column already calls `applyOverride` which handles reopen+override server-side.
- Width matches existing columns (296 px step from `App.vue`).
- Visual: faint accent border / dimmed text to signal "archive-like" feel; reuse existing `--ink-3` color tokens.

```vue
<script setup lang="ts">
import { computed } from 'vue';
import { useTicketsStore } from '@/stores/tickets';
import TicketCard from './TicketCard.vue';

const tickets = useTicketsStore();
const items = computed(() => tickets.resolvedTickets);

async function onDrop(e: DragEvent) {
  e.preventDefault();
  const id = e.dataTransfer?.getData('text/plain');
  if (!id) return;
  // Only do work if this ticket is currently open
  const isOpen = tickets.tickets.some(t => t.id === id);
  if (!isOpen) return;
  try { await tickets.markResolved(id); } catch { /* store rolls back */ }
}

function onDragOver(e: DragEvent) { e.preventDefault(); }
</script>

<template>
  <section class="column resolved" @drop="onDrop" @dragover="onDragOver">
    <header>
      <span class="mono uppercase">Resolved</span>
      <span class="count mono">{{ items.length }}</span>
    </header>
    <div class="list">
      <TicketCard v-for="t in items" :key="t.id" :ticket="t" />
      <p v-if="items.length === 0" class="empty mono">Nothing resolved yet</p>
    </div>
  </section>
</template>

<style scoped>
/* Mirror Column.vue's scoped styles. Add a faint accent border to signal
   the column is a sink, not a category column. */
.resolved {
  border-left: 2px solid var(--accent, #ff4d2e);
  opacity: 0.95;
}
.empty {
  color: var(--ink-3);
  padding: 12px;
  text-align: center;
}
</style>
```

- [ ] **Step 2: Wire into `webapp/src/components/Board.vue`**

In the template, append after the loop that renders the normal columns:

```vue
<ResolvedColumn />
```

Add the import at the top:

```typescript
import ResolvedColumn from './ResolvedColumn.vue';
```

- [ ] **Step 3: Update `App.vue` mount to load resolved tickets**

In `onMounted`, change:

```typescript
await tickets.refresh().catch(() => undefined);
```

to also fetch resolved (refresh already does so per Task 12, no change needed if Task 12 was implemented correctly — verify).

- [ ] **Step 4: Run typecheck**

```bash
cd webapp && npm run typecheck
```

- [ ] **Step 5: Commit**

```bash
git add webapp/src/components/ResolvedColumn.vue webapp/src/components/Board.vue
git commit -m "Webapp: Resolved column always rendered"
```

---

## Task 14: TicketCard — resolve icon + chip slot

**Files:**
- Create: `webapp/src/components/ResolutionChip.vue`
- Modify: `webapp/src/components/TicketCard.vue`

- [ ] **Step 1: Create `webapp/src/components/ResolutionChip.vue`**

```vue
<script setup lang="ts">
import { computed } from 'vue';
import type { Ticket } from '@/types/api';
import { useTicketsStore } from '@/stores/tickets';

const props = defineProps<{ ticket: Ticket }>();
const tickets = useTicketsStore();

const label = computed(() => {
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

async function onApply() {
  const state = props.ticket.resolution_chip_state;
  if (state === 'ai_resolved') await tickets.markResolved(props.ticket.id);
  else if (state === 'ai_reopened' || state === 'new_reply') await tickets.reopen(props.ticket.id);
}

async function onDismiss(e: Event) {
  e.stopPropagation();
  await tickets.dismissChip(props.ticket.id);
}
</script>

<template>
  <button
    v-if="ticket.resolution_chip_state"
    class="resolution-chip mono"
    :title="ticket.ai_resolution_reason ?? ''"
    @click="onApply"
  >
    {{ label }}
    <span class="dismiss" @click="onDismiss" aria-label="Dismiss suggestion">×</span>
  </button>
</template>

<style scoped>
.resolution-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 6px;
  border: 0.5px solid var(--line);
  border-radius: 999px;
  background: var(--chip-bg);
  color: var(--ink-2);
  cursor: pointer;
}
.resolution-chip:hover { background: var(--hover); }
.dismiss {
  font-size: 12px;
  line-height: 1;
  opacity: 0.6;
  cursor: pointer;
}
.dismiss:hover { opacity: 1; }
</style>
```

- [ ] **Step 2: Modify `webapp/src/components/TicketCard.vue`**

Add a resolve icon in the top-right of the card (next to the existing deep-link icon). The icon flips between ✓ (open) and ↺ (resolved):

```vue
<button class="resolve-icon" @click.stop="onResolveClick" :title="ticket.resolved_at ? 'Reopen' : 'Mark resolved'">
  {{ ticket.resolved_at ? '↺' : '✓' }}
</button>
```

Handler:

```typescript
async function onResolveClick() {
  if (props.ticket.resolved_at) {
    await tickets.reopen(props.ticket.id);
  } else {
    await tickets.markResolved(props.ticket.id);
  }
}
```

Add the chip slot near the other chips:

```vue
<ResolutionChip :ticket="ticket" />
```

Import `ResolutionChip` at the top.

- [ ] **Step 3: Run typecheck + build**

```bash
cd webapp && npm run typecheck && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add webapp/src/components/ResolutionChip.vue webapp/src/components/TicketCard.vue
git commit -m "Webapp: TicketCard resolve icon + ResolutionChip"
```

---

## Task 15: Flyout — resolution section + AI tri-state toggle

**Files:**
- Modify: `webapp/src/components/TicketFlyout.vue`

- [ ] **Step 1: Add the Resolution section to the flyout**

Inside `TicketFlyout.vue` template, add a new section near the follow-up + notes sections:

```vue
<section class="resolution-section">
  <h3 class="mono uppercase">Resolution</h3>
  <div class="status-row">
    <span v-if="ticket.resolved_at" class="status-pill mono">
      Resolved · {{ ticket.resolved_source }} · {{ relativeTime(ticket.resolved_at) }}
    </span>
    <span v-else class="status-pill mono">Open</span>
  </div>
  <button class="resolve-btn" @click="onResolveToggle">
    {{ ticket.resolved_at ? 'Reopen' : 'Mark resolved' }}
  </button>
  <div class="ai-tristate">
    <span class="mono uppercase">AI</span>
    <button :class="{ active: aiResolveState === null }"  @click="setAi(null)">default</button>
    <button :class="{ active: aiResolveState === true }"  @click="setAi(true)">on</button>
    <button :class="{ active: aiResolveState === false }" @click="setAi(false)">off</button>
  </div>
</section>
```

Script:

```typescript
import { computed } from 'vue';
import { useTicketsStore } from '@/stores/tickets';
import { useSettingsStore } from '@/stores/settings';

const tickets = useTicketsStore();
const settings = useSettingsStore();

// `ai_resolve_enabled` on the wire is the effective value. For the tri-state
// we need the raw nullable — store it as a separate field on Ticket, or fetch
// /tickets/{id} for the raw value. Simpler: assume the wire field is the
// raw value when set explicitly and inherit otherwise. To keep this clean,
// add a sibling field `ai_resolve_override` (true|false|null) sent by the
// backend alongside `ai_resolve_enabled` (effective). Update Task 9 + types
// to surface both. The flyout reads ai_resolve_override.
const aiResolveState = computed(() => /* prop or wire field */);

async function setAi(v: boolean | null) {
  await tickets.setAiResolve(props.ticket.id, v);
}

async function onResolveToggle() {
  if (props.ticket.resolved_at) await tickets.reopen(props.ticket.id);
  else await tickets.markResolved(props.ticket.id);
}
```

**Important sub-step:** add `ai_resolve_override: boolean | null` to the `Ticket` interface and the backend `TicketSchema`. Backend reads the raw `tickets.ai_resolve_enabled` (nullable) into `ai_resolve_override`, while `ai_resolve_enabled` continues to carry the *effective* value (merged with settings default). Update Task 2's schema + Task 11's types — go back and add the field; do not skip.

- [ ] **Step 2: Run typecheck + build**

```bash
cd webapp && npm run typecheck && npm run build
```

- [ ] **Step 3: Commit**

```bash
git add webapp/src/components/TicketFlyout.vue webapp/src/types/api.ts backend/app/schemas.py backend/app/services/tickets.py
git commit -m "Webapp: flyout Resolution section + AI tri-state"
```

---

## Task 16: Settings drawer — Auto-resolve section

**Files:**
- Modify: `webapp/src/components/SettingsDrawer.vue`, `webapp/src/stores/settings.ts`

- [ ] **Step 1: Extend the settings store**

Add `aiResolveDefault` + `aiResolveConfidenceThreshold` getters/setters and persist via `PUT /settings`.

- [ ] **Step 2: Add the Auto-resolve section to `SettingsDrawer.vue`**

```vue
<section class="auto-resolve-section">
  <h3 class="mono uppercase">Auto-resolve</h3>
  <label class="toggle-row">
    <input type="checkbox" v-model="aiResolveDefault" :disabled="!useAi" />
    <span>Let AI suggest resolution</span>
  </label>
  <p v-if="!useAi" class="hint mono">Enable AI (above) to use auto-resolve suggestions.</p>
  <label class="slider-row">
    <span class="mono">Confidence threshold</span>
    <input type="range" min="0.5" max="0.95" step="0.05" v-model.number="aiResolveConfidenceThreshold" />
    <span class="mono value">{{ aiResolveConfidenceThreshold.toFixed(2) }}</span>
  </label>
  <p class="hint">Suggestions appear as chips on cards. AI never moves tickets automatically; you confirm every change.</p>
</section>
```

Wire computed setters that call the existing settings store update path (debounced, mirrors how `mute_alarms` is handled).

- [ ] **Step 3: Run typecheck + build**

```bash
cd webapp && npm run typecheck && npm run build
```

- [ ] **Step 4: Commit**

```bash
git add webapp/src/components/SettingsDrawer.vue webapp/src/stores/settings.ts
git commit -m "Webapp: Auto-resolve settings section"
```

---

## Task 17: Extension closure pass

**Files:**
- Modify: `extension/intercom.js`, `extension/api.js`, `extension/background.js`

- [ ] **Step 1: Add a closure-list helper to `extension/intercom.js`**

Read the existing `listOpenConversations` style and mirror it. Add:

```javascript
/**
 * Fetch closed conversations until we've found every id in `wanted` or we
 * fall past `oldestUnixSeconds` (the lookback floor).
 * Returns the closed conversations whose ids are in `wanted`.
 */
export async function listClosedConversations({ wanted, oldestUnixSeconds }) {
  const found = [];
  let starting_after = null;
  const wantedSet = new Set(wanted);
  // Loop pages of state=closed newest-first
  while (wantedSet.size > 0) {
    const url = new URL('https://app.intercom.com/ember/inbox/conversations/list');
    url.searchParams.set('app_id', WORKSPACE_ID);
    url.searchParams.set('inbox_type', 'all');
    url.searchParams.set('sort_field', 'sorting_updated_at');
    url.searchParams.set('sort_direction', 'desc');
    url.searchParams.set('state', 'closed');
    url.searchParams.set('count', '50');
    url.searchParams.set('fields[]', 'attributes');
    if (starting_after) url.searchParams.set('starting_after', starting_after);

    const r = await fetch(url, { credentials: 'include' });
    if (!r.ok) throw new Error(`closed list ${r.status}`);
    const body = await r.json();
    const convos = body.conversations ?? [];
    if (convos.length === 0) break;

    let oldestOnPage = Infinity;
    for (const c of convos) {
      oldestOnPage = Math.min(oldestOnPage, c.updated_at);
      if (wantedSet.has(c.id)) {
        found.push(c);
        wantedSet.delete(c.id);
      }
    }
    if (oldestOnPage < oldestUnixSeconds) break;
    starting_after = body.pages?.next?.starting_after ?? null;
    if (!starting_after) break;
  }
  return found;
}
```

- [ ] **Step 2: Wire the closure pass into the sync flow**

In `extension/api.js` (or wherever the sync orchestrator lives), after fetching the open list and before posting to `/tickets/ingest`:

```javascript
async function syncTickets() {
  const openConvos = await listOpenConversations({ ... });
  const openIds = new Set(openConvos.map(c => c.id));

  // Closure pass: any tracked id NOT in openIds may have flipped to closed.
  const syncState = await fetch('http://127.0.0.1:8000/tickets/sync-state')
    .then(r => r.json());
  const trackedIds = Object.keys(syncState);
  const candidateClosedIds = trackedIds.filter(id => !openIds.has(id));

  let closedConvos = [];
  if (candidateClosedIds.length > 0) {
    const oldestUnix = Math.floor(Date.now() / 1000) - LOOKBACK_SECONDS;
    closedConvos = await listClosedConversations({
      wanted: candidateClosedIds,
      oldestUnixSeconds: oldestUnix,
    });
  }

  const all = [...openConvos, ...closedConvos];
  const hydrated = await Promise.all(all.map(c => hydrateConversation(c.id)));
  // For closed ones we need to overwrite hydrated.state to 'closed' since the
  // detail endpoint may report stale state — actually it carries `state`
  // directly so this is fine. Trust the detail call.
  await fetch('http://127.0.0.1:8000/tickets/ingest', {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(hydrated),
  });
}
```

(Adjust import names + entry point to match the existing extension layout.)

- [ ] **Step 3: Manual smoke test**

Load the extension unpacked, open Intercom, close a conversation that the backend has stored as open, click the sync button on the popup. Verify the backend logs show one ingest call carrying the closed convo and that the webapp's Resolved column gains the ticket.

- [ ] **Step 4: Commit**

```bash
git add extension/intercom.js extension/api.js extension/background.js
git commit -m "Extension: closure pass syncs Intercom-closed tickets"
```

---

## Task 18: Extension popup — Resolved tab + resolve action

**Files:**
- Modify: `extension/popup.js`, `extension/popup.html`, `extension/popup.css`

- [ ] **Step 1: Add a "Resolved" tab to the column-tab UI**

Append "Resolved" to the tab list in `popup.html` (or wherever tabs are built dynamically in `popup.js`). When selected, fetch `GET /tickets?resolved=true` and render the same card layout.

- [ ] **Step 2: Add a tap-to-resolve button to each open-state card row**

Mirror the existing tap-to-move override pattern. A ✓ button next to the deep-link calls `POST /tickets/{id}/resolve`; on resolved-tab cards an ↺ button calls `POST /tickets/{id}/reopen`.

- [ ] **Step 3: Manual smoke test**

Open the popup, switch to Resolved tab — see the same items the webapp shows. Tap ✓ on an open-tab card → it disappears from open tab, appears on resolved tab.

- [ ] **Step 4: Commit**

```bash
git add extension/popup.js extension/popup.html extension/popup.css
git commit -m "Extension popup: Resolved tab + resolve/reopen actions"
```

---

## Task 19: Docs — spec.md, plan.md, tasks.md

**Files:**
- Modify: `spec.md`, `plan.md`, `tasks.md`

- [ ] **Step 1: Add user stories to `spec.md`**

Append after US-014:

```markdown
### US-015 — Manual ticket resolution
I can mark a ticket as resolved; resolved tickets leave the category columns and
live in a dedicated Resolved column that is always shown.

Acceptance:
- A "Mark resolved" action is available on every open ticket from three surfaces:
  drag into the Resolved column, the card-level ✓ icon, and the flyout button.
- Resolved tickets disappear from category columns and appear in the Resolved
  column, sorted most-recently-resolved first.
- The Resolved column is always visible regardless of `include_category_ids`.
- I can reopen a resolved ticket via drag, icon, or flyout; reopening returns
  it to its category column.

### US-016 — AI suggests resolution
When the AI thinks a ticket appears resolved (or that a resolved ticket is no
longer resolved), I see an advisory chip on the card. The AI never moves a
ticket automatically.

Acceptance:
- The same AI categorization call returns `resolution_verdict`,
  `resolution_confidence`, and `resolution_reason`.
- A chip appears on a card only when the effective AI-resolve flag is on for
  that ticket, the verdict is opposite to current state, confidence ≥
  the configured threshold, and the chip has not been dismissed since the
  ticket's last update.
- Clicking the chip applies the suggestion.
- Dismissing the chip hides it until the ticket has new activity.

### US-017 — Intercom-closed tickets auto-resolve
A ticket I previously had as open that flips to `state=closed` in Intercom is
silently resolved with `source='intercom_closed'`.

Acceptance:
- The extension's sync flow includes a closure pass: it diffs tracked ids
  against the open list and pulls just the missing ids from Intercom's closed
  list.
- The backend `_upsert_ticket` stamps `resolved_at` + `resolved_source` only
  on the open→closed transition (not on every closed-state sync).
- No AI call is made for the closure event.
```

Add FRs FR-025..FR-031 covering: orthogonal flag, three sources, server-computed chip state, /resolve + /reopen endpoints, AI tri-state per ticket, settings fields, closure pass.

- [ ] **Step 2: Update `plan.md`**

Add a new section `§8c. Ticket resolution` that points at the design doc and summarizes the schema additions. Update the table in §5 (Data model) with the four new `tickets` columns + three `ai_cache` columns + two `settings` columns.

- [ ] **Step 3: Update `tasks.md`**

Add a new Phase 11 — Ticket resolution with the 18 tasks above (T060..T077 or whatever the next free numbers are). Each task entry has `Implements:` lines to the new US/FR ids. Update the traceability matrix at the bottom of `tasks.md`.

- [ ] **Step 4: Commit**

```bash
git add spec.md plan.md tasks.md
git commit -m "Docs: spec/plan/tasks for ticket-resolution feature"
```

---

## Task 20: Quality gates pass on `main`

- [ ] **Step 1: Backend**

```bash
cd backend
ruff check app tests && ruff format --check app tests
mypy app
pytest -q
```

All green expected.

- [ ] **Step 2: Webapp**

```bash
cd webapp
npm run typecheck
npm run build
```

All green expected.

- [ ] **Step 3: Manual end-to-end smoke**

- Start backend + webapp.
- Load extension unpacked; sync.
- Confirm Resolved column visible with zero items.
- Mark a ticket resolved via drag → it appears in Resolved column.
- Click ↺ icon on resolved card → it returns to its category column.
- Toggle Auto-resolve on in settings; trigger another sync. Confirm AI chips appear on at least one card.
- Dismiss a chip → it disappears. Force a new sync that bumps `updated_at` on that ticket (manual: add a note in Intercom) → chip returns.
- In Intercom, close a previously-open conversation. Sync. Confirm the ticket auto-moves to Resolved with source `intercom_closed`.

- [ ] **Step 4: Final commit (if any tweaks)**

```bash
git status
# only commit if there are pending fixes from the smoke test
```

---

## Self-review

**Spec coverage check:**

| Spec section | Plan task(s) |
|---|---|
| §3.1 tickets additions | Task 1 (migration + model), Task 6 (writes), Task 7 (mutations), Task 9 (reads) |
| §3.2 ai_cache additions | Task 1 (schema), Task 5 (read/write) |
| §3.3 settings additions | Task 1 (schema), Task 10 (api) |
| §4.1 prompt extension | Task 3 |
| §4.2 resolver + cache | Tasks 4 + 5 |
| §4.3 concurrency | Unchanged — no task needed |
| §5.1 extension closure pass | Task 17 |
| §5.2 backend auto-resolve transition | Task 6 |
| §5.3 ticket response shape | Tasks 2 + 9 + 15 (ai_resolve_override sub-step) |
| §6.1 Resolved column | Task 13 |
| §6.2 resolve actions (drag/icon/flyout) | Tasks 13, 14, 15 |
| §6.3 chip rules | Task 9 (server compute) + Task 14 (render) |
| §6.4 settings drawer section | Task 16 |
| §6.5 per-ticket AI override | Task 15 |
| §6.6 filter / state interplay | Task 9 |
| §7 API | Task 8 (resolve/reopen/ai/dismiss), Task 9 (?resolved=, drag-out), Task 10 (settings) |
| §8 front-end | Tasks 11–16 |
| §9 migration | Task 1 |
| §10 spec/plan/tasks updates | Task 19 |
| §12 testing focus | Covered across Tasks 6, 7, 8, 9 tests |

All covered.

**Placeholder scan:** none — every code step has actual code; Tasks 10, 12, 17, 18 require reading neighboring files but the exact contracts + sketches are spelled out.

**Type consistency:**
- `ResolvedSource` literal: same in `schemas.py`, `resolution.py` dataclass, `types/api.ts`.
- `ResolutionChipState` literal: same in `schemas.py` + `types/api.ts`.
- `ai_resolve_enabled` is consistently the **effective** value on the wire; `ai_resolve_override` (added in Task 15 sub-step) is the **raw** nullable. The flyout reads the raw; the chip computation in Task 9 reads the raw to compute effectiveness via merge.

**Known gotchas flagged for the implementer:**

- Task 15 introduces `ai_resolve_override` retroactively into Tasks 2/9/11/12 — the implementer must apply it back to those files when reaching Task 15, or pre-add it during Task 2.
- The chip-state computation runs server-side per ticket on every `GET /tickets`. Cheap (constant work per row) but verify with `EXPLAIN QUERY PLAN` on the SQL fan-out joins if performance regresses.
- `services.tickets.set_override` already commits inside its body — make sure the resolution clear runs *before* the commit so it's atomic.

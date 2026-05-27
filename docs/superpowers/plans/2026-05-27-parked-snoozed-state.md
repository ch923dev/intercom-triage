# Parked / Snoozed Ticket State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an operator-driven "parked" ticket state (defer a ticket until a chosen time, with a reason) across backend + webapp + extension, shipping as one PR.

**Architecture:** Parallel state mirroring the existing resolution XOR pattern — three nullable columns (`parked_at`, `parked_until`, `parked_reason`) on `tickets`, guarded by CheckConstraints. Parked is orthogonal to resolution; every resolve path clears the parked trio. "Ready to resume" (`parked_until <= now`) is derived on read, never stored — no background job. UI is a filter chip (Layout B): parked tickets drop out of category columns and surface in a parked-only view; one-click manual unpark.

**Tech Stack:** FastAPI + async SQLAlchemy 2.0 + Alembic + SQLite (backend); Vue 3 + Pinia + TS + Vitest (webapp); plain MV3 ES modules (extension).

**Source spec:** `docs/superpowers/specs/2026-05-27-parked-snoozed-state-design.md`

---

## Conventions for every task

- Backend: `from __future__ import annotations` at top; `naive_utcnow()` for DB clock; services raise `HTTPException`; services own commits; ruff + mypy strict. Run backend gate from `backend/` with the venv active.
- Webapp: `import type` for types; tokens from `tokens.css`; `--max-warnings 0`.
- Commit after each task. Branch first (we are on `main`): `git checkout -b feat/4.1-parked-state`.

## Execution waves (dependencies)

```
Task 1 (model+migration) → Task 2 (schemas) → Task 3 (service) → Task 4 (bulk) → Task 5 (routes) → Task 6 (stickiness test)
   then contract: Task 7 (types) → Task 8 (api client) → Task 9 (store)
   then UI: Task 10 (Topbar chip) ∥ Task 11 (park menu) ∥ Task 12 (BulkActionBar)
   then extension: Task 13 (api.js) → Task 14 (popup)
   then Task 15 (docs) → Task 16 (cross-package gate + PR)
```

---

### Task 0: Branch

- [ ] **Step 1: Create the feature branch**

```bash
git checkout -b feat/4.1-parked-state
```

---

### Task 1: Model columns + migration 0018

**Files:**
- Modify: `backend/app/models.py` (Ticket class, ~line 638 and `__table_args__` ~line 640-667)
- Create: `backend/alembic/versions/0018_add_parked_columns.py`
- Test: `backend/tests/test_parked_model.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_parked_model.py
from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.util import naive_utcnow


async def _make_open_ticket(session: AsyncSession, tid: str = "park-1") -> Ticket:
    row = Ticket(
        id=tid, title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(),
        summary="", ai_confidence=0.0,
    )
    session.add(row)
    await session.commit()
    return row


async def test_full_parked_trio_is_allowed(session: AsyncSession) -> None:
    row = await _make_open_ticket(session)
    now = naive_utcnow()
    row.parked_at = now
    row.parked_until = now
    row.parked_reason = "waiting_on_customer"
    await session.commit()
    fetched = (await session.scalars(select(Ticket).where(Ticket.id == "park-1"))).one()
    assert fetched.parked_reason == "waiting_on_customer"


async def test_half_parked_trio_is_rejected(session: AsyncSession) -> None:
    row = await _make_open_ticket(session, "park-2")
    row.parked_at = naive_utcnow()  # but not parked_until / parked_reason
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_parked_reason_enum_is_enforced(session: AsyncSession) -> None:
    row = await _make_open_ticket(session, "park-3")
    now = naive_utcnow()
    row.parked_at, row.parked_until, row.parked_reason = now, now, "bogus"
    with pytest.raises(IntegrityError):
        await session.commit()


async def test_parked_and_resolved_is_rejected(session: AsyncSession) -> None:
    row = await _make_open_ticket(session, "park-4")
    now = naive_utcnow()
    row.resolved_at, row.resolved_source = now, "manual"
    row.parked_at, row.parked_until, row.parked_reason = now, now, "other"
    with pytest.raises(IntegrityError):
        await session.commit()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parked_model.py`
Expected: FAIL — `Ticket` has no attribute `parked_at`.

- [ ] **Step 3: Add the columns to the model**

In `backend/app/models.py`, after the `resolution_cleared_at` column (line 638):

```python
    resolution_cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Roadmap 4.1 (T106) — operator "parked / snoozed" state: a deferred-action
    # ticket. Orthogonal to resolution; the trio is all-set-or-all-null and a
    # ticket is never both parked and resolved. "ready" (parked_until <= now) is
    # derived on read, not stored.
    parked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
```

- [ ] **Step 4: Add the constraints**

In the same class's `__table_args__` tuple, after `tickets_ai_sentiment_check` (before the closing `)` at line 667):

```python
        CheckConstraint(
            "(parked_at IS NULL) = (parked_until IS NULL) "
            "AND (parked_at IS NULL) = (parked_reason IS NULL)",
            name="tickets_parked_trio_check",
        ),
        CheckConstraint(
            "parked_reason IS NULL OR parked_reason "
            "IN ('waiting_on_customer','waiting_on_third_party','waiting_internal','other')",
            name="tickets_parked_reason_check",
        ),
        CheckConstraint(
            "NOT (parked_at IS NOT NULL AND resolved_at IS NOT NULL)",
            name="tickets_not_parked_and_resolved_check",
        ),
```

- [ ] **Step 5: Create the migration**

```python
# backend/alembic/versions/0018_add_parked_columns.py
"""Add tickets.parked_at / parked_until / parked_reason (roadmap 4.1, T106).

Operator "parked / snoozed" state. Orthogonal to resolution: trio is
all-or-none, reason is an enum, and a ticket is never both parked and resolved.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-27 00:00:18.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("parked_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("parked_until", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("parked_reason", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "tickets_parked_trio_check",
            "(parked_at IS NULL) = (parked_until IS NULL) "
            "AND (parked_at IS NULL) = (parked_reason IS NULL)",
        )
        batch_op.create_check_constraint(
            "tickets_parked_reason_check",
            "parked_reason IS NULL OR parked_reason "
            "IN ('waiting_on_customer','waiting_on_third_party','waiting_internal','other')",
        )
        batch_op.create_check_constraint(
            "tickets_not_parked_and_resolved_check",
            "NOT (parked_at IS NOT NULL AND resolved_at IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_not_parked_and_resolved_check", type_="check")
        batch_op.drop_constraint("tickets_parked_reason_check", type_="check")
        batch_op.drop_constraint("tickets_parked_trio_check", type_="check")
        batch_op.drop_column("parked_reason")
        batch_op.drop_column("parked_until")
        batch_op.drop_column("parked_at")
```

- [ ] **Step 6: Run tests + migration**

Run: `pytest -q tests/test_parked_model.py`
Expected: PASS (tests use `init_db` → `alembic upgrade head`, picking up 0018).
Run: `python -m app.models`
Expected: in-memory schema smoke prints seeded categories, no error.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0018_add_parked_columns.py backend/tests/test_parked_model.py
git commit -m "feat(4.1): parked columns + constraints on tickets (T106)"
```

---

### Task 2: Schemas — request/response + ParkedReason on TicketSchema

**Files:**
- Modify: `backend/app/schemas.py` (`ResolvedSource` area ~line 56; `TicketSchema` ~line 464-466; bulk bodies ~line 595)
- Test: `backend/tests/test_parked_schemas.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_parked_schemas.py
from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.schemas import BulkParkRequest, ParkRequest
from app.util import naive_utcnow


def test_park_request_accepts_future_until() -> None:
    req = ParkRequest(until_at=naive_utcnow() + timedelta(hours=1), reason="waiting_on_customer")
    assert req.reason == "waiting_on_customer"


def test_park_request_rejects_past_until() -> None:
    with pytest.raises(ValidationError):
        ParkRequest(until_at=naive_utcnow() - timedelta(hours=1), reason="other")


def test_park_request_rejects_bad_reason() -> None:
    with pytest.raises(ValidationError):
        ParkRequest(until_at=naive_utcnow() + timedelta(hours=1), reason="nope")


def test_bulk_park_request_carries_ids_and_fields() -> None:
    req = BulkParkRequest(
        ticket_ids=["a", "b"],
        until_at=naive_utcnow() + timedelta(days=1),
        reason="waiting_internal",
    )
    assert req.ticket_ids == ["a", "b"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parked_schemas.py`
Expected: FAIL — cannot import `ParkRequest` / `BulkParkRequest`.

- [ ] **Step 3: Add the ParkedReason type + a future-validator helper**

In `backend/app/schemas.py`, near `ResolvedSource` (line 56) add:

```python
ParkedReason = Literal[
    "waiting_on_customer", "waiting_on_third_party", "waiting_internal", "other"
]
```

Ensure these imports exist at the top of the file (add any missing):

```python
from pydantic import model_validator
from app.util import naive_utcnow
```

Add a module-level helper (near the other small helpers):

```python
def _require_future_until(until_at: datetime) -> None:
    # `until_at` is already coerced to naive UTC by NaiveUTCDatetime.
    if until_at <= naive_utcnow():
        raise ValueError("until_at must be in the future")
```

- [ ] **Step 4: Add the request/response models**

Place near `ResolveResponse` (line 482):

```python
class ParkRequest(BaseModel):
    """POST /tickets/{id}/park body. `until_at` is the wake time (must be future)."""

    until_at: NaiveUTCDatetime
    reason: ParkedReason

    @model_validator(mode="after")
    def _check_future(self) -> "ParkRequest":
        _require_future_until(self.until_at)
        return self


class ParkResponse(BaseModel):
    ok: Literal[True] = True
    parked_at: UTCDatetime
    parked_until: UTCDatetime
    parked_reason: ParkedReason


class UnparkResponse(BaseModel):
    ok: Literal[True] = True
```

Place near `BulkFollowupSet` (line 595):

```python
class BulkParkRequest(BulkTicketIds):
    """POST /tickets/bulk/park body — one wake time + reason applied to N tickets."""

    until_at: NaiveUTCDatetime
    reason: ParkedReason

    @model_validator(mode="after")
    def _check_future(self) -> "BulkParkRequest":
        _require_future_until(self.until_at)
        return self
```

- [ ] **Step 5: Add parked fields to TicketSchema (board response)**

In `TicketSchema`, after `ai_labels` (line 466):

```python
    # Roadmap 4.1 (T106) — parked / snoozed state. Board-state, like resolved_*
    # (NOT on HydratedTicket). `ready` is derived client-side from parked_until.
    parked_at: UTCDatetime | None = None
    parked_until: UTCDatetime | None = None
    parked_reason: ParkedReason | None = None
```

- [ ] **Step 6: Run tests**

Run: `pytest -q tests/test_parked_schemas.py`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_parked_schemas.py
git commit -m "feat(4.1): park request/response schemas + ParkedReason on TicketSchema"
```

---

### Task 3: Resolution service — apply_park / apply_unpark / clear_parked + resolve clears park

**Files:**
- Modify: `backend/app/services/resolution.py`
- Modify: `backend/app/services/tickets.py` (`_maybe_auto_resolve_from_ai` ~line 188-191; `_upsert_ticket` close-transition ~line 248-250)
- Test: `backend/tests/test_parked_service.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_parked_service.py
from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services import resolution as svc
from app.util import naive_utcnow


async def _open(session: AsyncSession, tid: str) -> Ticket:
    row = Ticket(
        id=tid, title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(), summary="", ai_confidence=0.0,
    )
    session.add(row)
    await session.commit()
    return row


async def test_park_then_unpark(session: AsyncSession) -> None:
    row = await _open(session, "p1")
    until = naive_utcnow() + timedelta(hours=2)
    out = svc.apply_park(row, until, "waiting_on_customer")
    assert out.parked_until == until
    assert row.parked_at is not None
    svc.apply_unpark(row)
    assert row.parked_at is None and row.parked_until is None and row.parked_reason is None


async def test_park_twice_is_409(session: AsyncSession) -> None:
    row = await _open(session, "p2")
    svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "other")
    with pytest.raises(HTTPException) as exc:
        svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "other")
    assert exc.value.status_code == 409


async def test_unpark_when_not_parked_is_409(session: AsyncSession) -> None:
    row = await _open(session, "p3")
    with pytest.raises(HTTPException) as exc:
        svc.apply_unpark(row)
    assert exc.value.status_code == 409


async def test_cannot_park_resolved_ticket(session: AsyncSession) -> None:
    row = await _open(session, "p4")
    svc.apply_resolve(row)
    with pytest.raises(HTTPException) as exc:
        svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "other")
    assert exc.value.status_code == 409


async def test_resolving_a_parked_ticket_clears_park(session: AsyncSession) -> None:
    row = await _open(session, "p5")
    svc.apply_park(row, naive_utcnow() + timedelta(hours=1), "waiting_internal")
    svc.apply_resolve(row)
    await session.commit()  # would raise if parked + resolved both set
    assert row.parked_at is None
    assert row.resolved_source == "manual"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parked_service.py`
Expected: FAIL — `resolution` has no `apply_park`.

- [ ] **Step 3: Add the parking helpers + outcome to resolution.py**

In `backend/app/services/resolution.py`, after the `ResolveOutcome` dataclass (line 24):

```python
@dataclass
class ParkOutcome:
    parked_at: datetime
    parked_until: datetime
    parked_reason: str
```

After `apply_reopen` (line 60), add:

```python
def clear_parked(row: Ticket) -> None:
    """Clear the parked trio. Does NOT commit. Safe on an unparked row.
    Called by every resolve path so a parked ticket can never become resolved
    while still parked (tickets_not_parked_and_resolved_check)."""
    row.parked_at = None
    row.parked_until = None
    row.parked_reason = None


def apply_park(row: Ticket, until_at: datetime, reason: str) -> ParkOutcome:
    """Mutate a Ticket row into the parked state. Does NOT commit.
    409 if the row is resolved (reopen first) or already parked."""
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is resolved; reopen before parking")
    if row.parked_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already parked")
    now = naive_utcnow()
    row.parked_at = now
    row.parked_until = until_at
    row.parked_reason = reason
    return ParkOutcome(parked_at=now, parked_until=until_at, parked_reason=reason)


def apply_unpark(row: Ticket) -> None:
    """Clear the parked state. Does NOT commit. 409 if not parked."""
    if row.parked_at is None:
        raise HTTPException(status_code=409, detail="ticket is not parked")
    clear_parked(row)
```

In `apply_resolve`, add `clear_parked(row)` immediately before `return` (after setting `resolved_source`, line 48):

```python
    row.resolved_at = now
    row.resolved_source = "manual"
    clear_parked(row)
    return ResolveOutcome(resolved_at=now, resolved_source="manual")
```

In `apply_mark_non_actionable`, likewise before its `return` (after line 72):

```python
    row.resolved_at = now
    row.resolved_source = "non_actionable"
    clear_parked(row)
    return ResolveOutcome(resolved_at=now, resolved_source="non_actionable")
```

Add the async wrappers after `mark_non_actionable` (line 99):

```python
async def park(
    session: AsyncSession, ticket_id: str, until_at: datetime, reason: str
) -> ParkOutcome:
    """Park a ticket until `until_at`. 409 if resolved or already parked."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_park(row, until_at, reason)
    await session.commit()
    metrics.incr("tickets_parked_total")
    return outcome


async def unpark(session: AsyncSession, ticket_id: str) -> None:
    """Unpark a ticket. 409 if not parked."""
    row = await get_or_404(session, ticket_id)
    apply_unpark(row)
    await session.commit()
    metrics.incr("tickets_unparked_total")
```

- [ ] **Step 4: Clear parked in the ingest auto-resolve paths**

In `backend/app/services/tickets.py`, add the import near the other service imports (top of file — confirm `resolution` is imported; if not, add `from app.services.resolution import clear_parked`):

```python
from app.services.resolution import clear_parked
```

In `_maybe_auto_resolve_from_ai`, after setting `resolved_source` (line 188-191):

```python
    row.resolved_at = now
    row.resolved_source = (
        "ai_resolved" if result.ai_resolution_verdict == "resolved" else "non_actionable"
    )
    clear_parked(row)
```

In `_upsert_ticket`, the close-transition branch on an existing row (line 248-250):

```python
    if hydrated.state == "closed" and row.state != "closed" and row.resolved_at is None:
        row.resolved_at = now
        row.resolved_source = "intercom_closed"
        clear_parked(row)
```

(The new-row insert path at 239-241 needs no clear — a freshly built row has a null parked trio.)

- [ ] **Step 5: Run tests**

Run: `pytest -q tests/test_parked_service.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/resolution.py backend/app/services/tickets.py backend/tests/test_parked_service.py
git commit -m "feat(4.1): park/unpark service + clear-parked on every resolve path"
```

---

### Task 4: Bulk service — bulk_park / bulk_unpark

**Files:**
- Modify: `backend/app/services/bulk.py`
- Test: `backend/tests/test_parked_bulk.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_parked_bulk.py
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services import bulk as bulk_svc
from app.services import resolution as svc
from app.util import naive_utcnow


async def _open(session: AsyncSession, tid: str) -> None:
    session.add(Ticket(
        id=tid, title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(), summary="", ai_confidence=0.0,
    ))
    await session.commit()


async def test_bulk_park_then_unpark(session: AsyncSession) -> None:
    for t in ("b1", "b2"):
        await _open(session, t)
    until = naive_utcnow() + timedelta(hours=3)
    res = await bulk_svc.bulk_park(session, ["b1", "b2"], until, "waiting_on_third_party")
    assert set(res.ok_ids) == {"b1", "b2"} and res.failed == []
    res2 = await bulk_svc.bulk_unpark(session, ["b1", "b2"])
    assert set(res2.ok_ids) == {"b1", "b2"}


async def test_bulk_park_skips_already_parked(session: AsyncSession) -> None:
    await _open(session, "b3")
    svc.apply_park(await svc.get_or_404(session, "b3"), naive_utcnow() + timedelta(hours=1), "other")
    await session.commit()
    res = await bulk_svc.bulk_park(session, ["b3"], naive_utcnow() + timedelta(hours=2), "other")
    assert res.ok_ids == [] and len(res.failed) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parked_bulk.py`
Expected: FAIL — `bulk` has no `bulk_park`.

- [ ] **Step 3: Implement bulk_park / bulk_unpark**

In `backend/app/services/bulk.py`, after `bulk_mark_non_actionable` (line 118), add the import of `datetime` if not present (it is, line 18) and:

```python
async def bulk_park(
    session: AsyncSession, ticket_ids: list[str], until_at: datetime, reason: str
) -> BulkResult:
    """Park N tickets until `until_at`. Resolved/already-parked rows fail 409."""

    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_park(row, until_at, reason)
        metrics.incr("tickets_parked_total")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("park", result)
    return result


async def bulk_unpark(session: AsyncSession, ticket_ids: list[str]) -> BulkResult:
    """Unpark N tickets. Non-parked rows fail 409."""

    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_unpark(row)
        metrics.incr("tickets_unparked_total")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("unpark", result)
    return result
```

- [ ] **Step 4: Run tests**

Run: `pytest -q tests/test_parked_bulk.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/bulk.py backend/tests/test_parked_bulk.py
git commit -m "feat(4.1): bulk_park / bulk_unpark"
```

---

### Task 5: Routes — park / unpark / bulk

**Files:**
- Modify: `backend/app/routers/tickets.py` (bulk block ~line 124-130; single block ~line 181-188)
- Test: `backend/tests/test_parked_api.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_parked_api.py
from __future__ import annotations

from datetime import timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.util import naive_utcnow


async def _seed_open(session: AsyncSession, tid: str = "api-1") -> None:
    session.add(Ticket(
        id=tid, title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(), summary="", ai_confidence=0.0,
    ))
    await session.commit()


async def test_park_and_unpark_roundtrip(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session)
    until = (naive_utcnow() + timedelta(hours=1)).isoformat() + "Z"
    r = await client.post("/tickets/api-1/park", json={"until_at": until, "reason": "waiting_on_customer"})
    assert r.status_code == 200, r.text
    assert r.json()["parked_reason"] == "waiting_on_customer"
    r2 = await client.post("/tickets/api-1/unpark", json={})
    assert r2.status_code == 200 and r2.json()["ok"] is True


async def test_park_past_time_is_422(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session, "api-2")
    past = (naive_utcnow() - timedelta(hours=1)).isoformat() + "Z"
    r = await client.post("/tickets/api-2/park", json={"until_at": past, "reason": "other"})
    assert r.status_code == 422


async def test_unpark_not_parked_is_409(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session, "api-3")
    r = await client.post("/tickets/api-3/unpark", json={})
    assert r.status_code == 409


async def test_bulk_park(client: AsyncClient, session: AsyncSession) -> None:
    await _seed_open(session, "api-4")
    until = (naive_utcnow() + timedelta(hours=1)).isoformat() + "Z"
    r = await client.post(
        "/tickets/bulk/park",
        json={"ticket_ids": ["api-4"], "until_at": until, "reason": "waiting_internal"},
    )
    assert r.status_code == 200 and r.json()["ok_ids"] == ["api-4"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest -q tests/test_parked_api.py`
Expected: FAIL — 404/405 (routes not defined).

- [ ] **Step 3: Update imports in the router**

In `backend/app/routers/tickets.py`, add to the schema import block:

```python
from app.schemas import (
    BulkParkRequest,
    ParkRequest,
    ParkResponse,
    UnparkResponse,
    # ...existing imports...
)
```

- [ ] **Step 4: Add bulk routes (in the `/bulk/...` block, after `bulk_non_actionable`, ~line 130)**

```python
@router.post("/bulk/park", response_model=BulkResult)
async def bulk_park(
    body: BulkParkRequest,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Park N tickets until `until_at`. Resolved/already-parked rows fail 409."""
    return await bulk_svc.bulk_park(session, body.ticket_ids, body.until_at, body.reason)


@router.post("/bulk/unpark", response_model=BulkResult)
async def bulk_unpark(
    body: BulkTicketIds,
    session: AsyncSession = Depends(get_session),
) -> BulkResult:
    """Unpark N tickets. Non-parked rows fail 409."""
    return await bulk_svc.bulk_unpark(session, body.ticket_ids)
```

(Match the exact `Depends`/param style of the surrounding `bulk_resolve` handler — copy its signature shape verbatim, only the body type + call differ.)

- [ ] **Step 5: Add single-ticket routes (in the `/{ticket_id}/...` block, after `reopen_ticket`, ~line 188)**

```python
@router.post("/{ticket_id}/park", response_model=ParkResponse)
async def park_ticket(
    ticket_id: str,
    body: ParkRequest,
    session: AsyncSession = Depends(get_session),
) -> ParkResponse:
    """Park a ticket until `until_at`. 409 if resolved or already parked."""
    out = await resolution_svc.park(session, ticket_id, body.until_at, body.reason)
    return ParkResponse(
        parked_at=out.parked_at, parked_until=out.parked_until, parked_reason=out.parked_reason
    )


@router.post("/{ticket_id}/unpark", response_model=UnparkResponse)
async def unpark_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> UnparkResponse:
    """Unpark a ticket. 409 if not parked, 404 if unknown."""
    await resolution_svc.unpark(session, ticket_id)
    return UnparkResponse()
```

- [ ] **Step 6: Run tests**

Run: `pytest -q tests/test_parked_api.py`
Expected: PASS. Also open `http://localhost:4000/docs` if the server is running and confirm the four routes appear.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/tickets.py backend/tests/test_parked_api.py
git commit -m "feat(4.1): park/unpark + bulk routes"
```

---

### Task 6: Stickiness regression test (no code change)

**Files:**
- Test: `backend/tests/test_parked_stickiness.py`

- [ ] **Step 1: Write the test (asserts re-sync does not clobber parked)**

```python
# backend/tests/test_parked_stickiness.py
from __future__ import annotations

from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket
from app.services import resolution as svc
from app.services.tickets import _upsert_ticket
from app.schemas import HydratedTicket
from app.ai.pipeline import CategorizationResult  # adjust import if defined elsewhere
from app.util import naive_utcnow


async def test_resync_preserves_parked_state(session: AsyncSession, test_config) -> None:
    # Seed a parked, open ticket.
    row = Ticket(
        id="sticky-1", title="t", state="open", priority=None, url=None,
        author={}, parts=[], internal_notes=[],
        created_at=naive_utcnow(), updated_at=naive_utcnow(), summary="", ai_confidence=0.0,
    )
    session.add(row)
    await session.commit()
    until = naive_utcnow() + timedelta(hours=4)
    svc.apply_park(row, until, "waiting_on_customer")
    await session.commit()

    # Re-sync the same conversation (still open) via the ingest upsert path.
    hydrated = HydratedTicket.model_validate({
        "id": "sticky-1", "title": "t", "state": "open", "priority": None,
        "created_at": naive_utcnow(), "updated_at": naive_utcnow(),
        "author": {"name": "C", "email": None, "id": None, "type": "user"},
        "url": None, "parts": [], "internal_notes": [],
    })
    # A non-resolving fallback result (mirrors the cold/fallback path).
    result = CategorizationResult(
        category_id=None, proposal_id=None, summary="", confidence=0.0, fallback=True,
        ai_priority="normal", ai_sentiment="neutral", ai_labels=[],
    )
    # Build minimal FilterSettings via the settings service or a fixture if available.
    from app.services.settings import get_settings
    settings = await get_settings(session)
    await _upsert_ticket(session, hydrated, result, settings)
    await session.commit()

    refreshed = await session.get(Ticket, "sticky-1")
    assert refreshed is not None
    assert refreshed.parked_at is not None  # NOT clobbered by re-sync
    assert refreshed.parked_reason == "waiting_on_customer"
```

> **Note for executor:** the exact constructor kwargs for `CategorizationResult` and the `HydratedTicket`/`TicketAuthorSchema` shape may differ slightly — adjust to the real definitions (grep `class CategorizationResult` and `class TicketAuthorSchema`). The assertion (parked survives re-sync) is the point. If `get_settings` has a different name, use the project's settings-loading helper.

- [ ] **Step 2: Run + confirm green**

Run: `pytest -q tests/test_parked_stickiness.py`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_parked_stickiness.py
git commit -m "test(4.1): re-sync preserves parked state (stickiness by construction)"
```

- [ ] **Step 4: Run the full backend gate before crossing to webapp**

Run: `ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
Expected: all green. Fix any ruff/mypy nits inline (e.g. import ordering).

---

### Task 7: Webapp types

**Files:**
- Modify: `webapp/src/types/api.ts` (`Ticket` interface ~line 169; near `ResolvedSource`)

- [ ] **Step 1: Add the ParkedReason type + Ticket fields**

Near `ResolvedSource` in `webapp/src/types/api.ts`:

```ts
export type ParkedReason =
  | 'waiting_on_customer'
  | 'waiting_on_third_party'
  | 'waiting_internal'
  | 'other';
```

In `interface Ticket`, after `resolved_source` (line 196):

```ts
  parked_at: string | null;
  parked_until: string | null;
  parked_reason: ParkedReason | null;
```

- [ ] **Step 2: Verify typecheck**

Run: `npm --prefix webapp run typecheck`
Expected: clean (no consumers reference parked yet).

- [ ] **Step 3: Commit**

```bash
git add webapp/src/types/api.ts
git commit -m "feat(4.1): parked fields on webapp Ticket type"
```

---

### Task 8: Webapp api client

**Files:**
- Modify: `webapp/src/api/client.ts` (after `markNonActionable` ~line 161; bulk block ~line 251; type import line 20)

- [ ] **Step 1: Add the import + methods**

Add `ParkedReason` to the type import block (line 7-26):

```ts
  ParkedReason,
```

After `markNonActionable` (line 161), add single-ticket methods:

```ts
  /** Park a ticket until `untilAt` (ISO with Z) with a structured reason. */
  parkTicket: (
    ticketId: string,
    untilAt: string,
    reason: ParkedReason,
  ): Promise<{ parked_at: string; parked_until: string; parked_reason: ParkedReason }> =>
    request(`/tickets/${ticketId}/park`, {
      method: 'POST',
      body: JSON.stringify({ until_at: untilAt, reason }),
    }),

  /** Unpark a ticket. */
  unparkTicket: (ticketId: string): Promise<void> =>
    request(`/tickets/${ticketId}/unpark`, { method: 'POST', body: '{}' }),
```

In the bulk block (after `bulkMarkNonActionable` ~line 251):

```ts
  /** Park N tickets until `untilAt` with one reason. Per-id ok/failed. */
  bulkPark: (ticketIds: string[], untilAt: string, reason: ParkedReason): Promise<BulkResult> =>
    request('/tickets/bulk/park', {
      method: 'POST',
      body: JSON.stringify({ ticket_ids: ticketIds, until_at: untilAt, reason }),
    }),

  /** Unpark N tickets. Per-id ok/failed. */
  bulkUnpark: (ticketIds: string[]): Promise<BulkResult> =>
    request('/tickets/bulk/unpark', {
      method: 'POST',
      body: JSON.stringify({ ticket_ids: ticketIds }),
    }),
```

- [ ] **Step 2: Verify typecheck**

Run: `npm --prefix webapp run typecheck`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/api/client.ts
git commit -m "feat(4.1): park/unpark + bulk api client methods"
```

---

### Task 9: Webapp store — getters, actions, parkedOnly toggle, tests

**Files:**
- Modify: `webapp/src/stores/tickets.ts`
- Test: `webapp/src/stores/tickets.parked.spec.ts`

- [ ] **Step 1: Write the failing test**

```ts
// webapp/src/stores/tickets.parked.spec.ts
import { setActivePinia, createPinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useTicketsStore } from '@/stores/tickets';
import { api } from '@/api/client';
import type { Ticket } from '@/types/api';

function ticket(id: string, over: Partial<Ticket> = {}): Ticket {
  return {
    id, title: id, state: 'open', priority: null, created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z', author: { name: 'C', email: null, id: null, type: 'user' },
    url: null, parts: [], internal_notes: [], category_id: 1, proposal_id: null, summary: '',
    ai_confidence: 0.9, user_override: false, title_user_edited: false, summary_user_edited: false,
    followup: null, note: null, resolved_at: null, resolved_source: null, ai_resolve_enabled: false,
    ai_resolve_override: null, ai_resolution_verdict: null, ai_resolution_confidence: null,
    ai_resolution_reason: null, resolution_chip_state: null, ai_priority: null, ai_sentiment: null,
    ai_labels: [], parked_at: null, parked_until: null, parked_reason: null, ...over,
  } as Ticket;
}

describe('tickets store — parked', () => {
  beforeEach(() => setActivePinia(createPinia()));

  it('parked tickets drop out of category columns and into parkedTickets', () => {
    const store = useTicketsStore();
    const future = new Date(Date.now() + 3_600_000).toISOString();
    store.tickets.push(ticket('open-1'));
    store.tickets.push(ticket('parked-1', { parked_at: '2026-01-01T00:00:00Z', parked_until: future, parked_reason: 'other' }));
    // byCategory excludes parked
    const col = store.byCategory.get(1) ?? [];
    expect(col.map((t) => t.id)).toEqual(['open-1']);
    expect(store.parkedTickets.map((t) => t.id)).toEqual(['parked-1']);
    expect(store.readyParkedCount).toBe(0);
  });

  it('readyParkedCount counts tickets whose parked_until has passed', () => {
    const store = useTicketsStore();
    const past = new Date(Date.now() - 1000).toISOString();
    store.tickets.push(ticket('ready-1', { parked_at: '2026-01-01T00:00:00Z', parked_until: past, parked_reason: 'other' }));
    expect(store.readyParkedCount).toBe(1);
  });

  it('parkTicket sets the trio optimistically and calls the api', async () => {
    const store = useTicketsStore();
    store.tickets.push(ticket('p-1'));
    const spy = vi.spyOn(api, 'parkTicket').mockResolvedValue({ parked_at: 'x', parked_until: 'y', parked_reason: 'other' });
    const future = new Date(Date.now() + 3_600_000).toISOString();
    await store.parkTicket('p-1', future, 'other');
    expect(spy).toHaveBeenCalledWith('p-1', future, 'other');
    expect(store.tickets.find((t) => t.id === 'p-1')!.parked_at).not.toBeNull();
  });

  it('parkTicket rolls back the trio on api failure', async () => {
    const store = useTicketsStore();
    store.tickets.push(ticket('p-2'));
    vi.spyOn(api, 'parkTicket').mockRejectedValue(new Error('boom'));
    const future = new Date(Date.now() + 3_600_000).toISOString();
    await expect(store.parkTicket('p-2', future, 'other')).rejects.toThrow('boom');
    expect(store.tickets.find((t) => t.id === 'p-2')!.parked_at).toBeNull();
  });

  it('unparkTicket clears the trio optimistically', async () => {
    const store = useTicketsStore();
    const future = new Date(Date.now() + 3_600_000).toISOString();
    store.tickets.push(ticket('u-1', { parked_at: '2026-01-01T00:00:00Z', parked_until: future, parked_reason: 'other' }));
    vi.spyOn(api, 'unparkTicket').mockResolvedValue(undefined);
    await store.unparkTicket('u-1');
    expect(store.tickets.find((t) => t.id === 'u-1')!.parked_at).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/stores/tickets.parked.spec.ts` (from `webapp/`)
Expected: FAIL — `parkedTickets` / `parkTicket` undefined.

- [ ] **Step 3: Add the parkedOnly ref + getters**

In `webapp/src/stores/tickets.ts`, after `reviewOnly` (line 129-135) add:

```ts
  /** When true, the board narrows to PARKED tickets (roadmap 4.1, Layout B).
   *  A board-level toggle like `reviewOnly`, driven by the Topbar parked chip. */
  const parkedOnly = ref(false);
  function setParkedOnly(v: boolean) {
    parkedOnly.value = v;
  }
  function toggleParkedOnly() {
    parkedOnly.value = !parkedOnly.value;
  }

  /** Open tickets currently parked (parked_at set). Parked rows ride in the
   *  open list (resolved_at is null), so this is a straight filter. */
  const parkedTickets = computed(() => state.value.tickets.filter((t) => t.parked_at !== null));

  /** Count of parked tickets whose wake time has passed ("ready to resume"). */
  const readyParkedCount = computed(() => {
    const now = Date.now();
    return parkedTickets.value.filter(
      (t) => t.parked_until !== null && Date.parse(t.parked_until) <= now,
    ).length;
  });
```

- [ ] **Step 4: Exclude parked from the column/lane base (and honor parkedOnly)**

Replace the body of `facetVisibleTickets` (line 140-151) with:

```ts
  const facetVisibleTickets = computed(() => {
    let base = visibleTickets.value;
    if (reviewOnly.value) base = base.filter((t) => needsReview(t, effectiveOverridden(t)));
    // Layout B: parked tickets leave the category columns. The parked chip flips
    // `parkedOnly` to show ONLY parked; otherwise parked rows are hidden.
    base = parkedOnly.value
      ? base.filter((t) => t.parked_at !== null)
      : base.filter((t) => t.parked_at === null);
    if (!isFilterActive.value) return base;
    const now = Date.now();
    return base.filter((t) =>
      ticketMatchesFilter(t, activeFilter.value, effectiveCategoryId(t), now),
    );
  });
```

In `needsReviewTickets` (line 122-124), exclude parked so a parked ticket never sits in the review lane:

```ts
  const needsReviewTickets = computed(() =>
    state.value.tickets.filter((t) => t.parked_at === null && needsReview(t, effectiveOverridden(t))),
  );
```

- [ ] **Step 5: Add the actions**

After `reopen` (line 396) add:

```ts
  /** Park a ticket in place (it stays in the open list, drops out of columns).
   *  Optimistic; rolls back on server failure. */
  async function parkTicket(id: string, untilAt: string, reason: ParkedReason) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    mutating.value++;
    state.value.tickets.splice(idx, 1, {
      ...original,
      parked_at: new Date().toISOString(),
      parked_until: untilAt,
      parked_reason: reason,
    });
    try {
      await api.parkTicket(id, untilAt, reason);
    } catch (e) {
      state.value.tickets.splice(idx, 1, original);
      throw e;
    } finally {
      mutating.value--;
    }
  }

  /** Clear a ticket's parked state in place; rolls back on failure. */
  async function unparkTicket(id: string) {
    const idx = state.value.tickets.findIndex((t) => t.id === id);
    if (idx === -1) return;
    const original = state.value.tickets[idx]!;
    mutating.value++;
    state.value.tickets.splice(idx, 1, {
      ...original,
      parked_at: null,
      parked_until: null,
      parked_reason: null,
    });
    try {
      await api.unparkTicket(id);
    } catch (e) {
      state.value.tickets.splice(idx, 1, original);
      throw e;
    } finally {
      mutating.value--;
    }
  }
```

After `bulkDismissChip` (line 671) add (post-response update of `ok_ids`, mirroring `bulkDismissChip`):

```ts
  /** Bulk park — sets the trio on every ok id the server confirms. */
  async function bulkPark(ids: string[], untilAt: string, reason: ParkedReason): Promise<BulkResult> {
    mutating.value++;
    try {
      const result = await api.bulkPark(ids, untilAt, reason);
      const okSet = new Set(result.ok_ids);
      const stamped = new Date().toISOString();
      for (const t of state.value.tickets) {
        if (okSet.has(t.id)) {
          t.parked_at = stamped;
          t.parked_until = untilAt;
          t.parked_reason = reason;
        }
      }
      return result;
    } finally {
      mutating.value--;
    }
  }

  /** Bulk unpark — clears the trio on every ok id. */
  async function bulkUnpark(ids: string[]): Promise<BulkResult> {
    mutating.value++;
    try {
      const result = await api.bulkUnpark(ids);
      const okSet = new Set(result.ok_ids);
      for (const t of state.value.tickets) {
        if (okSet.has(t.id)) {
          t.parked_at = null;
          t.parked_until = null;
          t.parked_reason = null;
        }
      }
      return result;
    } finally {
      mutating.value--;
    }
  }
```

Add the `ParkedReason` type import at the top (line 11):

```ts
import type { BulkResult, ParkedReason, Ticket } from '@/types/api';
```

- [ ] **Step 6: Export the new members**

In the returned object (line 697-742), add:

```ts
    // Parked / snoozed (roadmap 4.1)
    parkedTickets,
    readyParkedCount,
    parkedOnly,
    setParkedOnly,
    toggleParkedOnly,
    parkTicket,
    unparkTicket,
    bulkPark,
    bulkUnpark,
```

- [ ] **Step 7: Run tests**

Run: `npx vitest run src/stores/tickets.parked.spec.ts`
Expected: PASS. Then `npm --prefix webapp run typecheck` clean.

- [ ] **Step 8: Commit**

```bash
git add webapp/src/stores/tickets.ts webapp/src/stores/tickets.parked.spec.ts
git commit -m "feat(4.1): parked getters + park/unpark + bulk store actions"
```

---

### Task 10: Topbar parked chip + ready badge

**Files:**
- Modify: `webapp/src/components/Topbar.vue` (mirror the `.pill.review` block ~line 62-63, 154-164, 296-306)

- [ ] **Step 1: Add the count + a chip that toggles `parkedOnly`**

In `<script setup>`, near `reviewCount` (line 62-63):

```ts
const parkedCount = computed(() => tickets.parkedTickets.length);
const readyCount = computed(() => tickets.readyParkedCount);
```

In the template, next to the review pill (after line 164), add a parked pill (mirror the review pill markup exactly, swapping store members):

```html
<button
  v-if="parkedCount > 0 || tickets.parkedOnly"
  class="pill parked"
  :class="{ active: tickets.parkedOnly }"
  :title="
    tickets.parkedOnly ? 'Showing parked tickets — click to clear' : 'Show parked tickets'
  "
  @click="tickets.toggleParkedOnly()"
>
  <span class="mono">⏸ {{ parkedCount }} parked</span>
  <span v-if="readyCount > 0" class="ready-badge mono">★ {{ readyCount }}</span>
</button>
```

In `<style scoped>`, after the `.pill.review` rules (line 296-306), add (use tokens; the parked accent reuses the existing blue-ish `--accent` family — if a dedicated token is wanted, propose it in `DESIGN.md` first per webapp/CLAUDE.md):

```css
.pill.parked {
  cursor: pointer;
}
.pill.parked.active {
  background: var(--chip-bg);
  border-color: var(--accent);
  color: var(--accent);
}
.pill.parked .ready-badge {
  margin-left: 6px;
  color: var(--accent);
}
```

- [ ] **Step 2: Verify**

Run: `npm --prefix webapp run lint && npm --prefix webapp run typecheck`
Expected: clean. Then `npm --prefix webapp run dev`, sync a ticket, park it (Task 11 trigger), confirm the chip appears, toggles a parked-only board, and the count is right. Cross-check colors/radii against `DESIGN.md`.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/components/Topbar.vue
git commit -m "feat(4.1): Topbar parked chip + ready badge (Layout B)"
```

---

### Task 11: Park action UI — ParkMenu component + card/flyout trigger

**Files:**
- Create: `webapp/src/components/ParkMenu.vue`
- Modify: the ticket card / flyout action row that already holds the Resolve / Reopen / Non-actionable buttons (grep `markResolved(` and `reopen(` under `webapp/src/components/` to locate — likely `components/ticket/TicketActions.vue` or `TicketCard.vue`).

- [ ] **Step 1: Create ParkMenu.vue (duration presets + reason select → emits `park`)**

```vue
<!-- Park action menu: pick a duration preset (or custom datetime) + a reason,
     emit `park(untilAtIso, reason)`. Used by the card/flyout action row and
     reused conceptually by BulkActionBar's inline menu. Roadmap 4.1. -->
<script setup lang="ts">
import { ref } from 'vue';
import type { ParkedReason } from '@/types/api';

const emit = defineEmits<{ (e: 'park', untilAt: string, reason: ParkedReason): void }>();

const presets: Array<{ label: string; minutes: number }> = [
  { label: '1h', minutes: 60 },
  { label: '4h', minutes: 240 },
  { label: '1d', minutes: 24 * 60 },
  { label: '3d', minutes: 3 * 24 * 60 },
];

const reasons: Array<{ value: ParkedReason; label: string }> = [
  { value: 'waiting_on_customer', label: 'Waiting on customer' },
  { value: 'waiting_on_third_party', label: 'Waiting on third party' },
  { value: 'waiting_internal', label: 'Waiting (internal)' },
  { value: 'other', label: 'Other' },
];

const reason = ref<ParkedReason>('waiting_on_customer');
const customAt = ref('');

function emitPreset(minutes: number) {
  emit('park', new Date(Date.now() + minutes * 60_000).toISOString(), reason.value);
}
function emitCustom() {
  if (!customAt.value) return;
  const iso = new Date(customAt.value).toISOString();
  if (Date.parse(iso) <= Date.now()) return; // backend also rejects past times (422)
  emit('park', iso, reason.value);
}
</script>

<template>
  <div class="park-menu" role="menu">
    <label class="label">Reason</label>
    <select v-model="reason" class="reason">
      <option v-for="r in reasons" :key="r.value" :value="r.value">{{ r.label }}</option>
    </select>
    <label class="label">Until</label>
    <div class="presets">
      <button
        v-for="p in presets"
        :key="p.label"
        type="button"
        class="preset mono"
        role="menuitem"
        @click="emitPreset(p.minutes)"
      >
        +{{ p.label }}
      </button>
    </div>
    <div class="custom">
      <input v-model="customAt" type="datetime-local" class="custom-input" />
      <button type="button" class="preset" :disabled="!customAt" @click="emitCustom">Set</button>
    </div>
  </div>
</template>

<style scoped>
.park-menu {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  min-width: 200px;
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: 4px;
  box-shadow: var(--shadow);
}
.label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-3);
}
.reason,
.custom-input {
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  background: var(--bg);
  border: var(--hairline) solid var(--line);
  border-radius: 4px;
  padding: 4px 6px;
}
.presets {
  display: flex;
  gap: 4px;
}
.preset {
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  background: transparent;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 4px 8px;
  cursor: pointer;
}
.preset:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.preset:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.custom {
  display: flex;
  gap: 4px;
  align-items: center;
}
</style>
```

- [ ] **Step 2: Wire the trigger into the existing action row**

Locate the component holding the Resolve/Reopen buttons (grep result from above). Add a "Park ▾" toggle + a reason/preset popover that mounts `ParkMenu`, and an Unpark button shown when the ticket is parked. Pattern (adapt names to the host component's store binding + open-state ref):

```vue
<!-- in <script setup>: -->
import ParkMenu from '@/components/ParkMenu.vue';
import type { ParkedReason } from '@/types/api';
const parkOpen = ref(false);
function onPark(untilAt: string, reason: ParkedReason) {
  parkOpen.value = false;
  void tickets.parkTicket(props.ticket.id, untilAt, reason);
}

<!-- in <template>, alongside the Resolve button, only when the ticket is OPEN: -->
<template v-if="props.ticket.resolved_at === null">
  <div v-if="props.ticket.parked_at === null" class="park-wrap">
    <button type="button" @click="parkOpen = !parkOpen">Park ▾</button>
    <ParkMenu v-if="parkOpen" @park="onPark" />
  </div>
  <button v-else type="button" @click="tickets.unparkTicket(props.ticket.id)">Unpark</button>
</template>
```

> The host component already imports `useTicketsStore()`; reuse that binding (named `tickets` in most components). If it doesn't, add `const tickets = useTicketsStore();`.

- [ ] **Step 3: (Optional but recommended) show parked status on the card**

Where the resolution chip / followup chip renders on the card, add a parked chip when `parked_at !== null`: show the reason + a relative countdown ("ready in 3h" / "★ ready" when `parked_until <= now`). Reuse the existing chip styling. This is presentation-only; verify against `DESIGN.md`.

- [ ] **Step 4: Verify**

Run: `npm --prefix webapp run lint && npm --prefix webapp run typecheck`
Then `npm run dev`: park an open ticket via the menu → it leaves its column, the Topbar parked chip count increments, toggling the chip shows it; unpark returns it to its column. Set a custom past datetime → button stays effectively disabled / no-op (backend would 422).

- [ ] **Step 5: Commit**

```bash
git add webapp/src/components/ParkMenu.vue <the-modified-action-component>
git commit -m "feat(4.1): park action menu + card trigger + unpark"
```

---

### Task 12: BulkActionBar — Park / Unpark

**Files:**
- Modify: `webapp/src/components/BulkActionBar.vue`

- [ ] **Step 1: Add a Park dropdown + an Unpark button**

In `<script setup>`, add computeds + handlers near the others (line 36-47, 124-150). Mirror the existing `noneResolved`/`onResolve` pattern. Add:

```ts
import ParkMenu from './ParkMenu.vue';
import type { ParkedReason } from '@/types/api';

const parkOpen = ref(false);
const noneParked = computed(
  () => selectedTickets.value.length > 0 && selectedTickets.value.every((t) => t.parked_at === null),
);
const anyParked = computed(() => selectedTickets.value.some((t) => t.parked_at !== null));

function onPark(untilAt: string, reason: ParkedReason) {
  parkOpen.value = false;
  void runBulk(() => tickets.bulkPark(selection.asArray(), untilAt, reason), 'parked');
}
function onUnpark() {
  void runBulk(() => tickets.bulkUnpark(selection.asArray()), 'unparked');
}
```

In the template, after the Reopen button (line 201), add (the Park dropdown is only enabled when none of the selection is resolved — you cannot park a resolved ticket):

```html
<div class="dropdown">
  <button
    type="button"
    :disabled="busy || !noneResolved || !noneParked"
    :title="noneResolved ? 'Park selected' : 'Some selected are already resolved'"
    @click="parkOpen = !parkOpen"
  >
    Park ▾
  </button>
  <div v-if="parkOpen" class="menu" role="menu">
    <ParkMenu @park="onPark" />
  </div>
</div>

<button
  type="button"
  :disabled="busy || !anyParked"
  :title="anyParked ? 'Unpark selected' : 'None of the selected are parked'"
  @click="onUnpark"
>
  Unpark
</button>
```

- [ ] **Step 2: Verify**

Run: `npm --prefix webapp run lint && npm --prefix webapp run typecheck && npx vitest run src/components/BulkActionBar.spec.ts`
Expected: clean/green (extend the spec if it asserts button counts). Then `npm run dev`: select several open tickets → Park → they leave the columns; select parked → Unpark.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/components/BulkActionBar.vue webapp/src/components/BulkActionBar.spec.ts
git commit -m "feat(4.1): bulk Park / Unpark in BulkActionBar"
```

- [ ] **Step 4: Run the full webapp gate**

Run: `npm --prefix webapp run lint && npm --prefix webapp run format:check && npm --prefix webapp run typecheck && npm --prefix webapp run test && npm --prefix webapp run build`
Expected: all green.

---

### Task 13: Extension api.js — parkTicket / unparkTicket

**Files:**
- Modify: `extension/api.js` (after `markNonActionable` ~line 71)

- [ ] **Step 1: Add the exports (match the existing `encodeURIComponent` + JSDoc style)**

```js
/** Park a ticket until `untilAt` (ISO with Z) with a structured reason.
 *  409 if resolved or already parked. */
export const parkTicket = (ticketId, untilAt, reason) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/park`, {
    method: 'POST',
    body: JSON.stringify({ until_at: untilAt, reason }),
  });

/** Unpark a ticket. 409 if not parked, 404 if unknown. */
export const unparkTicket = (ticketId) =>
  request(`/tickets/${encodeURIComponent(ticketId)}/unpark`, { method: 'POST' });
```

- [ ] **Step 2: Verify (no build step — syntax only)**

Run: `node --check extension/api.js`
Expected: no output (valid).

- [ ] **Step 3: Commit**

```bash
git add extension/api.js
git commit -m "feat(4.1): extension api.js park/unpark"
```

---

### Task 14: Extension popup — Parked tab + buttons

**Files:**
- Modify: `extension/popup.js`

> **Executor:** read `popup.js` first to match its exact `state`, tab constants, `node()` helper, and `render*` functions (documented in `extension/CLAUDE.md` → "Popup state model"). The additions below follow the documented Resolved-tab pattern; adapt identifiers to the real code.

- [ ] **Step 1: Import the new api calls**

At the top import from `./api.js`, add `parkTicket, unparkTicket` to the existing import list.

- [ ] **Step 2: Add a Parked tab**

Where the tab constants / tab list are defined (alongside the Resolved / Non-actionable tabs), add a `parked` tab. Its list is derived from the already-fetched open `state.tickets`:

```js
// parked tickets ride in the open board fetch (resolved_at === null).
const parkedList = state.tickets.filter((t) => t.parked_at !== null && t.resolved_at === null);
```

Render it under the `parked` tab using the same card builder as the other tabs. The tab label shows the count; if any `parked_until <= Date.now()` show a "★ ready" marker (use `state.now` if the 1Hz tick maintains it).

- [ ] **Step 3: Add Park / Unpark buttons on cards**

In the per-card action builder, when rendering an OPEN ticket (`resolved_at === null`):
- if `parked_at === null`: add a "Park" control. Keep it simple given the popup's minimal DOM — a small `<select>` of reasons + preset duration buttons (1h/1d), or a single default ("waiting_on_customer", +1d) Park button to avoid cramped UI. On click: `await parkTicket(t.id, new Date(Date.now() + 24*60*60*1000).toISOString(), reason); await reloadBoard();` (reuse whatever the popup's existing resolve handler calls to refetch + re-render).
- if `parked_at !== null`: add an "Unpark" button → `await unparkTicket(t.id); await reloadBoard();`

Follow the exact pattern of the existing Resolve button handler (which calls `resolveTicket(id)` then refetches). Errors: mirror the existing handler's try/catch (popup surfaces `ApiError.message`).

- [ ] **Step 4: Verify (manual — no extension test suite)**

`chrome://extensions` → reload unpacked → open popup → Sync → confirm: tickets render, Park on an open ticket moves it to the Parked tab, Unpark returns it, no console errors, badge count unaffected. (Per `extension/CLAUDE.md` §4 verification table.)

- [ ] **Step 5: Commit**

```bash
git add extension/popup.js
git commit -m "feat(4.1): extension popup Parked tab + park/unpark buttons"
```

---

### Task 15: Docs — spec.md / plan.md / tasks.md / CLAUDE.md

**Files:**
- Modify: `spec.md`, `plan.md`, `tasks.md`, `CLAUDE.md`

> Per root `CLAUDE.md`: "Don't extend the surface area without spec.md / plan.md / tasks.md updates." Do these as one docs commit.

- [ ] **Step 1: spec.md** — add a requirement for the parked state. Add an `FR-0xx` (next free number) describing: operator parks an open ticket with a wake time + structured reason; parked tickets leave the live queue; "ready" is derived when the wake time passes; manual unpark; not both parked and resolved. Add a `US-0xx` user story ("As the operator, I park a ticket waiting on the customer so it leaves my queue until I expect a reply"). Reference T106.

- [ ] **Step 2: plan.md** — under the data-model / resolution section, note the parallel parked state: three columns, the three CheckConstraints, the "every resolve path calls `clear_parked`" rule, and that "ready" is derived (no scheduler). Note the four routes + bulk.

- [ ] **Step 3: tasks.md** — mark **T106** with its implementation footprint and add a traceability row mapping T106 → the new FR/US, listing the touched files across the three packages.

- [ ] **Step 4: CLAUDE.md (root)** — extend the cross-package invariants list: add a parked-state invariant (e.g. #14) — "Parked is board-state on `TicketSchema` (not `HydratedTicket`); the trio is XOR-locked; every resolve path clears it; `ready` is derived, never stored; `_upsert_ticket` never writes parked so it's sticky by construction." Mirror the phrasing/format of the existing invariants.

- [ ] **Step 5: Commit**

```bash
git add spec.md plan.md tasks.md CLAUDE.md
git commit -m "docs(4.1): spec/plan/tasks/invariants for parked state (T106)"
```

---

### Task 16: Cross-package gate + finish the branch

- [ ] **Step 1: Backend gate**

Run (from `backend/`, venv active): `ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
Expected: all green; note the pass count.

- [ ] **Step 2: Webapp gate**

Run: `npm --prefix webapp run lint && npm --prefix webapp run format:check && npm --prefix webapp run typecheck && npm --prefix webapp run test && npm --prefix webapp run build`
Expected: all green.

- [ ] **Step 3: Extension manual checklist**

`chrome://extensions` → reload unpacked → Sync → park/unpark single tickets in the popup → no console errors. (`/qa-extension`.)

- [ ] **Step 4: Migration round-trip sanity**

Run (from `backend/`): `alembic upgrade head && alembic downgrade -1 && alembic upgrade head`
Expected: clean up/down/up (0017 ⇄ 0018).

- [ ] **Step 5: Merge the branch (one PR across all three packages)**

```bash
git checkout main
git merge --no-ff feat/4.1-parked-state -m "Merge feat/4.1-parked-state: parked/snoozed ticket state (roadmap 4.1, T106)"
git branch -d feat/4.1-parked-state
```

Re-run the backend + webapp gates on `main` after the merge before declaring done.

---

## Self-review (run before handing off)

**Spec coverage:** every spec section maps to a task — data model §1 → T1; API §2 → T3/T4/T5; contract §3 → T2/T7/T8 (+stickiness T6); webapp UI §4 → T9/T10/T11/T12; extension §5 → T13/T14; error handling §6 → T3/T5 tests; testing §7 → per-task tests + T16 gates; docs §8 → T15. ✅

**Type/name consistency:** `ParkedReason` (schemas.py Literal ↔ types/api.ts union ↔ api client param); `clear_parked` / `apply_park` / `apply_unpark` / `park` / `unpark` used identically across resolution.py, bulk.py, router, tickets.py; `parkTicket`/`unparkTicket`/`bulkPark`/`bulkUnpark` consistent across client.ts ↔ store ↔ api.js; `parkedOnly`/`parkedTickets`/`readyParkedCount` consistent store ↔ Topbar. ✅

**Placeholders:** Tasks 11 and 14 require the executor to read one host file (the card/flyout action row; `popup.js`) to place a trigger — the new components/handlers are given in full; only the mount-point identifiers are environment-bound. Flagged inline. ✅

# Time-tabled Notes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-textarea per-ticket scratchpad with an append-only timestamped log; each entry may optionally carry a timer that drives the existing `followups` alarm loop.

**Architecture:** New `note_entries` table sits alongside the unchanged `ticket_notes` (legacy scratchpad) and `followups` (alarm loop) tables. Service-layer entry creation upserts the `followups` row in the same transaction when `timer_min` is set, so the existing client-side alarm/banner/bucket-board code keeps working without modification. Frontend adds a parallel `useNoteEntriesStore` and rewrites the `Next-step notes` section of the flyout into a timeline + new-entry form.

**Tech Stack:** Python 3.11 + FastAPI + SQLAlchemy 2.x async + Alembic + pytest-asyncio (backend); Vue 3 + Pinia + Vitest + TypeScript (webapp).

**Spec:** `docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md`

---

## File Structure

**Backend — new:**
- `backend/alembic/versions/0008_add_note_entries.py` — create `note_entries` table + indices.
- `backend/app/services/note_entries.py` — CRUD + timer→followup soft-link service.
- `backend/app/routers/note_entries.py` — REST endpoints under `/notes/entries`.
- `backend/tests/test_note_entries_service.py` — service-level tests against in-memory DB.
- `backend/tests/test_note_entries_api.py` — endpoint tests via httpx AsyncClient.

**Backend — modify:**
- `backend/app/models.py` — add `NoteEntry` ORM model.
- `backend/app/schemas.py` — add `NoteEntryRead`, `NoteEntryCreate`, `NoteEntryDeleted`.
- `backend/app/main.py` — register the new router.

**Webapp — new:**
- `webapp/src/stores/noteEntries.ts` — Pinia store with optimistic add/delete + soft-link awareness.
- `webapp/src/stores/noteEntries.spec.ts` — store unit tests.

**Webapp — modify:**
- `webapp/src/types/api.ts` — add `NoteEntry` interface.
- `webapp/src/api/client.ts` — add `listNoteEntries`, `addNoteEntry`, `deleteNoteEntry`.
- `webapp/src/App.vue` — load store on mount alongside existing `notes.load()`.
- `webapp/src/components/TicketFlyout.vue` — rewrite the `Next-step notes` section.
- `webapp/src/components/TicketCard.vue` — chip count = legacy + entries.
- `webapp/src/stores/notes.ts` — extend `countNoteLines` consumer (no signature change; chip caller does the add).

**Docs:**
- `README.md` — add `/notes/entries` rows to the API surface table.

Each backend file does one job: ORM, schemas, services, router. Each webapp file mirrors an existing sibling (e.g. `noteEntries.ts` mirrors `notes.ts`). No file grows past its current responsibility.

---

## Task 1: Add `NoteEntry` ORM model + Alembic migration

**Files:**
- Modify: `backend/app/models.py` (append after `TicketNote`, before `Ticket` — line 320ish)
- Create: `backend/alembic/versions/0008_add_note_entries.py`
- Create: `backend/tests/test_note_entries_service.py` (initial schema-only test)

- [ ] **Step 1: Write the failing test (schema smoke)**

Create `backend/tests/test_note_entries_service.py`:

```python
"""Service-level tests for note_entries (spec: time-tabled notes)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteEntry


@pytest.mark.asyncio
async def test_note_entry_model_persists(session: AsyncSession) -> None:
    """Insert a note_entry row + read it back."""
    row = NoteEntry(ticket_id="T1", body="investigating", timer_min=15, reason="bug")
    session.add(row)
    await session.commit()

    found = (await session.scalars(select(NoteEntry).where(NoteEntry.ticket_id == "T1"))).one()
    assert found.body == "investigating"
    assert found.timer_min == 15
    assert found.reason == "bug"
    assert found.deleted_at is None
    assert found.created_at is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_note_entries_service.py::test_note_entry_model_persists -v`

Expected: FAIL with `ImportError: cannot import name 'NoteEntry' from 'app.models'`.

- [ ] **Step 3: Add `NoteEntry` model**

Insert into `backend/app/models.py` immediately after the `TicketNote` class (around line 320, before `class Ticket`):

```python
class NoteEntry(Base):
    """A timestamped append-only entry on a ticket's investigation log.

    Replaces the freeform `ticket_notes.body` scratchpad with a log of
    `(timestamp, body)` items. Each entry may carry an optional timer
    (`timer_min`) and an optional `reason` that mirrors the wording on the
    follow-up row. Soft-linked to `followups` by `ticket_id`: when a new
    entry has `timer_min` set, the service upserts the matching `followups`
    row inside the same transaction.

    Append-only — corrections are new entries. `deleted_at` is a soft-delete
    for hard mistakes only.
    """

    __tablename__ = "note_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    timer_min: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("length(body) > 0", name="note_entries_body_nonempty"),
        CheckConstraint(
            "reason IS NULL OR length(reason) <= 80",
            name="note_entries_reason_len_check",
        ),
        CheckConstraint(
            "timer_min IS NULL OR (timer_min BETWEEN 1 AND 1440)",
            name="note_entries_timer_range_check",
        ),
        Index("ix_note_entries_ticket", "ticket_id"),
        Index("ix_note_entries_created", "created_at"),
    )
```

- [ ] **Step 4: Create the Alembic migration**

Create `backend/alembic/versions/0008_add_note_entries.py`:

```python
"""Add note_entries table (time-tabled notes spec).

Spec: docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-23 00:00:08.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "note_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("timer_min", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("length(body) > 0", name="note_entries_body_nonempty"),
        sa.CheckConstraint(
            "reason IS NULL OR length(reason) <= 80",
            name="note_entries_reason_len_check",
        ),
        sa.CheckConstraint(
            "timer_min IS NULL OR (timer_min BETWEEN 1 AND 1440)",
            name="note_entries_timer_range_check",
        ),
    )
    op.create_index("ix_note_entries_ticket", "note_entries", ["ticket_id"])
    op.create_index("ix_note_entries_created", "note_entries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_note_entries_created", table_name="note_entries")
    op.drop_index("ix_note_entries_ticket", table_name="note_entries")
    op.drop_table("note_entries")
```

- [ ] **Step 5: Run schema test to verify it passes**

Run: `cd backend && pytest tests/test_note_entries_service.py::test_note_entry_model_persists -v`

Expected: PASS.

- [ ] **Step 6: Run full test suite to make sure nothing else broke**

Run: `cd backend && pytest -q`

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0008_add_note_entries.py backend/tests/test_note_entries_service.py
git commit -m "feat(notes): add note_entries table + ORM model

Append-only log of per-ticket timestamped entries. Each entry may
carry an optional timer (timer_min) and reason. Migration 0008.
Spec: docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md"
```

---

## Task 2: Add Pydantic schemas

**Files:**
- Modify: `backend/app/schemas.py` (append after `NoteDeletedResponse`, around line 180)

- [ ] **Step 1: Add the schemas**

Append to `backend/app/schemas.py` immediately after `class NoteDeletedResponse` (around line 180), before the `# ── Tickets ──` divider:

```python
# ── Note entries (time-tabled notes) ─────────────────────────────────────────


class NoteEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticket_id: str
    body: str
    timer_min: int | None
    reason: str | None
    created_at: UTCDatetime


class NoteEntryCreate(BaseModel):
    """POST /notes/entries body. `body` required, timer + reason optional.

    `timer_min` set → service upserts the ticket's `followups` row in the
    same transaction. `reason` mirrors to `followups.reason` when timer set.
    """

    ticket_id: str = Field(min_length=1)
    body: str = Field(min_length=1)
    timer_min: int | None = Field(default=None, ge=1, le=1440)
    reason: str | None = Field(default=None, max_length=80)


class NoteEntryDeleted(BaseModel):
    ok: Literal[True] = True
    deleted: Literal[True] = True
    id: int
```

- [ ] **Step 2: Verify schemas compile**

Run: `cd backend && mypy app/schemas.py`

Expected: success (no errors).

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat(notes): add NoteEntry pydantic schemas"
```

---

## Task 3: Service layer — CRUD + atomic followup soft-link

**Files:**
- Create: `backend/app/services/note_entries.py`
- Modify: `backend/tests/test_note_entries_service.py`

- [ ] **Step 1: Write failing tests for the service**

Append to `backend/tests/test_note_entries_service.py`:

```python
from datetime import timedelta

from app.models import Followup
from app.services import followups as followups_svc
from app.services import note_entries as svc
from app.util import naive_utcnow


@pytest.mark.asyncio
async def test_add_entry_without_timer_does_not_create_followup(session: AsyncSession) -> None:
    entry = await svc.add_entry(session, ticket_id="T1", body="note only")
    assert entry.id is not None
    assert entry.timer_min is None

    fu = await session.get(Followup, "T1")
    assert fu is None


@pytest.mark.asyncio
async def test_add_entry_with_timer_upserts_followup(session: AsyncSession) -> None:
    before = naive_utcnow()
    entry = await svc.add_entry(
        session,
        ticket_id="T1",
        body="investigating",
        timer_min=15,
        reason="check retry policy",
    )
    assert entry.timer_min == 15

    fu = await session.get(Followup, "T1")
    assert fu is not None
    assert fu.reason == "check retry policy"
    assert fu.fired is False
    expected_due = before + timedelta(minutes=15)
    # Allow a generous skew — the service uses its own `naive_utcnow()`.
    assert abs((fu.due_at - expected_due).total_seconds()) < 5


@pytest.mark.asyncio
async def test_new_timer_entry_overwrites_prior_followup(session: AsyncSession) -> None:
    await svc.add_entry(session, ticket_id="T1", body="first", timer_min=5, reason="r1")
    fu_first = await session.get(Followup, "T1")
    assert fu_first is not None
    first_due = fu_first.due_at

    await svc.add_entry(session, ticket_id="T1", body="second", timer_min=60, reason="r2")
    await session.refresh(fu_first)
    assert fu_first.reason == "r2"
    assert fu_first.due_at > first_due  # 60m > 5m so new due_at is strictly later


@pytest.mark.asyncio
async def test_list_for_ticket_returns_asc_by_created_at(session: AsyncSession) -> None:
    await svc.add_entry(session, ticket_id="T1", body="a")
    await svc.add_entry(session, ticket_id="T1", body="b")
    await svc.add_entry(session, ticket_id="T2", body="x")

    rows = await svc.list_for_ticket(session, "T1")
    assert [r.body for r in rows] == ["a", "b"]


@pytest.mark.asyncio
async def test_list_all_excludes_soft_deleted(session: AsyncSession) -> None:
    e1 = await svc.add_entry(session, ticket_id="T1", body="kept")
    e2 = await svc.add_entry(session, ticket_id="T1", body="gone")
    await svc.soft_delete(session, e2.id)

    rows = await svc.list_all(session)
    assert {r.id for r in rows} == {e1.id}


@pytest.mark.asyncio
async def test_soft_delete_missing_id_raises_404(session: AsyncSession) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.soft_delete(session, 99999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_add_entry_rejects_empty_body(session: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await svc.add_entry(session, ticket_id="T1", body="")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_note_entries_service.py -v`

Expected: ImportError or AttributeError on `app.services.note_entries`.

- [ ] **Step 3: Create the service module**

Create `backend/app/services/note_entries.py`:

```python
"""Note entries — append-only per-ticket investigation log.

Spec: docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md

`add_entry` is the only mutation that touches `followups`: when `timer_min`
is set, it upserts the row inside the same transaction. The existing
`followups.apply_set_followup` is reused — it mutates the row but does not
commit, so this service controls atomicity.

Soft-deletes use `deleted_at`; entries are otherwise immutable.
"""

from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import NoteEntry
from app.services import followups as followups_svc
from app.util import naive_utcnow


async def list_all(session: AsyncSession) -> list[NoteEntry]:
    """Every non-deleted entry, asc by created_at. Used to seed the frontend store."""
    stmt = (
        select(NoteEntry)
        .where(NoteEntry.deleted_at.is_(None))
        .order_by(NoteEntry.created_at.asc(), NoteEntry.id.asc())
    )
    return list((await session.scalars(stmt)).all())


async def list_for_ticket(session: AsyncSession, ticket_id: str) -> list[NoteEntry]:
    """Non-deleted entries for one ticket, asc by created_at."""
    stmt = (
        select(NoteEntry)
        .where(NoteEntry.ticket_id == ticket_id, NoteEntry.deleted_at.is_(None))
        .order_by(NoteEntry.created_at.asc(), NoteEntry.id.asc())
    )
    return list((await session.scalars(stmt)).all())


async def add_entry(
    session: AsyncSession,
    ticket_id: str,
    body: str,
    timer_min: int | None = None,
    reason: str | None = None,
) -> NoteEntry:
    """Insert a new entry. When `timer_min` is set, upsert the ticket's
    `followups` row inside the same transaction. Latest timer entry wins."""
    entry = NoteEntry(
        ticket_id=ticket_id,
        body=body,
        timer_min=timer_min,
        reason=reason,
        created_at=naive_utcnow(),
    )
    session.add(entry)

    if timer_min is not None:
        due_at = naive_utcnow() + timedelta(minutes=timer_min)
        await followups_svc.apply_set_followup(session, ticket_id, due_at, reason)

    await session.commit()
    await session.refresh(entry)
    metrics.incr("note_entries_added_total")
    if timer_min is not None:
        metrics.incr("note_entries_added_with_timer_total")
    return entry


async def soft_delete(session: AsyncSession, entry_id: int) -> NoteEntry:
    """Stamp `deleted_at`. Idempotent on a row already deleted."""
    row = await session.get(NoteEntry, entry_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no note entry {entry_id}")
    if row.deleted_at is None:
        row.deleted_at = naive_utcnow()
        await session.commit()
        await session.refresh(row)
        metrics.incr("note_entries_deleted_total")
    return row
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && pytest tests/test_note_entries_service.py -v`

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/note_entries.py backend/tests/test_note_entries_service.py
git commit -m "feat(notes): note_entries service with atomic followup soft-link"
```

---

## Task 4: REST router for `/notes/entries`

**Files:**
- Create: `backend/app/routers/note_entries.py`
- Create: `backend/tests/test_note_entries_api.py`

- [ ] **Step 1: Write the failing API tests**

Create `backend/tests/test_note_entries_api.py`:

```python
"""HTTP tests for /notes/entries (time-tabled notes spec)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_post_entry_minimal_body(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "investigating"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ticket_id"] == "T1"
    assert payload["body"] == "investigating"
    assert payload["timer_min"] is None
    assert payload["reason"] is None
    assert "id" in payload
    assert "created_at" in payload


@pytest.mark.asyncio
async def test_post_entry_with_timer_creates_followup(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={
            "ticket_id": "T1",
            "body": "investigating timeout",
            "timer_min": 15,
            "reason": "check retry policy",
        },
    )
    assert resp.status_code == 200

    fu_resp = await client.get("/followups")
    fus = fu_resp.json()
    assert len(fus) == 1
    assert fus[0]["ticket_id"] == "T1"
    assert fus[0]["reason"] == "check retry policy"
    assert fus[0]["fired"] is False


@pytest.mark.asyncio
async def test_post_entry_with_timer_overrides_prior_followup(client: AsyncClient) -> None:
    await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "first", "timer_min": 5, "reason": "r1"},
    )
    await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "second", "timer_min": 60, "reason": "r2"},
    )

    fus = (await client.get("/followups")).json()
    assert len(fus) == 1
    assert fus[0]["reason"] == "r2"


@pytest.mark.asyncio
async def test_get_entries_filtered_by_ticket(client: AsyncClient) -> None:
    await client.post("/notes/entries", json={"ticket_id": "T1", "body": "a"})
    await client.post("/notes/entries", json={"ticket_id": "T1", "body": "b"})
    await client.post("/notes/entries", json={"ticket_id": "T2", "body": "x"})

    t1 = (await client.get("/notes/entries/T1")).json()
    assert [r["body"] for r in t1] == ["a", "b"]

    t2 = (await client.get("/notes/entries/T2")).json()
    assert [r["body"] for r in t2] == ["x"]


@pytest.mark.asyncio
async def test_get_all_excludes_soft_deleted(client: AsyncClient) -> None:
    e = (await client.post("/notes/entries", json={"ticket_id": "T1", "body": "gone"})).json()
    await client.post("/notes/entries", json={"ticket_id": "T1", "body": "kept"})
    await client.delete(f"/notes/entries/{e['id']}")

    rows = (await client.get("/notes/entries")).json()
    assert [r["body"] for r in rows] == ["kept"]


@pytest.mark.asyncio
async def test_delete_returns_envelope(client: AsyncClient) -> None:
    e = (await client.post("/notes/entries", json={"ticket_id": "T1", "body": "x"})).json()
    resp = await client.delete(f"/notes/entries/{e['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True, "id": e["id"]}


@pytest.mark.asyncio
async def test_delete_missing_returns_404(client: AsyncClient) -> None:
    resp = await client.delete("/notes/entries/99999")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_rejects_empty_body(client: AsyncClient) -> None:
    resp = await client.post("/notes/entries", json={"ticket_id": "T1", "body": ""})
    assert resp.status_code == 422  # pydantic Field(min_length=1)


@pytest.mark.asyncio
async def test_post_rejects_reason_too_long(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "x", "timer_min": 15, "reason": "a" * 81},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_rejects_timer_out_of_range(client: AsyncClient) -> None:
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "x", "timer_min": 0},
    )
    assert resp.status_code == 422
    resp = await client.post(
        "/notes/entries",
        json={"ticket_id": "T1", "body": "x", "timer_min": 1441},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && pytest tests/test_note_entries_api.py -v`

Expected: 404s on `/notes/entries` — router not registered yet.

- [ ] **Step 3: Create the router**

Create `backend/app/routers/note_entries.py`:

```python
"""Note-entries endpoints — time-tabled notes spec.

Spec: docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import NoteEntryCreate, NoteEntryDeleted, NoteEntryRead
from app.services import note_entries as svc

router = APIRouter(prefix="/notes/entries", tags=["notes"])


@router.get("", response_model=list[NoteEntryRead])
async def list_entries(session: AsyncSession = Depends(get_session)) -> list[NoteEntryRead]:
    """Every non-deleted entry, asc by created_at. Used to seed the store."""
    rows = await svc.list_all(session)
    return [NoteEntryRead.model_validate(row) for row in rows]


@router.get("/{ticket_id}", response_model=list[NoteEntryRead])
async def list_entries_for_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[NoteEntryRead]:
    """Non-deleted entries for one ticket, asc by created_at."""
    rows = await svc.list_for_ticket(session, ticket_id)
    return [NoteEntryRead.model_validate(row) for row in rows]


@router.post("", response_model=NoteEntryRead)
async def create_entry(
    body: NoteEntryCreate,
    session: AsyncSession = Depends(get_session),
) -> NoteEntryRead:
    """Insert a new entry. When `timer_min` set, upserts the ticket's
    follow-up row in the same transaction (latest timer entry wins)."""
    row = await svc.add_entry(
        session,
        ticket_id=body.ticket_id,
        body=body.body,
        timer_min=body.timer_min,
        reason=body.reason,
    )
    return NoteEntryRead.model_validate(row)


@router.delete("/{entry_id}", response_model=NoteEntryDeleted)
async def delete_entry(
    entry_id: int,
    session: AsyncSession = Depends(get_session),
) -> NoteEntryDeleted:
    """Soft-delete (sets `deleted_at`). Idempotent on a row already deleted."""
    row = await svc.soft_delete(session, entry_id)
    return NoteEntryDeleted(id=row.id)
```

- [ ] **Step 4: Register the router in main.py**

Modify `backend/app/main.py`. Find the import block (around line 27-33) and add:

```python
from app.routers import note_entries as note_entries_router
```

Then locate where `notes_router` is included (search for `app.include_router(notes_router.router)` — likely inside `create_app()`). Add immediately after it:

```python
    app.include_router(note_entries_router.router)
```

- [ ] **Step 5: Run API tests to verify they pass**

Run: `cd backend && pytest tests/test_note_entries_api.py -v`

Expected: all 10 tests pass.

- [ ] **Step 6: Run full backend test suite + quality gates**

Run:
```bash
cd backend
ruff check app tests && ruff format --check app tests
mypy app
pytest -q
```

Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/note_entries.py backend/app/main.py backend/tests/test_note_entries_api.py
git commit -m "feat(notes): /notes/entries router (list, list-for-ticket, post, delete)"
```

---

## Task 5: Webapp types + API client

**Files:**
- Modify: `webapp/src/types/api.ts`
- Modify: `webapp/src/api/client.ts`

- [ ] **Step 1: Add the `NoteEntry` type**

Add to `webapp/src/types/api.ts` immediately after the `TicketNote` interface (around line 78):

```typescript
export interface NoteEntry {
  id: number;
  ticket_id: string;
  body: string;
  timer_min: number | null;
  reason: string | null;
  created_at: string;
}
```

- [ ] **Step 2: Add API client methods**

Modify `webapp/src/api/client.ts`:

Add `NoteEntry` to the imports at the top:
```typescript
import type {
  BulkResult,
  CategoriesResponse,
  Category,
  FilterSettings,
  Followup,
  NoteEntry,
  ProposalsResponse,
  ResolvedSource,
  Ticket,
  TicketNote,
} from '@/types/api';
```

Inside the `api` object, immediately after the `// ── notes (T047) ──` block (after `putNote`), add:

```typescript
  // ── note entries (time-tabled notes) ──────────────────────────────────────
  listNoteEntries: (): Promise<NoteEntry[]> => request('/notes/entries'),

  listNoteEntriesForTicket: (ticketId: string): Promise<NoteEntry[]> =>
    request(`/notes/entries/${ticketId}`),

  addNoteEntry: (body: {
    ticket_id: string;
    body: string;
    timer_min?: number | null;
    reason?: string | null;
  }): Promise<NoteEntry> =>
    request('/notes/entries', { method: 'POST', body: JSON.stringify(body) }),

  deleteNoteEntry: (entryId: number): Promise<{ ok: true; deleted: true; id: number }> =>
    request(`/notes/entries/${entryId}`, { method: 'DELETE' }),
```

- [ ] **Step 3: Typecheck**

Run: `cd webapp && npm run typecheck`

Expected: success.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/types/api.ts webapp/src/api/client.ts
git commit -m "feat(notes): webapp NoteEntry type + API client methods"
```

---

## Task 6: Pinia `noteEntries` store with optimistic add/delete

**Files:**
- Create: `webapp/src/stores/noteEntries.ts`
- Create: `webapp/src/stores/noteEntries.spec.ts`

- [ ] **Step 1: Write failing store tests**

Create `webapp/src/stores/noteEntries.spec.ts`:

```typescript
// Time-tabled notes store unit tests.

import { beforeEach, describe, expect, it, vi, afterEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useNoteEntriesStore } from './noteEntries';
import { api } from '@/api/client';
import type { NoteEntry } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listNoteEntries: vi.fn(),
    addNoteEntry: vi.fn(),
    deleteNoteEntry: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function makeEntry(over: Partial<NoteEntry> = {}): NoteEntry {
  return {
    id: 1,
    ticket_id: 'T1',
    body: 'a',
    timer_min: null,
    reason: null,
    created_at: '2026-05-23T10:00:00Z',
    ...over,
  };
}

describe('noteEntriesStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('load() seeds map keyed by ticket_id with chronological arrays', async () => {
    mocked.listNoteEntries.mockResolvedValue([
      makeEntry({ id: 1, ticket_id: 'T1', body: 'first' }),
      makeEntry({ id: 2, ticket_id: 'T1', body: 'second' }),
      makeEntry({ id: 3, ticket_id: 'T2', body: 'other' }),
    ]);
    const s = useNoteEntriesStore();
    await s.load();
    expect(s.entriesOf('T1').map((e) => e.body)).toEqual(['first', 'second']);
    expect(s.entriesOf('T2').map((e) => e.body)).toEqual(['other']);
    expect(s.countOf('T1')).toBe(2);
    expect(s.countOf('missing')).toBe(0);
  });

  it('load() falls back to empty on backend error', async () => {
    mocked.listNoteEntries.mockRejectedValue(new Error('boom'));
    const s = useNoteEntriesStore();
    await s.load();
    expect(s.entriesOf('T1')).toEqual([]);
  });

  it('addEntry() optimistically appends then replaces with server row', async () => {
    const saved = makeEntry({ id: 42, body: 'saved', created_at: '2026-05-23T10:01:00Z' });
    mocked.addNoteEntry.mockResolvedValue(saved);

    const s = useNoteEntriesStore();
    const pending = s.addEntry('T1', 'saved', 15, 'reason');

    // optimistic row visible before await resolves
    expect(s.entriesOf('T1').map((e) => e.body)).toEqual(['saved']);
    expect(s.entriesOf('T1')[0].id).toBeLessThan(0); // temp negative id

    await pending;
    expect(s.entriesOf('T1').map((e) => e.id)).toEqual([42]);
  });

  it('addEntry() rolls back when the server rejects', async () => {
    mocked.addNoteEntry.mockRejectedValue(new Error('500'));
    const s = useNoteEntriesStore();
    await expect(s.addEntry('T1', 'oops')).rejects.toThrow();
    expect(s.entriesOf('T1')).toEqual([]);
  });

  it('deleteEntry() removes the row optimistically and rolls back on failure', async () => {
    const e = makeEntry({ id: 7, ticket_id: 'T1' });
    mocked.listNoteEntries.mockResolvedValue([e]);
    const s = useNoteEntriesStore();
    await s.load();

    mocked.deleteNoteEntry.mockRejectedValue(new Error('500'));
    await expect(s.deleteEntry(7)).rejects.toThrow();
    expect(s.entriesOf('T1').map((x) => x.id)).toEqual([7]);
  });

  it('deleteEntry() succeeds and the row is gone', async () => {
    const e = makeEntry({ id: 7, ticket_id: 'T1' });
    mocked.listNoteEntries.mockResolvedValue([e]);
    const s = useNoteEntriesStore();
    await s.load();

    mocked.deleteNoteEntry.mockResolvedValue({ ok: true, deleted: true, id: 7 });
    await s.deleteEntry(7);
    expect(s.entriesOf('T1')).toEqual([]);
    expect(s.countOf('T1')).toBe(0);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && npx vitest run src/stores/noteEntries.spec.ts`

Expected: module-not-found on `./noteEntries`.

- [ ] **Step 3: Create the store**

Create `webapp/src/stores/noteEntries.ts`:

```typescript
// Time-tabled notes store. Spec:
// docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md
//
// Append-only per-ticket investigation log. `load()` seeds from
// `GET /notes/entries`; `addEntry` is optimistic and replaces the temp row
// with the server-issued id on success. The matching follow-up upsert
// happens server-side inside the same transaction — this store does not
// touch the followups store. The flyout reads the active followup directly
// from `useFollowupsStore` so the bucket-board view stays consistent.

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { NoteEntry } from '@/types/api';

export const useNoteEntriesStore = defineStore('noteEntries', () => {
  /** ticket_id → asc-by-created_at array of non-deleted entries. */
  const map = ref<Record<string, NoteEntry[]>>({});

  /** Monotonically decreasing temp id for optimistic rows; replaced on save. */
  let nextTempId = -1;

  function entriesOf(ticketId: string): NoteEntry[] {
    return map.value[ticketId] ?? [];
  }

  function countOf(ticketId: string): number {
    return entriesOf(ticketId).length;
  }

  async function load() {
    try {
      const rows = await api.listNoteEntries();
      const grouped: Record<string, NoteEntry[]> = {};
      for (const r of rows) {
        (grouped[r.ticket_id] ??= []).push(r);
      }
      // server returns asc by created_at already; no client-side sort needed.
      map.value = grouped;
    } catch {
      map.value = {};
    }
  }

  async function addEntry(
    ticketId: string,
    body: string,
    timerMin: number | null = null,
    reason: string | null = null,
  ): Promise<NoteEntry> {
    const tempId = nextTempId--;
    const optimistic: NoteEntry = {
      id: tempId,
      ticket_id: ticketId,
      body,
      timer_min: timerMin,
      reason,
      created_at: new Date().toISOString(),
    };
    const prior = entriesOf(ticketId);
    map.value = { ...map.value, [ticketId]: [...prior, optimistic] };

    try {
      const saved = await api.addNoteEntry({
        ticket_id: ticketId,
        body,
        timer_min: timerMin,
        reason,
      });
      const replaced = entriesOf(ticketId).map((e) => (e.id === tempId ? saved : e));
      map.value = { ...map.value, [ticketId]: replaced };
      return saved;
    } catch (e) {
      const reverted = entriesOf(ticketId).filter((x) => x.id !== tempId);
      map.value = { ...map.value, [ticketId]: reverted };
      throw e;
    }
  }

  async function deleteEntry(entryId: number): Promise<void> {
    // Locate the row across all tickets — entry ids are unique server-side.
    let ticketId: string | null = null;
    let snapshot: NoteEntry[] | null = null;
    for (const [tid, list] of Object.entries(map.value)) {
      if (list.some((e) => e.id === entryId)) {
        ticketId = tid;
        snapshot = list;
        break;
      }
    }
    if (ticketId === null || snapshot === null) return;

    map.value = {
      ...map.value,
      [ticketId]: snapshot.filter((e) => e.id !== entryId),
    };

    try {
      await api.deleteNoteEntry(entryId);
    } catch (e) {
      map.value = { ...map.value, [ticketId]: snapshot };
      throw e;
    }
  }

  return { entriesOf, countOf, load, addEntry, deleteEntry };
});
```

- [ ] **Step 4: Run store tests to verify they pass**

Run: `cd webapp && npx vitest run src/stores/noteEntries.spec.ts`

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/stores/noteEntries.ts webapp/src/stores/noteEntries.spec.ts
git commit -m "feat(notes): noteEntries Pinia store with optimistic add/delete"
```

---

## Task 7: Load `noteEntries` store on app mount + update card chip count

**Files:**
- Modify: `webapp/src/App.vue`
- Modify: `webapp/src/components/TicketCard.vue`

- [ ] **Step 1: Wire the store load in App.vue**

Modify `webapp/src/App.vue`:

Add to the imports near line 20 (alongside `useNotesStore`):
```typescript
import { useNoteEntriesStore } from '@/stores/noteEntries';
```

Add to the store instantiation around line 32 (after `const notes = useNotesStore();`):
```typescript
const noteEntries = useNoteEntriesStore();
```

Modify the `onMounted` block (lines 39-46). Change the `Promise.all` line:
```typescript
await Promise.all([followups.load(), notes.load(), noteEntries.load()]);
```

- [ ] **Step 2: Update the card chip count**

Open `webapp/src/components/TicketCard.vue`. Find where the existing notes chip is rendered (search for `countNoteLines` or `noteCount`). The current pattern uses the legacy `notes` store's `countNoteLines(notesStore.bodyOf(ticket.id))`.

Add the entries store import next to the existing notes store import:
```typescript
import { useNoteEntriesStore } from '@/stores/noteEntries';
```

Add the store instantiation alongside the existing `notes` store:
```typescript
const noteEntries = useNoteEntriesStore();
```

Locate the chip `noteCount` computed (or whatever the file calls it). Change it from
```typescript
const noteCount = computed(() => countNoteLines(notes.bodyOf(props.ticket.id)));
```
to
```typescript
const noteCount = computed(() => {
  const legacy = countNoteLines(notes.bodyOf(props.ticket.id));
  return legacy + noteEntries.countOf(props.ticket.id);
});
```

If the file does not yet use a computed and instead inlines the call in the template, introduce the `noteCount` computed above first and replace the inline call.

- [ ] **Step 3: Typecheck + run existing tests**

Run:
```bash
cd webapp
npm run typecheck
npx vitest run
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/App.vue webapp/src/components/TicketCard.vue
git commit -m "feat(notes): load noteEntries on mount + card chip counts entries"
```

---

## Task 8: Rewrite the `Next-step notes` section of the flyout

**Files:**
- Modify: `webapp/src/components/TicketFlyout.vue`

- [ ] **Step 1: Add imports + store wiring**

Open `webapp/src/components/TicketFlyout.vue`.

Add import alongside the existing `useNotesStore` import (around line 10):
```typescript
import { useNoteEntriesStore } from '@/stores/noteEntries';
```

Add store instance alongside the existing `notes` instance (around line 19):
```typescript
const noteEntries = useNoteEntriesStore();
```

Add reactive state immediately after the existing `draft` / `noteSaving` refs (around line 140). These drive the new entry form:

```typescript
const TIMER_PRESETS: { label: string; minutes: number | null }[] = [
  { label: 'off', minutes: null },
  { label: '5m', minutes: 5 },
  { label: '15m', minutes: 15 },
  { label: '30m', minutes: 30 },
  { label: '1h', minutes: 60 },
];

const entryDraft = ref('');
const entryTimer = ref<number | null>(null);
const entryReason = ref('');
const entrySaving = ref(false);
const entryError = ref<string | null>(null);
const legacyOpen = ref(false);

const entries = computed(() =>
  ticket.value ? noteEntries.entriesOf(ticket.value.id) : [],
);
const hasLegacyNote = computed(() => notes.bodyOf(ticket.value?.id ?? '').length > 0);

async function addEntry() {
  const id = ticket.value?.id;
  const body = entryDraft.value.trim();
  if (!id || body.length === 0) return;
  entrySaving.value = true;
  entryError.value = null;
  try {
    await noteEntries.addEntry(
      id,
      body,
      entryTimer.value,
      entryReason.value.trim() || null,
    );
    entryDraft.value = '';
    entryReason.value = '';
    entryTimer.value = null;
    // If the entry armed a timer, refresh the followups store so the chip
    // updates immediately (backend already wrote the row inside the same txn).
    if (entryTimer.value !== null || entryReason.value.length > 0) {
      await followups.load();
    }
  } catch (e) {
    entryError.value = (e as Error).message;
  } finally {
    entrySaving.value = false;
  }
}

async function removeEntry(entryId: number) {
  try {
    await noteEntries.deleteEntry(entryId);
  } catch (e) {
    entryError.value = (e as Error).message;
  }
}

function entryTimeLabel(iso: string): string {
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}
```

- [ ] **Step 2: Reset entry form state when the open ticket changes**

Find the existing `watch(() => ticket.value?.id, …)` block that resets `draft`, `reason`, `fuError` (around line 166). Add to its callback body, after the existing resets:

```typescript
    entryDraft.value = '';
    entryReason.value = '';
    entryTimer.value = null;
    entryError.value = null;
    legacyOpen.value = false;
```

- [ ] **Step 3: Replace the `Next-step notes` template block**

Find the existing `<!-- Notes (T052) -->` section (around line 565). Replace the entire `<section class="block">…</section>` block (lines ~565-584) with:

```vue
          <!-- Next-step notes — time-tabled entries (spec: time-tabled notes) -->
          <section class="block">
            <div class="mono label">
              Next-step notes
              <span v-if="entrySaving" class="dim">· saving…</span>
            </div>

            <!-- Legacy scratchpad disclosure — only when non-empty -->
            <details v-if="hasLegacyNote" v-model:open="legacyOpen" class="legacy-note">
              <summary class="mono dim">Legacy note ▸</summary>
              <textarea
                v-model="draft"
                class="notes"
                rows="3"
                @input="scheduleSave"
                @blur="flushNote"
              />
            </details>

            <!-- Timeline -->
            <ul v-if="entries.length" class="entry-timeline">
              <li v-for="e in entries" :key="e.id" class="entry-row">
                <div class="entry-head">
                  <span class="mono dim">{{ entryTimeLabel(e.created_at) }}</span>
                  <button class="entry-x" title="Delete entry" @click="removeEntry(e.id)">×</button>
                </div>
                <p class="entry-body">{{ e.body }}</p>
                <div v-if="e.timer_min !== null" class="entry-timer mono dim">
                  ⏱ {{ e.timer_min }}m<span v-if="e.reason"> · "{{ e.reason }}"</span>
                </div>
              </li>
            </ul>
            <p v-else class="dim entry-empty">No entries yet — add the first one below.</p>

            <!-- New entry form -->
            <div class="entry-form">
              <textarea
                v-model="entryDraft"
                class="notes"
                rows="3"
                placeholder="What's the next step?"
              />
              <div class="presets timer-row">
                <span class="mono dim timer-label">Timer:</span>
                <button
                  v-for="p in TIMER_PRESETS"
                  :key="p.label"
                  class="chip"
                  :class="{ active: entryTimer === p.minutes }"
                  @click="entryTimer = p.minutes"
                >
                  {{ p.label }}
                </button>
              </div>
              <input
                v-model="entryReason"
                class="reason"
                type="text"
                maxlength="80"
                placeholder="Reason (optional, ≤ 80 chars)"
              />
              <div class="presets">
                <button
                  class="chip primary"
                  :disabled="entrySaving || entryDraft.trim().length === 0"
                  @click="addEntry"
                >
                  Add entry
                </button>
              </div>
              <div v-if="entryError" class="mono err">{{ entryError }}</div>
            </div>
          </section>
```

- [ ] **Step 4: Add styles for the new elements**

Append to the `<style scoped>` block at the bottom of the file (after the existing `.notes { … }` rule, around line 921):

```css
.legacy-note {
  margin-bottom: 10px;
}
.legacy-note summary {
  cursor: pointer;
  padding: 4px 0;
}
.entry-timeline {
  list-style: none;
  margin: 0 0 12px;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.entry-row {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-card);
  padding: 6px 8px;
  background: var(--panel);
}
.entry-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 2px;
}
.entry-x {
  border: none;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.entry-x:hover {
  color: var(--accent);
}
.entry-body {
  margin: 2px 0;
  white-space: pre-wrap;
  font-size: 13px;
}
.entry-timer {
  margin-top: 2px;
  font-size: 11px;
}
.entry-empty {
  margin: 0 0 12px;
  font-size: 12px;
}
.entry-form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.timer-row {
  align-items: center;
}
.timer-label {
  margin-right: 4px;
}
.chip.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
.chip.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
```

- [ ] **Step 5: Typecheck + build**

Run:
```bash
cd webapp
npm run typecheck
npm run build
```

Expected: success.

- [ ] **Step 6: Manual smoke test in browser**

Start the dev stack:
```bash
# terminal 1
cd backend && uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# terminal 2
cd webapp && npm run dev
```

Open <http://localhost:5173>, click any card to open the flyout, then verify:
1. `Next-step notes` section shows "No entries yet" if none exist.
2. Type into the new-entry textarea, click `15m`, type a reason, click `Add entry`. A new row appears above the form with the timestamp + ⏱ chip.
3. The Follow-up section above shows the timer as the ticket's active follow-up.
4. Click another `15m` entry — the prior follow-up row is overwritten (visible in the Follow-up section).
5. Click the `×` on a past entry — it disappears from the timeline.
6. Close + reopen the flyout — timeline persists.
7. Legacy note: if a ticket already had a `ticket_notes.body`, the `Legacy note ▸` disclosure appears and reveals the old textarea on click.

- [ ] **Step 7: Commit**

```bash
git add webapp/src/components/TicketFlyout.vue
git commit -m "feat(notes): flyout timeline + new-entry form with optional timer"
```

---

## Task 9: README API surface update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the API table**

Open `README.md`. Find the row in the API surface table (around line 102):
```
| `GET /notes` · `PUT /notes/{id}` | Per-ticket next-step notes (empty body deletes) |
```

Insert immediately after it:
```
| `GET /notes/entries` · `GET /notes/entries/{ticket_id}` | Time-tabled note entries — list all / list by ticket |
| `POST /notes/entries` · `DELETE /notes/entries/{id}` | Append an entry (optional `timer_min` upserts follow-up); soft-delete by id |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs(readme): document /notes/entries endpoints"
```

---

## Task 10: Full quality-gate sweep

- [ ] **Step 1: Backend gates**

Run:
```bash
cd backend
ruff check app tests && ruff format --check app tests
mypy app
pytest -q
```

Expected: all green. Fix any new ruff/mypy issues before continuing.

- [ ] **Step 2: Webapp gates**

Run:
```bash
cd webapp
npm run typecheck
npm run build
npx vitest run
```

Expected: all green.

- [ ] **Step 3: Final commit if any fixups landed**

If steps 1-2 required fixups, stage + commit them:
```bash
git add -A
git commit -m "chore: fix lint/type issues from time-tabled notes rollout"
```

If no fixups, skip this commit.

---

## Self-Review (already run; issues fixed inline)

**Spec coverage:**
- Data model — Task 1 (ORM) + Task 1 (migration).
- API — Task 2 (schemas) + Task 4 (router).
- Soft-link contract (timer entry → followup upsert atomic) — Task 3 service + Task 3 tests.
- Frontend store — Task 6.
- Flyout UI rewrite — Task 8.
- Card chip count — Task 7.
- Migration kept additive, legacy preserved — Task 1.
- Tests cover both layers — Tasks 1, 3, 4, 6.
- README update — Task 9.
- Quality gates — Task 10.

**Placeholder scan:** None — every step has runnable code + expected output.

**Type consistency:** `NoteEntry` (TS) mirrors `NoteEntryRead` (pydantic) mirrors `NoteEntry` (ORM). Method names — `addEntry` / `addNoteEntry` / `add_entry` — pair store→client→service consistently. `timer_min` is the same name across all three layers.

**Out-of-scope items from spec:** No tasks for bulk endpoints, edit, multi-timer, auto-snooze escalation, legacy migration, or Chrome extension changes — all confirmed YAGNI in the spec.

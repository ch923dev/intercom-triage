# Note Attachments Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-entry and per-ticket file attachments to the notes feature, with paste, drop, and file-picker upload from the flyout.

**Architecture:** New polymorphic `note_attachments` table (one row per file, `owner_kind ∈ {'entry','ticket'}`). Files stored on local filesystem under `backend/data/attachments/<sha256[:2]>/<sha256>.<ext>`, content-addressed so identical bytes dedupe automatically. Thumbnails generated on demand via Pillow and cached at `data/attachments/thumbs/<sha256>.webp`. Soft-delete + nightly disk sweep (mirrors the existing `_cache_sweep_loop` pattern). Webapp adds a lazy-loading Pinia store and two upload zones in the flyout: per-entry pending-attach inside the new-entry compose, and a per-ticket dropzone above the timeline.

**Tech Stack:** Python 3.11 + FastAPI multipart + SQLAlchemy 2.x async + Alembic + Pillow + pytest-asyncio (backend); Vue 3 + Pinia + Vitest (webapp).

**Spec:** `docs/superpowers/specs/2026-05-23-note-attachments-design.md`

---

## File Structure

**Backend — new:**
- `backend/alembic/versions/0009_add_note_attachments.py` — create `note_attachments` table + indices + check constraints.
- `backend/app/services/attachments.py` — upload, list, soft-delete, thumb generation, sweep helpers.
- `backend/app/routers/attachments.py` — `/attachments` endpoints.
- `backend/tests/test_attachments_service.py` — service-level tests (filesystem + DB).
- `backend/tests/test_attachments_api.py` — endpoint tests (multipart + streaming).

**Backend — modify:**
- `backend/requirements.txt` — add `Pillow`.
- `backend/app/models.py` — add `NoteAttachment` ORM model.
- `backend/app/schemas.py` — add `NoteAttachmentRead`, `NoteAttachmentDeleted`.
- `backend/app/config.py` — add `attachments_dir`, `attachment_gc_days`, `attachment_sweep_interval_seconds`.
- `backend/app/main.py` — register router, mkdir on lifespan boot, start `_attachment_sweep_loop`.
- `backend/pyproject.toml` — add mypy override for `PIL` if needed.

**Webapp — new:**
- `webapp/src/stores/attachments.ts` — Pinia store, lazy load per ticket, optimistic upload + remove.
- `webapp/src/stores/attachments.spec.ts` — store unit tests.
- `webapp/src/components/AttachmentList.vue` — shared renderer (thumb grid + pill row, × delete).
- `webapp/src/components/AttachmentDropzone.vue` — the ticket-bin zone widget.

**Webapp — modify:**
- `webapp/src/types/api.ts` — add `NoteAttachment` interface.
- `webapp/src/api/client.ts` — add `listAttachments`, `uploadAttachment`, `deleteAttachment`.
- `webapp/src/components/TicketFlyout.vue` — wire dropzone, paste-on-textarea, pending attachments preview, per-entry render.

**Docs:**
- `README.md` — add `/attachments` rows + new `data/attachments/` line under "Backup".

---

## Task 1: Add Pillow dependency

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/pyproject.toml` (mypy ignore if stubs missing)

- [ ] **Step 1: Add Pillow to requirements**

Append to `backend/requirements.txt` after the SQLAlchemy block:

```
# Image thumbnailing for note attachments
Pillow==11.0.0
```

- [ ] **Step 2: Install**

Run from `backend/`:
```bash
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Expected: `Successfully installed Pillow-11.0.0` (or "already satisfied").

- [ ] **Step 3: Add mypy override**

Open `backend/pyproject.toml`. Find the `[tool.mypy]` section. If it has no `[[tool.mypy.overrides]]` block for `PIL`, append:

```toml
[[tool.mypy.overrides]]
module = "PIL.*"
ignore_missing_imports = true
```

If no `[tool.mypy]` block exists at all, search for it first — Pillow ships type stubs as of v10 so this override may not be needed. Run step 4 first; only add the override if mypy complains.

- [ ] **Step 4: Smoke-test the import**

Run:
```bash
.venv/Scripts/python.exe -c "from PIL import Image; print('Pillow', Image.__version__ if hasattr(Image, '__version__') else 'ok')"
```

Expected: prints `Pillow ok` or similar (no traceback).

- [ ] **Step 5: Verify backend mypy still passes**

Run from `backend/`:
```bash
.venv/Scripts/python.exe -m mypy app
```

Expected: `Success: no issues found`.

- [ ] **Step 6: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/requirements.txt backend/pyproject.toml
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "chore(deps): add Pillow for note-attachment thumbnails"
```

---

## Task 2: Add `NoteAttachment` ORM model + Alembic migration

**Files:**
- Modify: `backend/app/models.py` (append after `NoteEntry`, before `class Ticket`)
- Create: `backend/alembic/versions/0009_add_note_attachments.py`
- Create: `backend/tests/test_attachments_service.py` (schema-only test for now)

- [ ] **Step 1: Write failing schema smoke test**

Create `backend/tests/test_attachments_service.py`:

```python
"""Service-level tests for note_attachments (spec: note attachments)."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NoteAttachment


@pytest.mark.asyncio
async def test_note_attachment_model_persists(session: AsyncSession) -> None:
    """Insert a note_attachments row + read it back."""
    row = NoteAttachment(
        owner_kind="ticket",
        owner_id="T1",
        ticket_id="T1",
        filename="trace.csv",
        mime="text/csv",
        size_bytes=42,
        sha256="a" * 64,
        stored_path="aa/aaaa.csv",
    )
    session.add(row)
    await session.commit()

    found = (
        await session.scalars(select(NoteAttachment).where(NoteAttachment.id == row.id))
    ).one()
    assert found.owner_kind == "ticket"
    assert found.owner_id == "T1"
    assert found.ticket_id == "T1"
    assert found.filename == "trace.csv"
    assert found.mime == "text/csv"
    assert found.size_bytes == 42
    assert found.sha256 == "a" * 64
    assert found.stored_path == "aa/aaaa.csv"
    assert found.deleted_at is None
    assert found.created_at is not None
```

- [ ] **Step 2: Run test to confirm it fails**

Run from `backend/`:
```bash
.venv/Scripts/python.exe -m pytest tests/test_attachments_service.py -v
```

Expected: `ImportError: cannot import name 'NoteAttachment' from 'app.models'`.

- [ ] **Step 3: Add the `NoteAttachment` ORM model**

Open `backend/app/models.py`. Find the `NoteEntry` class (added by the time-tabled notes spec) and the `Ticket` class right after it. Insert this new class between them — immediately after the `NoteEntry` class's closing `)` of `__table_args__`, before `class Ticket(Base):`:

```python
class NoteAttachment(Base):
    """A file attachment owned by either a note entry or a ticket (spec:
    note attachments). Content-addressed by sha256 on disk so identical
    uploads dedupe automatically. Polymorphic owner — `owner_kind` is
    'entry' (owner_id = str of NoteEntry.id) or 'ticket' (owner_id =
    ticket_id). `ticket_id` is always populated so list-by-ticket is one
    index lookup regardless of owner kind."""

    __tablename__ = "note_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_kind: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_id: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "owner_kind IN ('entry','ticket')",
            name="note_attachments_owner_kind_check",
        ),
        CheckConstraint("length(sha256) = 64", name="note_attachments_sha256_len_check"),
        CheckConstraint("size_bytes >= 0", name="note_attachments_size_nonneg_check"),
        Index("ix_note_attachments_owner", "owner_kind", "owner_id"),
        Index("ix_note_attachments_ticket", "ticket_id"),
        Index("ix_note_attachments_sha256", "sha256"),
    )
```

- [ ] **Step 4: Create the Alembic migration**

Create `backend/alembic/versions/0009_add_note_attachments.py`:

```python
"""Add note_attachments table (note attachments spec).

Spec: docs/superpowers/specs/2026-05-23-note-attachments-design.md

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-23 00:00:09.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "note_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_kind", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "owner_kind IN ('entry','ticket')",
            name="note_attachments_owner_kind_check",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64", name="note_attachments_sha256_len_check"
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name="note_attachments_size_nonneg_check"
        ),
    )
    op.create_index(
        "ix_note_attachments_owner", "note_attachments", ["owner_kind", "owner_id"]
    )
    op.create_index("ix_note_attachments_ticket", "note_attachments", ["ticket_id"])
    op.create_index("ix_note_attachments_sha256", "note_attachments", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_note_attachments_sha256", table_name="note_attachments")
    op.drop_index("ix_note_attachments_ticket", table_name="note_attachments")
    op.drop_index("ix_note_attachments_owner", table_name="note_attachments")
    op.drop_table("note_attachments")
```

- [ ] **Step 5: Run schema test to verify it passes**

Run from `backend/`:
```bash
.venv/Scripts/python.exe -m pytest tests/test_attachments_service.py::test_note_attachment_model_persists -v
```

Expected: PASS.

- [ ] **Step 6: Run full backend test suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: 179 passed (178 prior + 1 new).

- [ ] **Step 7: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/app/models.py backend/alembic/versions/0009_add_note_attachments.py backend/tests/test_attachments_service.py
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): add note_attachments table + ORM model

Polymorphic owner (entry|ticket), content-addressed sha256.
Migration 0009. Spec: docs/superpowers/specs/2026-05-23-note-attachments-design.md"
```

---

## Task 3: Add Pydantic schemas

**Files:**
- Modify: `backend/app/schemas.py` (append after `NoteEntryDeleted`, before `# ── Tickets ──` divider)

- [ ] **Step 1: Add the schemas**

Open `backend/app/schemas.py`. Find the `class NoteEntryDeleted(BaseModel):` block. Immediately after its closing brace and blank line, insert:

```python
# ── Note attachments ─────────────────────────────────────────────────────────


class NoteAttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_kind: Literal["entry", "ticket"]
    owner_id: str
    ticket_id: str
    filename: str
    mime: str
    size_bytes: int
    created_at: UTCDatetime
    raw_url: str
    thumb_url: str | None


class NoteAttachmentDeleted(BaseModel):
    ok: Literal[True] = True
    deleted: Literal[True] = True
    id: int
```

`raw_url` / `thumb_url` are populated by the router (they're not DB columns), so for `from_attributes` validation we'll populate them manually from the service layer — the schema lists them so the response shape is documented and validated. The router code in Task 5 builds the dict explicitly.

- [ ] **Step 2: Verify schemas typecheck**

Run from `backend/`:
```bash
.venv/Scripts/python.exe -m mypy app/schemas.py
```

Expected: `Success: no issues found in 1 source file`.

- [ ] **Step 3: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/app/schemas.py
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): add NoteAttachment pydantic schemas"
```

---

## Task 4: Config + filesystem bootstrap

**Files:**
- Modify: `backend/app/config.py`

- [ ] **Step 1: Add attachment config**

Open `backend/app/config.py`. Add this import near the top (after `from functools import lru_cache`):

```python
from pathlib import Path
```

Inside `class AppConfig(BaseSettings)`, after the `cache_ttl_seconds` field (around line 50), add a new section:

```python
    # ── Attachments (note attachments spec) ──────────────────────────────────
    attachments_dir: Path = Path("./data/attachments")
    attachment_gc_days: int = Field(default=7, ge=0)
    attachment_sweep_interval_seconds: int = Field(default=86_400, ge=60)
```

- [ ] **Step 2: Verify config typechecks**

```bash
.venv/Scripts/python.exe -m mypy app/config.py
```

Expected: success.

- [ ] **Step 3: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/app/config.py
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): add attachments_dir + sweep config knobs"
```

---

## Task 5: Service layer — upload, list, soft-delete, dedup

**Files:**
- Create: `backend/app/services/attachments.py`
- Modify: `backend/tests/test_attachments_service.py`

- [ ] **Step 1: Add failing service tests**

Append to `backend/tests/test_attachments_service.py`:

```python
from datetime import timedelta
from pathlib import Path

from app.config import AppConfig
from app.models import NoteAttachment
from app.services import attachments as svc
from app.util import naive_utcnow


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        openrouter_api_key="test",
        database_url="sqlite+aiosqlite:///:memory:",
        attachments_dir=tmp_path / "attachments",
    )


@pytest.mark.asyncio
async def test_upload_creates_row_and_disk_file(
    session: AsyncSession, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path)
    row = await svc.upload_attachment(
        session,
        cfg,
        owner_kind="ticket",
        owner_id="T1",
        ticket_id="T1",
        filename="hello.txt",
        mime="text/plain",
        data=b"hello world",
    )
    assert row.id is not None
    assert row.sha256 == (
        "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"
    )
    assert row.size_bytes == 11
    disk_path = cfg.attachments_dir / row.stored_path
    assert disk_path.exists()
    assert disk_path.read_bytes() == b"hello world"


@pytest.mark.asyncio
async def test_upload_dedupes_same_bytes(
    session: AsyncSession, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path)
    a = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "a.txt", "text/plain", b"same"
    )
    b = await svc.upload_attachment(
        session, cfg, "entry", "42", "T1", "b.txt", "text/plain", b"same"
    )
    assert a.sha256 == b.sha256
    assert a.stored_path == b.stored_path
    # Only one file on disk for both rows.
    matches = list((cfg.attachments_dir).rglob(f"{a.sha256}*"))
    assert len(matches) == 1


@pytest.mark.asyncio
async def test_list_for_ticket_returns_both_owner_kinds_and_excludes_deleted(
    session: AsyncSession, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path)
    t = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "t.txt", "text/plain", b"t"
    )
    e = await svc.upload_attachment(
        session, cfg, "entry", "42", "T1", "e.txt", "text/plain", b"e"
    )
    gone = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "g.txt", "text/plain", b"g"
    )
    await svc.soft_delete(session, gone.id)

    rows = await svc.list_for_ticket(session, "T1")
    assert {r.id for r in rows} == {t.id, e.id}


@pytest.mark.asyncio
async def test_soft_delete_sets_deleted_at_but_keeps_disk_file(
    session: AsyncSession, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path)
    row = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "x.txt", "text/plain", b"x"
    )
    disk_path = cfg.attachments_dir / row.stored_path

    deleted = await svc.soft_delete(session, row.id)
    assert deleted.deleted_at is not None
    assert disk_path.exists()


@pytest.mark.asyncio
async def test_soft_delete_missing_id_returns_404(session: AsyncSession) -> None:
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.soft_delete(session, 99999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_sweep_unlinks_orphan_past_gc_window(
    session: AsyncSession, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path)
    row = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "x.txt", "text/plain", b"orphan"
    )
    disk_path = cfg.attachments_dir / row.stored_path
    await svc.soft_delete(session, row.id)

    # Force deleted_at into the past.
    row.deleted_at = naive_utcnow() - timedelta(days=cfg.attachment_gc_days + 1)
    await session.commit()

    result = await svc.sweep_attachments(session, cfg)
    assert result.files_unlinked == 1
    assert result.rows_deleted == 1
    assert not disk_path.exists()


@pytest.mark.asyncio
async def test_sweep_keeps_file_with_live_sibling(
    session: AsyncSession, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path)
    a = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "a.txt", "text/plain", b"shared"
    )
    b = await svc.upload_attachment(
        session, cfg, "entry", "42", "T2", "b.txt", "text/plain", b"shared"
    )
    disk_path = cfg.attachments_dir / a.stored_path
    await svc.soft_delete(session, a.id)

    a.deleted_at = naive_utcnow() - timedelta(days=cfg.attachment_gc_days + 1)
    await session.commit()

    result = await svc.sweep_attachments(session, cfg)
    assert result.files_unlinked == 0  # b still references the same sha256
    assert result.rows_deleted == 1
    assert disk_path.exists()
    # b still readable.
    assert (await session.get(NoteAttachment, b.id)) is not None


@pytest.mark.asyncio
async def test_get_thumb_path_creates_webp_for_image(
    session: AsyncSession, tmp_path: Path
) -> None:
    from io import BytesIO
    from PIL import Image

    cfg = _make_config(tmp_path)
    buf = BytesIO()
    Image.new("RGB", (400, 300), color=(255, 0, 0)).save(buf, format="PNG")
    row = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "a.png", "image/png", buf.getvalue()
    )

    thumb = svc.get_or_make_thumb_path(cfg, row)
    assert thumb is not None and thumb.exists()
    assert thumb.suffix == ".webp"
    with Image.open(thumb) as im:
        assert max(im.size) <= 256


@pytest.mark.asyncio
async def test_get_thumb_path_returns_none_for_non_image(
    session: AsyncSession, tmp_path: Path
) -> None:
    cfg = _make_config(tmp_path)
    row = await svc.upload_attachment(
        session, cfg, "ticket", "T1", "T1", "x.txt", "text/plain", b"hello"
    )
    assert svc.get_or_make_thumb_path(cfg, row) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_attachments_service.py -v
```

Expected: `ImportError: cannot import name 'attachments' from 'app.services'`.

- [ ] **Step 3: Create the service module**

Create `backend/app/services/attachments.py`:

```python
"""Note attachments — upload, list, soft-delete, sweep, thumb generation.

Spec: docs/superpowers/specs/2026-05-23-note-attachments-design.md

Files are content-addressed by sha256 on disk under `<attachments_dir>/<sha256[:2]>/<sha256>.<ext>`.
Uploading the same bytes twice creates two DB rows pointing at one file. Soft-deletes
keep the file on disk; the nightly sweep removes orphans whose sha256 has no live
sibling rows.
"""

from __future__ import annotations

import hashlib
import mimetypes
from dataclasses import dataclass
from datetime import timedelta
from io import BytesIO
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.metrics import metrics
from app.models import NoteAttachment
from app.util import naive_utcnow


def _extension_for(filename: str, mime: str) -> str:
    """Pick a sensible file extension. Prefer the original filename's suffix;
    fall back to mimetypes; final fallback `.bin`."""
    suffix = Path(filename).suffix
    if suffix and len(suffix) <= 16:
        return suffix
    guessed = mimetypes.guess_extension(mime or "") or ""
    return guessed or ".bin"


def _stored_path_for(sha256: str, filename: str, mime: str) -> str:
    """Relative path under `attachments_dir` for a content-addressed file."""
    return f"{sha256[:2]}/{sha256}{_extension_for(filename, mime)}"


async def upload_attachment(
    session: AsyncSession,
    config: AppConfig,
    owner_kind: str,
    owner_id: str,
    ticket_id: str,
    filename: str,
    mime: str,
    data: bytes,
) -> NoteAttachment:
    """Hash + dedup + persist. Writes the file before inserting the row so
    a failed insert leaves a stray byte-identical file on disk that the next
    upload of the same bytes will reuse — that's the desired behaviour."""
    sha = hashlib.sha256(data).hexdigest()
    rel = _stored_path_for(sha, filename, mime)
    abs_path = config.attachments_dir / rel
    abs_path.parent.mkdir(parents=True, exist_ok=True)
    if not abs_path.exists():
        abs_path.write_bytes(data)

    row = NoteAttachment(
        owner_kind=owner_kind,
        owner_id=owner_id,
        ticket_id=ticket_id,
        filename=filename,
        mime=mime,
        size_bytes=len(data),
        sha256=sha,
        stored_path=rel,
        created_at=naive_utcnow(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    metrics.incr("attachments_uploaded_total")
    return row


async def list_for_ticket(
    session: AsyncSession, ticket_id: str
) -> list[NoteAttachment]:
    """All non-deleted attachments for a ticket (both owner_kinds)."""
    stmt = (
        select(NoteAttachment)
        .where(
            NoteAttachment.ticket_id == ticket_id,
            NoteAttachment.deleted_at.is_(None),
        )
        .order_by(NoteAttachment.created_at.asc(), NoteAttachment.id.asc())
    )
    return list((await session.scalars(stmt)).all())


async def get(session: AsyncSession, attachment_id: int) -> NoteAttachment:
    """Return a row or raise 404. Includes soft-deleted rows so /raw can still
    serve them mid-undo; the router decides whether to surface deleted ones."""
    row = await session.get(NoteAttachment, attachment_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no attachment {attachment_id}")
    return row


async def soft_delete(session: AsyncSession, attachment_id: int) -> NoteAttachment:
    """Stamp `deleted_at`. Idempotent on a row already deleted."""
    row = await get(session, attachment_id)
    if row.deleted_at is None:
        row.deleted_at = naive_utcnow()
        await session.commit()
        await session.refresh(row)
        metrics.incr("attachments_deleted_total")
    return row


def get_or_make_thumb_path(config: AppConfig, row: NoteAttachment) -> Path | None:
    """Return the on-disk path to a 256px max-side WebP thumbnail for an image
    attachment. Generated on first request, cached. Returns None for non-images."""
    if not row.mime.startswith("image/"):
        return None
    thumbs_dir = config.attachments_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumbs_dir / f"{row.sha256}.webp"
    if thumb_path.exists():
        return thumb_path

    source_path = config.attachments_dir / row.stored_path
    if not source_path.exists():
        return None

    from PIL import Image

    with Image.open(source_path) as im:
        im = im.convert("RGB")
        im.thumbnail((256, 256))
        im.save(thumb_path, format="WEBP", quality=80)
    return thumb_path


@dataclass
class SweepResult:
    files_unlinked: int
    rows_deleted: int


async def sweep_attachments(
    session: AsyncSession, config: AppConfig
) -> SweepResult:
    """Hard-delete rows whose `deleted_at` is older than `attachment_gc_days`.
    Unlink the file only when no live sibling row references the same sha256."""
    cutoff = naive_utcnow() - timedelta(days=config.attachment_gc_days)
    stmt = select(NoteAttachment).where(
        NoteAttachment.deleted_at.is_not(None),
        NoteAttachment.deleted_at < cutoff,
    )
    rows = list((await session.scalars(stmt)).all())

    files_unlinked = 0
    for row in rows:
        live_count = (
            await session.scalar(
                select(func.count())
                .select_from(NoteAttachment)
                .where(
                    NoteAttachment.sha256 == row.sha256,
                    NoteAttachment.id != row.id,
                    NoteAttachment.deleted_at.is_(None),
                )
            )
            or 0
        )
        if live_count == 0:
            abs_path = config.attachments_dir / row.stored_path
            if abs_path.exists():
                abs_path.unlink()
                files_unlinked += 1
            thumb_path = config.attachments_dir / "thumbs" / f"{row.sha256}.webp"
            if thumb_path.exists():
                thumb_path.unlink()
        await session.delete(row)

    await session.commit()
    metrics.incr("attachments_gc_total.rows_deleted", len(rows))
    metrics.incr("attachments_gc_total.files_unlinked", files_unlinked)
    return SweepResult(files_unlinked=files_unlinked, rows_deleted=len(rows))
```

- [ ] **Step 4: Run tests to verify all pass**

```bash
.venv/Scripts/python.exe -m pytest tests/test_attachments_service.py -v
```

Expected: all 9 tests pass (1 from Task 2 + 8 new).

- [ ] **Step 5: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/app/services/attachments.py backend/tests/test_attachments_service.py
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): service layer with dedup, thumbs, soft-delete, sweep"
```

---

## Task 6: REST router

**Files:**
- Create: `backend/app/routers/attachments.py`
- Create: `backend/tests/test_attachments_api.py`
- Modify: `backend/app/main.py` (register router + mkdir on lifespan boot)

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/test_attachments_api.py`:

```python
"""HTTP tests for /attachments (note attachments spec)."""

from __future__ import annotations

from io import BytesIO

import pytest
from httpx import AsyncClient


def _png_bytes(color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    from PIL import Image

    buf = BytesIO()
    Image.new("RGB", (320, 240), color=color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.mark.asyncio
async def test_post_attachment_for_ticket(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("trace.csv", b"a,b,c\n1,2,3", "text/csv")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["owner_kind"] == "ticket"
    assert payload["owner_id"] == "T1"
    assert payload["ticket_id"] == "T1"
    assert payload["filename"] == "trace.csv"
    assert payload["mime"] == "text/csv"
    assert payload["size_bytes"] == 11
    assert payload["raw_url"].endswith(f"/attachments/{payload['id']}/raw")
    assert payload["thumb_url"] is None


@pytest.mark.asyncio
async def test_post_attachment_for_entry(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "entry", "owner_id": "42", "ticket_id": "T1"},
        files={"file": ("note.txt", b"hello", "text/plain")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["owner_kind"] == "entry"
    assert payload["owner_id"] == "42"


@pytest.mark.asyncio
async def test_post_image_returns_thumb_url(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("a.png", _png_bytes(), "image/png")},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["thumb_url"] is not None
    assert payload["thumb_url"].endswith(f"/attachments/{payload['id']}/thumb")


@pytest.mark.asyncio
async def test_get_list_filtered_by_ticket(client: AsyncClient) -> None:
    await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("a.txt", b"a", "text/plain")},
    )
    await client.post(
        "/attachments",
        data={"owner_kind": "entry", "owner_id": "42", "ticket_id": "T1"},
        files={"file": ("b.txt", b"b", "text/plain")},
    )
    await client.post(
        "/attachments",
        data={"owner_kind": "ticket", "owner_id": "T2", "ticket_id": "T2"},
        files={"file": ("x.txt", b"x", "text/plain")},
    )

    rows = (await client.get("/attachments", params={"ticket_id": "T1"})).json()
    assert sorted(r["filename"] for r in rows) == ["a.txt", "b.txt"]


@pytest.mark.asyncio
async def test_get_raw_streams_bytes(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("hello.txt", b"hello world", "text/plain")},
        )
    ).json()
    resp = await client.get(f"/attachments/{created['id']}/raw")
    assert resp.status_code == 200
    assert resp.content == b"hello world"
    assert resp.headers["content-type"].startswith("text/plain")
    assert "hello.txt" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_get_thumb_for_image(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("a.png", _png_bytes(), "image/png")},
        )
    ).json()
    resp = await client.get(f"/attachments/{created['id']}/thumb")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert len(resp.content) > 0


@pytest.mark.asyncio
async def test_get_thumb_for_non_image_returns_404(client: AsyncClient) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("a.txt", b"hi", "text/plain")},
        )
    ).json()
    resp = await client.get(f"/attachments/{created['id']}/thumb")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_delete_returns_envelope_and_excludes_from_list(
    client: AsyncClient,
) -> None:
    created = (
        await client.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("a.txt", b"a", "text/plain")},
        )
    ).json()
    resp = await client.delete(f"/attachments/{created['id']}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "deleted": True, "id": created["id"]}

    rows = (await client.get("/attachments", params={"ticket_id": "T1"})).json()
    assert rows == []


@pytest.mark.asyncio
async def test_post_missing_field_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "ticket"},
        files={"file": ("a.txt", b"a", "text/plain")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_invalid_owner_kind_returns_422(client: AsyncClient) -> None:
    resp = await client.post(
        "/attachments",
        data={"owner_kind": "bogus", "owner_id": "T1", "ticket_id": "T1"},
        files={"file": ("a.txt", b"a", "text/plain")},
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/Scripts/python.exe -m pytest tests/test_attachments_api.py -v
```

Expected: 404s on `/attachments` — router not registered yet.

- [ ] **Step 3: Create the router**

Create `backend/app/routers/attachments.py`:

```python
"""Note-attachment endpoints (spec: note attachments).

Endpoints:
  POST   /attachments               multipart upload
  GET    /attachments?ticket_id=…   list non-deleted for one ticket
  GET    /attachments/{id}/raw      stream bytes (inline)
  GET    /attachments/{id}/thumb    WebP thumbnail for images; 404 otherwise
  DELETE /attachments/{id}          soft-delete
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.db import get_session
from app.deps import get_config_dep
from app.models import NoteAttachment
from app.schemas import NoteAttachmentDeleted, NoteAttachmentRead
from app.services import attachments as svc

router = APIRouter(prefix="/attachments", tags=["attachments"])


def _to_read(row: NoteAttachment) -> NoteAttachmentRead:
    """Serialize an ORM row to the wire schema, computing raw/thumb URLs."""
    return NoteAttachmentRead(
        id=row.id,
        owner_kind=row.owner_kind,  # type: ignore[arg-type]
        owner_id=row.owner_id,
        ticket_id=row.ticket_id,
        filename=row.filename,
        mime=row.mime,
        size_bytes=row.size_bytes,
        created_at=row.created_at,
        raw_url=f"/api/attachments/{row.id}/raw",
        thumb_url=(
            f"/api/attachments/{row.id}/thumb" if row.mime.startswith("image/") else None
        ),
    )


@router.post("", response_model=NoteAttachmentRead)
async def post_attachment(
    file: UploadFile = File(...),
    owner_kind: Literal["entry", "ticket"] = Form(...),
    owner_id: str = Form(..., min_length=1),
    ticket_id: str = Form(..., min_length=1),
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_config_dep),
) -> NoteAttachmentRead:
    """Upload a single file. Multipart fields: file (binary), owner_kind,
    owner_id, ticket_id. Content-addressed dedup is transparent to the caller."""
    data = await file.read()
    row = await svc.upload_attachment(
        session,
        config,
        owner_kind=owner_kind,
        owner_id=owner_id,
        ticket_id=ticket_id,
        filename=file.filename or "unnamed",
        mime=file.content_type or "application/octet-stream",
        data=data,
    )
    return _to_read(row)


@router.get("", response_model=list[NoteAttachmentRead])
async def list_attachments(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[NoteAttachmentRead]:
    """All non-deleted attachments for a ticket (both owner_kinds)."""
    rows = await svc.list_for_ticket(session, ticket_id)
    return [_to_read(r) for r in rows]


@router.get("/{attachment_id}/raw")
async def get_raw(
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_config_dep),
) -> FileResponse:
    """Stream the file bytes inline. `Content-Disposition: inline; filename="…"`."""
    row = await svc.get(session, attachment_id)
    abs_path = config.attachments_dir / row.stored_path
    if not abs_path.exists():
        raise HTTPException(status_code=404, detail="file missing on disk")
    return FileResponse(
        path=abs_path,
        media_type=row.mime,
        filename=row.filename,
        content_disposition_type="inline",
    )


@router.get("/{attachment_id}/thumb")
async def get_thumb(
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_config_dep),
) -> FileResponse:
    """Return the 256px-max-side WebP thumbnail for an image. 404 otherwise."""
    row = await svc.get(session, attachment_id)
    thumb = svc.get_or_make_thumb_path(config, row)
    if thumb is None:
        raise HTTPException(status_code=404, detail="no thumbnail for this mime type")
    return FileResponse(path=thumb, media_type="image/webp")


@router.delete("/{attachment_id}", response_model=NoteAttachmentDeleted)
async def delete_attachment(
    attachment_id: int,
    session: AsyncSession = Depends(get_session),
) -> NoteAttachmentDeleted:
    """Soft-delete. Idempotent on a row already deleted."""
    row = await svc.soft_delete(session, attachment_id)
    return NoteAttachmentDeleted(id=row.id)
```

- [ ] **Step 4: Verify `get_config_dep` exists**

Open `backend/app/deps.py`:

```bash
grep -n get_config_dep backend/app/deps.py || cat backend/app/deps.py | head -40
```

If `get_config_dep` is not defined, add it now. Open `backend/app/deps.py`. If you see a `get_config` import or `Depends(get_config)` usage already, the dep already lives there under a different name. Otherwise append at the end of the file:

```python
from app.config import AppConfig, get_config


def get_config_dep() -> AppConfig:
    """FastAPI dependency wrapper around the cached config singleton."""
    return get_config()
```

If `get_config_dep` does exist under another name (e.g. `get_app_config`), update the import in `app/routers/attachments.py` accordingly. The conftest already overrides `get_config` via `dependency_overrides`, so this dep automatically uses the test config in tests.

- [ ] **Step 5: Register the router + lifespan mkdir**

Open `backend/app/main.py`. Find the imports near line 27-33:

```python
from app.routers import notes as notes_router
from app.routers import note_entries as note_entries_router
```

Add immediately after:

```python
from app.routers import attachments as attachments_router
```

Find the router-registration block (around line 130-138). Insert after `note_entries_router`:

```python
    app.include_router(attachments_router.router)
```

In the same file, find the `lifespan` function. Locate `await init_db(engine, session_factory)` (around line 70). Immediately after that line add:

```python
    config.attachments_dir.mkdir(parents=True, exist_ok=True)
    (config.attachments_dir / "thumbs").mkdir(parents=True, exist_ok=True)
```

- [ ] **Step 6: Run API tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_attachments_api.py -v
```

Expected: all 10 tests pass.

If any test fails with `attachments_dir` permission errors, ensure conftest's `test_config` does NOT pin a specific `attachments_dir` (the default `./data/attachments` is relative to cwd; tests should work but pollute. See Task 7 for the conftest fix that makes this fully hermetic).

- [ ] **Step 7: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/app/routers/attachments.py backend/app/main.py backend/app/deps.py backend/tests/test_attachments_api.py
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): /attachments router (upload, list, raw, thumb, delete)"
```

---

## Task 7: Hermetic test fixture for attachments_dir

**Files:**
- Modify: `backend/tests/conftest.py`

- [ ] **Step 1: Update conftest to use tmp_path for attachments_dir**

Open `backend/tests/conftest.py`. Find `test_config` fixture (around line 23-34). Change its signature to accept `tmp_path_factory` and bind `attachments_dir` to a temp folder:

Replace:
```python
@pytest.fixture
def test_config() -> AppConfig:
    """Config pinned to an in-memory SQLite + dummy secrets.

    SQLAlchemy keeps a single connection alive for `:memory:` (StaticPool), so
    the schema seeded by `init_db` is visible to every session in the test.
    """
    return AppConfig(
        openrouter_api_key="test-openrouter-key",
        database_url="sqlite+aiosqlite:///:memory:",
        cache_ttl_seconds=300,
        ai_concurrency=4,
    )
```

With:
```python
@pytest.fixture
def test_config(tmp_path_factory: pytest.TempPathFactory) -> AppConfig:
    """Config pinned to an in-memory SQLite + dummy secrets + an isolated
    on-disk attachments dir under a pytest tmp path. Each test session gets
    its own attachments tree so uploads do not bleed across tests."""
    attachments_root = tmp_path_factory.mktemp("attachments")
    return AppConfig(
        openrouter_api_key="test-openrouter-key",
        database_url="sqlite+aiosqlite:///:memory:",
        cache_ttl_seconds=300,
        ai_concurrency=4,
        attachments_dir=attachments_root,
    )
```

- [ ] **Step 2: Run full suite to confirm nothing else broke**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: all green (prior 178 + service tests + API tests).

- [ ] **Step 3: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/tests/conftest.py
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "test(attachments): hermetic attachments_dir via tmp_path_factory"
```

---

## Task 8: Background sweep loop

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: Add sweep loop**

Open `backend/app/main.py`. Find the `_cache_sweep_loop` function (around line 40-59). Immediately after it, add:

```python
async def _attachment_sweep_loop(
    session_factory: async_sessionmaker[AsyncSession],
    config: get_config_module.AppConfig,
) -> None:
    """Background loop: hard-delete expired soft-deleted attachments + unlink
    orphaned disk files. Once at startup, then every config.attachment_sweep_interval_seconds."""
    from app.services.attachments import sweep_attachments

    while True:
        try:
            async with session_factory() as session:
                result = await sweep_attachments(session, config)
            if result.rows_deleted or result.files_unlinked:
                log_event(
                    "attachment_sweep",
                    op="background",
                    rows_deleted=result.rows_deleted,
                    files_unlinked=result.files_unlinked,
                )
        except Exception as exc:
            log_event(
                "attachment_sweep_error",
                level=logging.WARNING,
                op="background",
                error=str(exc),
            )
        await asyncio.sleep(config.attachment_sweep_interval_seconds)
```

For the `get_config_module` reference: at the top of `main.py` find:

```python
from app.config import get_config
```

Change it to:

```python
from app import config as get_config_module
from app.config import get_config
```

Then replace the type hint `config: get_config_module.AppConfig` if you prefer to import AppConfig directly — simpler version:

```python
from app.config import AppConfig, get_config
```

…and then the loop signature becomes `config: AppConfig`. Pick one approach and apply consistently.

- [ ] **Step 2: Start + cancel the loop in lifespan**

Inside the `lifespan` function in `main.py`, find where `sweep_task` is created (around line 94-97):

```python
    sweep_task = asyncio.create_task(
        _cache_sweep_loop(session_factory, config.cache_ttl_seconds),
    )
    app.state.sweep_task = sweep_task
```

Insert immediately after:

```python
    attachment_sweep_task = asyncio.create_task(
        _attachment_sweep_loop(session_factory, config),
    )
    app.state.attachment_sweep_task = attachment_sweep_task
```

Find the `finally:` block (around line 102-109) that cancels `sweep_task`:

```python
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
```

Insert immediately after the existing cancel:

```python
        attachment_sweep_task.cancel()
        try:
            await attachment_sweep_task
        except asyncio.CancelledError:
            pass
```

- [ ] **Step 3: Verify the app still boots in tests**

```bash
.venv/Scripts/python.exe -m pytest tests/test_health.py -v
```

Expected: PASS.

- [ ] **Step 4: Run full suite**

```bash
.venv/Scripts/python.exe -m pytest -q
```

Expected: all green.

- [ ] **Step 5: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add backend/app/main.py
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): nightly disk sweep loop in lifespan"
```

---

## Task 9: Webapp — types + API client

**Files:**
- Modify: `webapp/src/types/api.ts`
- Modify: `webapp/src/api/client.ts`

- [ ] **Step 1: Add `NoteAttachment` type**

Open `webapp/src/types/api.ts`. Find the `NoteEntry` interface added by the time-tabled notes spec. Immediately after its closing brace, add:

```typescript
export interface NoteAttachment {
  id: number;
  owner_kind: 'entry' | 'ticket';
  owner_id: string;
  ticket_id: string;
  filename: string;
  mime: string;
  size_bytes: number;
  created_at: string;
  raw_url: string;
  thumb_url: string | null;
}
```

- [ ] **Step 2: Add client methods**

Open `webapp/src/api/client.ts`. Add `NoteAttachment` to the imports at the top:

```typescript
import type {
  BulkResult,
  CategoriesResponse,
  Category,
  FilterSettings,
  Followup,
  NoteAttachment,
  NoteEntry,
  ProposalsResponse,
  ResolvedSource,
  Ticket,
  TicketNote,
} from '@/types/api';
```

Inside the `api` object, immediately after the `// ── note entries (time-tabled notes) ──` block (after `deleteNoteEntry`), add:

```typescript
  // ── attachments (note attachments) ────────────────────────────────────────
  listAttachments: (ticketId: string): Promise<NoteAttachment[]> =>
    request(`/attachments?ticket_id=${encodeURIComponent(ticketId)}`),

  uploadAttachment: (
    file: File,
    ownerKind: 'entry' | 'ticket',
    ownerId: string,
    ticketId: string,
  ): Promise<NoteAttachment> => {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('owner_kind', ownerKind);
    fd.append('owner_id', ownerId);
    fd.append('ticket_id', ticketId);
    // Cannot use `request()` directly — multipart needs no `content-type` header
    // (browser sets the boundary). Replicate the error envelope manually.
    return fetch(`${'/api'}/attachments`, { method: 'POST', body: fd }).then(
      async (resp) => {
        if (!resp.ok) {
          const body = await resp.json().catch(() => ({}));
          throw new Error(`POST /attachments → ${resp.status}: ${JSON.stringify(body)}`);
        }
        return resp.json();
      },
    );
  },

  deleteAttachment: (id: number): Promise<{ ok: true; deleted: true; id: number }> =>
    request(`/attachments/${id}`, { method: 'DELETE' }),
```

- [ ] **Step 3: Typecheck**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/webapp" && npm run typecheck
```

Expected: success.

- [ ] **Step 4: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add webapp/src/types/api.ts webapp/src/api/client.ts
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): webapp NoteAttachment type + API client methods"
```

---

## Task 10: Pinia attachments store

**Files:**
- Create: `webapp/src/stores/attachments.ts`
- Create: `webapp/src/stores/attachments.spec.ts`

- [ ] **Step 1: Write failing store tests**

Create `webapp/src/stores/attachments.spec.ts`:

```typescript
// Note attachments store unit tests.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAttachmentsStore } from './attachments';
import { api } from '@/api/client';
import type { NoteAttachment } from '@/types/api';

vi.mock('@/api/client', () => ({
  api: {
    listAttachments: vi.fn(),
    uploadAttachment: vi.fn(),
    deleteAttachment: vi.fn(),
  },
}));

const mocked = vi.mocked(api);

function make(over: Partial<NoteAttachment> = {}): NoteAttachment {
  return {
    id: 1,
    owner_kind: 'ticket',
    owner_id: 'T1',
    ticket_id: 'T1',
    filename: 'a.txt',
    mime: 'text/plain',
    size_bytes: 1,
    created_at: '2026-05-23T10:00:00Z',
    raw_url: '/api/attachments/1/raw',
    thumb_url: null,
    ...over,
  };
}

describe('attachmentsStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('load() seeds map and marks ticket as loaded', async () => {
    mocked.listAttachments.mockResolvedValue([make({ id: 1 }), make({ id: 2 })]);
    const s = useAttachmentsStore();
    await s.load('T1');
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([1, 2]);
    expect(mocked.listAttachments).toHaveBeenCalledTimes(1);

    await s.load('T1');
    expect(mocked.listAttachments).toHaveBeenCalledTimes(1); // no-op second call
  });

  it('byTicket filters to owner_kind=ticket', async () => {
    mocked.listAttachments.mockResolvedValue([
      make({ id: 1, owner_kind: 'ticket', owner_id: 'T1' }),
      make({ id: 2, owner_kind: 'entry', owner_id: '42' }),
    ]);
    const s = useAttachmentsStore();
    await s.load('T1');
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([1]);
  });

  it('byEntry filters to matching entry id', async () => {
    mocked.listAttachments.mockResolvedValue([
      make({ id: 1, owner_kind: 'entry', owner_id: '42' }),
      make({ id: 2, owner_kind: 'entry', owner_id: '99' }),
      make({ id: 3, owner_kind: 'ticket', owner_id: 'T1' }),
    ]);
    const s = useAttachmentsStore();
    await s.load('T1');
    expect(s.byEntry(42).map((a) => a.id)).toEqual([1]);
    expect(s.byEntry(99).map((a) => a.id)).toEqual([2]);
  });

  it('upload() shows optimistic placeholder then replaces with server row', async () => {
    const saved = make({ id: 100, filename: 'saved.txt' });
    mocked.uploadAttachment.mockResolvedValue(saved);
    const s = useAttachmentsStore();
    const file = new File(['x'], 'saved.txt', { type: 'text/plain' });
    const pending = s.upload(file, 'ticket', 'T1', 'T1');

    // optimistic row appears immediately with a temp negative id.
    expect(s.byTicket('T1').length).toBe(1);
    expect(s.byTicket('T1')[0].id).toBeLessThan(0);

    await pending;
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([100]);
  });

  it('upload() rolls back on server rejection', async () => {
    mocked.uploadAttachment.mockRejectedValue(new Error('500'));
    const s = useAttachmentsStore();
    const file = new File(['x'], 'fail.txt', { type: 'text/plain' });
    await expect(s.upload(file, 'ticket', 'T1', 'T1')).rejects.toThrow();
    expect(s.byTicket('T1')).toEqual([]);
  });

  it('remove() removes optimistically and rolls back on failure', async () => {
    mocked.listAttachments.mockResolvedValue([make({ id: 7 })]);
    const s = useAttachmentsStore();
    await s.load('T1');
    mocked.deleteAttachment.mockRejectedValue(new Error('500'));
    await expect(s.remove(7)).rejects.toThrow();
    expect(s.byTicket('T1').map((a) => a.id)).toEqual([7]);
  });

  it('remove() succeeds and clears the row', async () => {
    mocked.listAttachments.mockResolvedValue([make({ id: 7 })]);
    const s = useAttachmentsStore();
    await s.load('T1');
    mocked.deleteAttachment.mockResolvedValue({ ok: true, deleted: true, id: 7 });
    await s.remove(7);
    expect(s.byTicket('T1')).toEqual([]);
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/webapp" && npx vitest run src/stores/attachments.spec.ts
```

Expected: module-not-found on `./attachments`.

- [ ] **Step 3: Create the store**

Create `webapp/src/stores/attachments.ts`:

```typescript
// Note attachments store. Spec:
// docs/superpowers/specs/2026-05-23-note-attachments-design.md
//
// Lazy load per ticket — `load(ticketId)` is no-op after the first call for a
// given ticket. Uploads are optimistic with a negative temp id; the server-issued
// row replaces it on resolve, or it is dropped on rejection. Removes are
// optimistic too.

import { defineStore } from 'pinia';
import { ref } from 'vue';
import { api } from '@/api/client';
import type { NoteAttachment } from '@/types/api';

export const useAttachmentsStore = defineStore('attachments', () => {
  /** ticket_id → list of attachments (both owner_kinds). */
  const map = ref<Record<string, NoteAttachment[]>>({});
  /** Tickets that have completed a successful load — used to dedupe load() calls. */
  const loadedTickets = ref<Set<string>>(new Set());

  let nextTempId = -1;

  function byTicket(ticketId: string): NoteAttachment[] {
    return (map.value[ticketId] ?? []).filter((a) => a.owner_kind === 'ticket');
  }

  function byEntry(entryId: number): NoteAttachment[] {
    const sId = String(entryId);
    return Object.values(map.value)
      .flat()
      .filter((a) => a.owner_kind === 'entry' && a.owner_id === sId);
  }

  function _appendTo(ticketId: string, row: NoteAttachment): void {
    const prior = map.value[ticketId] ?? [];
    map.value = { ...map.value, [ticketId]: [...prior, row] };
  }

  function _removeFrom(ticketId: string, attachmentId: number): NoteAttachment | undefined {
    const prior = map.value[ticketId] ?? [];
    const removed = prior.find((a) => a.id === attachmentId);
    map.value = { ...map.value, [ticketId]: prior.filter((a) => a.id !== attachmentId) };
    return removed;
  }

  async function load(ticketId: string): Promise<void> {
    if (loadedTickets.value.has(ticketId)) return;
    try {
      const rows = await api.listAttachments(ticketId);
      map.value = { ...map.value, [ticketId]: rows };
      loadedTickets.value = new Set([...loadedTickets.value, ticketId]);
    } catch {
      // leave the map untouched; caller can retry on next flyout open.
    }
  }

  async function upload(
    file: File,
    ownerKind: 'entry' | 'ticket',
    ownerId: string,
    ticketId: string,
  ): Promise<NoteAttachment> {
    const tempId = nextTempId--;
    const optimistic: NoteAttachment = {
      id: tempId,
      owner_kind: ownerKind,
      owner_id: ownerId,
      ticket_id: ticketId,
      filename: file.name,
      mime: file.type || 'application/octet-stream',
      size_bytes: file.size,
      created_at: new Date().toISOString(),
      raw_url: '',
      thumb_url: null,
    };
    _appendTo(ticketId, optimistic);

    try {
      const saved = await api.uploadAttachment(file, ownerKind, ownerId, ticketId);
      const next = (map.value[ticketId] ?? []).map((a) => (a.id === tempId ? saved : a));
      map.value = { ...map.value, [ticketId]: next };
      return saved;
    } catch (e) {
      _removeFrom(ticketId, tempId);
      throw e;
    }
  }

  async function remove(attachmentId: number): Promise<void> {
    // Locate the row across all tickets — ids are unique server-side.
    let ticketId: string | null = null;
    for (const [tid, list] of Object.entries(map.value)) {
      if (list.some((a) => a.id === attachmentId)) {
        ticketId = tid;
        break;
      }
    }
    if (ticketId === null) return;
    const snapshot = map.value[ticketId];
    const removed = _removeFrom(ticketId, attachmentId);
    if (removed === undefined) return;
    try {
      await api.deleteAttachment(attachmentId);
    } catch (e) {
      map.value = { ...map.value, [ticketId]: snapshot };
      throw e;
    }
  }

  return { byTicket, byEntry, load, upload, remove };
});
```

- [ ] **Step 4: Run store tests**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/webapp" && npx vitest run src/stores/attachments.spec.ts
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add webapp/src/stores/attachments.ts webapp/src/stores/attachments.spec.ts
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): attachments Pinia store with optimistic upload + remove"
```

---

## Task 11: Shared `AttachmentList` renderer

**Files:**
- Create: `webapp/src/components/AttachmentList.vue`

- [ ] **Step 1: Create the component**

Create `webapp/src/components/AttachmentList.vue`:

```vue
<!-- Renders a list of NoteAttachment rows as thumbnails (images) and pills
     (non-images). Click a thumbnail to open `raw_url` in a new tab. Each
     attachment has an × button that emits `remove(id)`. Used by both the
     per-entry slot in the timeline and the per-ticket bin. -->
<script setup lang="ts">
import type { NoteAttachment } from '@/types/api';

interface Props {
  items: NoteAttachment[];
}
const props = defineProps<Props>();
const emit = defineEmits<{ (e: 'remove', id: number): void }>();

function isImage(a: NoteAttachment): boolean {
  return a.mime.startsWith('image/');
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}
</script>

<template>
  <div v-if="props.items.length" class="att-list">
    <a
      v-for="a in props.items.filter(isImage)"
      :key="a.id"
      :href="a.raw_url"
      target="_blank"
      rel="noopener"
      class="att-thumb-wrap"
      :title="a.filename"
    >
      <img v-if="a.thumb_url" :src="a.thumb_url" :alt="a.filename" class="att-thumb" />
      <span v-else class="att-thumb att-thumb-placeholder">…</span>
      <button class="att-x" title="Remove" @click.prevent="emit('remove', a.id)">×</button>
    </a>
    <span
      v-for="a in props.items.filter((x) => !isImage(x))"
      :key="a.id"
      class="att-pill"
      :title="a.filename"
    >
      <a :href="a.raw_url" target="_blank" rel="noopener" class="att-pill-link">
        📄 {{ a.filename }} · {{ sizeLabel(a.size_bytes) }}
      </a>
      <button class="att-x att-x-inline" title="Remove" @click.prevent="emit('remove', a.id)">×</button>
    </span>
  </div>
</template>

<style scoped>
.att-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.att-thumb-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  display: inline-block;
}
.att-thumb {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: var(--radius-chip);
  border: var(--hairline) solid var(--line);
  background: var(--panel);
}
.att-thumb-placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-3);
}
.att-x {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: var(--hairline) solid var(--line);
  background: var(--panel);
  color: var(--ink);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}
.att-x:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.att-x-inline {
  position: static;
  width: 16px;
  height: 16px;
  margin-left: 4px;
}
.att-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  font-family: var(--font-mono);
  font-size: 10px;
}
.att-pill-link {
  color: var(--ink);
  text-decoration: none;
}
.att-pill-link:hover {
  color: var(--accent);
}
</style>
```

- [ ] **Step 2: Typecheck**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/webapp" && npm run typecheck
```

Expected: success.

- [ ] **Step 3: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add webapp/src/components/AttachmentList.vue
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): AttachmentList renderer (thumbs + pills + x)"
```

---

## Task 12: `AttachmentDropzone` widget

**Files:**
- Create: `webapp/src/components/AttachmentDropzone.vue`

- [ ] **Step 1: Create the component**

Create `webapp/src/components/AttachmentDropzone.vue`:

```vue
<!-- Drag/drop, paste, or click-to-browse zone. Emits a `files` event with
     the picked File[]. Owns no upload logic — caller decides what to do. -->
<script setup lang="ts">
import { ref } from 'vue';

const emit = defineEmits<{ (e: 'files', files: File[]): void }>();

const hover = ref(false);
const inputRef = ref<HTMLInputElement | null>(null);

function emitFiles(list: FileList | null | undefined) {
  if (!list || list.length === 0) return;
  emit('files', Array.from(list));
}

function onDrop(e: DragEvent) {
  e.preventDefault();
  hover.value = false;
  emitFiles(e.dataTransfer?.files);
}

function onPaste(e: ClipboardEvent) {
  emitFiles(e.clipboardData?.files);
}

function onPick(e: Event) {
  const input = e.target as HTMLInputElement;
  emitFiles(input.files);
  input.value = '';
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ hover }"
    tabindex="0"
    @dragover.prevent="hover = true"
    @dragleave="hover = false"
    @drop="onDrop"
    @paste="onPaste"
    @click="inputRef?.click()"
  >
    <span class="mono dim">Drop files, paste, or click to browse</span>
    <input
      ref="inputRef"
      type="file"
      multiple
      hidden
      @change="onPick"
    />
  </div>
</template>

<style scoped>
.dropzone {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-card);
  background: var(--panel);
  cursor: pointer;
  user-select: none;
  font-size: 11px;
}
.dropzone:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.dropzone.hover {
  border-color: var(--accent);
  background: var(--hover);
}
</style>
```

- [ ] **Step 2: Typecheck**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/webapp" && npm run typecheck
```

Expected: success.

- [ ] **Step 3: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add webapp/src/components/AttachmentDropzone.vue
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): AttachmentDropzone widget (drag, paste, browse)"
```

---

## Task 13: Wire attachments into `TicketFlyout.vue`

**Files:**
- Modify: `webapp/src/components/TicketFlyout.vue`

- [ ] **Step 1: Add imports + store wiring**

Open `webapp/src/components/TicketFlyout.vue`. Locate the existing imports block. After the `useNoteEntriesStore` import, add:

```typescript
import { useAttachmentsStore } from '@/stores/attachments';
import AttachmentList from './AttachmentList.vue';
import AttachmentDropzone from './AttachmentDropzone.vue';
```

After the `const noteEntries = useNoteEntriesStore();` line, add:

```typescript
const attachments = useAttachmentsStore();
```

- [ ] **Step 2: Lazy-load attachments on ticket open**

Find the existing `watch(() => ticket.value?.id, …)` block. Inside its callback, after the entry-state resets, add:

```typescript
    if (id) {
      void attachments.load(id);
    }
```

- [ ] **Step 3: Add pending-attachments state for the new-entry compose**

In the `<script setup>` block, near the other entry refs, add:

```typescript
const pendingFiles = ref<File[]>([]);

function removePending(idx: number) {
  pendingFiles.value = pendingFiles.value.filter((_, i) => i !== idx);
}

function onTextareaPaste(e: ClipboardEvent) {
  const files = e.clipboardData?.files;
  if (!files || files.length === 0) return;
  pendingFiles.value = [...pendingFiles.value, ...Array.from(files)];
}

function onTextareaDrop(e: DragEvent) {
  e.preventDefault();
  const files = e.dataTransfer?.files;
  if (!files || files.length === 0) return;
  pendingFiles.value = [...pendingFiles.value, ...Array.from(files)];
}

function pendingSizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}
```

Reset `pendingFiles.value = [];` inside the same watcher that resets the other entry fields.

- [ ] **Step 4: Update `addEntry` to upload pending files after the entry exists**

Find the existing `addEntry` function. Replace the body with:

```typescript
async function addEntry() {
  const id = ticket.value?.id;
  const body = entryDraft.value.trim();
  if (!id || body.length === 0) return;
  entrySaving.value = true;
  entryError.value = null;
  const armedTimer = entryTimer.value !== null;
  const filesToUpload = pendingFiles.value;
  try {
    const saved = await noteEntries.addEntry(
      id,
      body,
      entryTimer.value,
      entryReason.value.trim() || null,
    );
    if (filesToUpload.length > 0) {
      await Promise.all(
        filesToUpload.map((f) =>
          attachments.upload(f, 'entry', String(saved.id), id),
        ),
      );
    }
    entryDraft.value = '';
    entryReason.value = '';
    entryTimer.value = null;
    pendingFiles.value = [];
    if (armedTimer) {
      await followups.load();
    }
  } catch (e) {
    entryError.value = (e as Error).message;
  } finally {
    entrySaving.value = false;
  }
}
```

- [ ] **Step 5: Add a handler for ticket-bin uploads**

In `<script setup>`, add:

```typescript
async function onTicketFiles(files: File[]) {
  const id = ticket.value?.id;
  if (!id) return;
  try {
    await Promise.all(
      files.map((f) => attachments.upload(f, 'ticket', id, id)),
    );
  } catch (e) {
    entryError.value = (e as Error).message;
  }
}

async function onRemoveAttachment(id: number) {
  try {
    await attachments.remove(id);
  } catch (e) {
    entryError.value = (e as Error).message;
  }
}
```

- [ ] **Step 6: Render — ticket-bin zone above the timeline**

Find the timeline `<ul v-if="entries.length" …>` block. Insert immediately before it (still inside the `Next-step notes` section, after the legacy-note disclosure):

```vue
            <!-- Ticket files (per-ticket attachment bin) -->
            <div v-if="ticket" class="ticket-bin">
              <div class="mono dim ticket-bin-label">Ticket files</div>
              <AttachmentDropzone @files="onTicketFiles" />
              <AttachmentList
                :items="attachments.byTicket(ticket.id)"
                @remove="onRemoveAttachment"
              />
            </div>
```

- [ ] **Step 7: Render — per-entry attachments under each timeline row**

Inside the `<li v-for="e in entries"…>` block, immediately after the `<div v-if="e.timer_min !== null" …>` block (still inside the `<li>`), append:

```vue
                <AttachmentList
                  :items="attachments.byEntry(e.id)"
                  @remove="onRemoveAttachment"
                />
```

- [ ] **Step 8: Render — pending-attachments preview + textarea paste/drop**

Find the new-entry textarea (around `<textarea v-model="entryDraft" …>`). Change it to:

```vue
              <textarea
                v-model="entryDraft"
                class="notes"
                rows="3"
                placeholder="What's the next step? (paste or drop files to attach to this entry)"
                @paste="onTextareaPaste"
                @drop="onTextareaDrop"
                @dragover.prevent
              />
              <div v-if="pendingFiles.length" class="pending-files">
                <span
                  v-for="(f, i) in pendingFiles"
                  :key="i"
                  class="att-pill pending-pill"
                  :title="f.name"
                >
                  <span>📎 {{ f.name }} · {{ pendingSizeLabel(f.size) }}</span>
                  <button class="att-x att-x-inline" title="Remove" @click="removePending(i)">×</button>
                </span>
              </div>
```

- [ ] **Step 9: Add styles**

Append to the `<style scoped>` block (after the existing `.entry-form` rule):

```css
.ticket-bin {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}
.ticket-bin-label {
  margin-top: 4px;
}
.pending-files {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.pending-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px 8px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  font-family: var(--font-mono);
  font-size: 10px;
}
.att-x {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  border: var(--hairline) solid var(--line);
  background: var(--panel);
  color: var(--ink);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}
.att-x:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.att-x-inline {
  margin-left: 4px;
}
```

(If any selector here duplicates one already added in Task 8 of the time-tabled notes plan, leave the existing definition and skip the duplicate.)

- [ ] **Step 10: Typecheck + build**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/webapp" && npm run typecheck && npm run build
```

Expected: success.

- [ ] **Step 11: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add webapp/src/components/TicketFlyout.vue
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "feat(attachments): flyout dropzone + paste/drop on textarea + per-entry render"
```

---

## Task 14: README docs update

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update API table**

Open `README.md`. Find the row added by the time-tabled notes spec:

```
| `POST /notes/entries` · `DELETE /notes/entries/{id}` | Append an entry (optional `timer_min` upserts follow-up); soft-delete by id |
```

Insert immediately after:

```
| `POST /attachments` · `GET /attachments?ticket_id=...` | Multipart upload / list by ticket. `owner_kind` = `entry`\|`ticket` |
| `GET /attachments/{id}/raw` · `GET /attachments/{id}/thumb` | Stream bytes inline / 256px WebP thumbnail for images |
| `DELETE /attachments/{id}` | Soft-delete; nightly sweep removes orphaned bytes after `ATTACHMENT_GC_DAYS` (default 7) |
```

- [ ] **Step 2: Update backup section**

Find the `## Backup` section (around line 154). After the existing line `Copy backend/data/triage.db somewhere — single file.`, append:

```
Attachment files live under `backend/data/attachments/` (content-addressed
by sha256). To back up notes + their files, copy `backend/data/` as a whole.
```

- [ ] **Step 3: Commit**

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add README.md
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "docs(readme): document /attachments endpoints + backup story"
```

---

## Task 15: Final quality-gate sweep

- [ ] **Step 1: Backend gates**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/backend"
.venv/Scripts/python.exe -m ruff check app tests
.venv/Scripts/python.exe -m mypy app
.venv/Scripts/python.exe -m pytest -q
```

Expected: all green. Existing `tests/test_bulk_api.py` formatting drift is pre-existing — leave it.

- [ ] **Step 2: Webapp gates**

```bash
cd "F:/Claude Projects/niche/intercom-ticket-management/webapp"
npm run typecheck
npm run build
npx vitest run
```

Expected: all green.

- [ ] **Step 3: Fix-up commit (if needed)**

If steps 1-2 surfaced lint/type issues introduced by this branch, fix them inline:

```bash
git -C "F:/Claude Projects/niche/intercom-ticket-management" add -A
git -C "F:/Claude Projects/niche/intercom-ticket-management" commit -m "chore: fix lint/type issues from note-attachments rollout"
```

Skip this step if everything was green.

---

## Self-Review (already run; issues fixed inline)

**Spec coverage:**
- Data model — Tasks 2 (ORM + migration).
- Disk layout (sha256 sharding, dedup, content-addressing) — Task 5 (service).
- API surface (POST, GET list, GET raw, GET thumb, DELETE) — Task 6 (router).
- `raw_url` / `thumb_url` derivation — Task 6 (`_to_read`).
- Sweep (GC window, sibling check, thumb cleanup) — Task 5 service + Task 8 lifespan loop.
- Pillow dependency — Task 1.
- Filesystem bootstrap on lifespan — Task 6 step 5.
- Frontend types — Task 9.
- API client — Task 9 (multipart bypasses `request()`).
- Lazy store — Task 10 (load dedup via `loadedTickets`).
- Two zones — Task 12 (dropzone) + Task 13 (textarea paste + per-entry pending).
- Render rules (thumbs vs pills, × delete) — Task 11.
- Tests — Tasks 2, 5, 6 service+api; Task 10 store.
- Hermetic tests — Task 7.
- README — Task 14.
- Quality gates — Task 15.

**Placeholder scan:** None.

**Type consistency:** `NoteAttachment` (TS) mirrors `NoteAttachmentRead` (pydantic) mirrors `NoteAttachment` (ORM). `owner_kind` literal type `'entry' | 'ticket'` matches across layers. `owner_id` is `str` everywhere (never `int`) — entry ids serialized as `String(entry.id)` at the call site in `TicketFlyout.vue`. `raw_url` is always populated by the router (never null); `thumb_url` is null for non-images.

**Out-of-scope items from spec:** No tasks for editing, versioning, EXIF stripping, antivirus, auth on `/raw`, resumable uploads, bulk progress UI, Chrome extension, or per-attachment caps — confirmed YAGNI in the spec.

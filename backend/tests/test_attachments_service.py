"""Service-level tests for note_attachments (spec: note attachments)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.models import NoteAttachment
from app.services import attachments as svc
from app.util import naive_utcnow


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

    found = (await session.scalars(select(NoteAttachment).where(NoteAttachment.id == row.id))).one()
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


def _make_config(tmp_path: Path) -> AppConfig:
    return AppConfig(
        openrouter_api_key="test",
        database_url="sqlite+aiosqlite:///:memory:",
        attachments_dir=tmp_path / "attachments",
    )


@pytest.mark.asyncio
async def test_upload_creates_row_and_disk_file(session: AsyncSession, tmp_path: Path) -> None:
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
    assert row.sha256 == ("b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9")
    assert row.size_bytes == 11
    disk_path = cfg.attachments_dir / row.stored_path
    assert disk_path.exists()
    assert disk_path.read_bytes() == b"hello world"


@pytest.mark.asyncio
async def test_upload_dedupes_same_bytes(session: AsyncSession, tmp_path: Path) -> None:
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
    t = await svc.upload_attachment(session, cfg, "ticket", "T1", "T1", "t.txt", "text/plain", b"t")
    e = await svc.upload_attachment(session, cfg, "entry", "42", "T1", "e.txt", "text/plain", b"e")
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
async def test_sweep_unlinks_orphan_past_gc_window(session: AsyncSession, tmp_path: Path) -> None:
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
async def test_sweep_keeps_file_with_live_sibling(session: AsyncSession, tmp_path: Path) -> None:
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
async def test_get_thumb_path_creates_webp_for_image(session: AsyncSession, tmp_path: Path) -> None:
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

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
from pathlib import Path

import anyio
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
        await anyio.to_thread.run_sync(abs_path.write_bytes, data)

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


async def list_for_ticket(session: AsyncSession, ticket_id: str) -> list[NoteAttachment]:
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


async def get_or_make_thumb_path(config: AppConfig, row: NoteAttachment) -> Path | None:
    """Return the on-disk path to a 256px max-side WebP thumbnail for an image
    attachment. Generated on first request, cached. Returns None for non-images.
    The PIL render step is offloaded to a worker thread to avoid blocking the
    event loop on CPU-bound image I/O."""
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

    def _render() -> None:
        from PIL import Image

        with Image.open(source_path) as im:
            converted = im.convert("RGB")
            converted.thumbnail((256, 256))
            converted.save(thumb_path, format="WEBP", quality=80)

    await anyio.to_thread.run_sync(_render)
    return thumb_path


@dataclass
class SweepResult:
    files_unlinked: int
    rows_deleted: int


async def sweep_attachments(session: AsyncSession, config: AppConfig) -> SweepResult:
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

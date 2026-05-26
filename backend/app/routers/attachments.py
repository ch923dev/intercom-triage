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

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.db import get_session
from app.deps import get_app_config
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
        thumb_url=(f"/api/attachments/{row.id}/thumb" if row.mime.startswith("image/") else None),
    )


@router.post("", response_model=NoteAttachmentRead)
async def post_attachment(
    file: UploadFile = File(...),
    owner_kind: Literal["entry", "ticket"] = Form(...),
    owner_id: str = Form(..., min_length=1),
    ticket_id: str = Form(..., min_length=1),
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
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
    config: AppConfig = Depends(get_app_config),
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
    config: AppConfig = Depends(get_app_config),
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

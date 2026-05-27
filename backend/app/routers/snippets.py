"""Snippets endpoints. Roadmap 1.5 — snippet / canned-response manager.

Thin CRUD over the `snippets` table. Variable substitution is client-side
(see `webapp/src/utils/snippets.ts`); the backend stores and serves bodies
verbatim with `{{variable}}` placeholders intact.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import OkResponse, SnippetCreate, SnippetRead, SnippetUpdate
from app.services import snippets as svc

router = APIRouter(prefix="/snippets", tags=["snippets"])


@router.get("", response_model=list[SnippetRead])
async def list_snippets(
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[SnippetRead]:
    rows = await svc.list_all(session, include_archived)
    return [SnippetRead.model_validate(r) for r in rows]


@router.post("", response_model=SnippetRead)
async def create_snippet(
    body: SnippetCreate,
    session: AsyncSession = Depends(get_session),
) -> SnippetRead:
    row = await svc.create(session, title=body.title, body=body.body)
    return SnippetRead.model_validate(row)


@router.patch("/{snippet_id}", response_model=SnippetRead)
async def update_snippet(
    snippet_id: int,
    body: SnippetUpdate,
    session: AsyncSession = Depends(get_session),
) -> SnippetRead:
    row = await svc.update(session, snippet_id, title=body.title, body=body.body)
    return SnippetRead.model_validate(row)


@router.post("/{snippet_id}/archive", response_model=OkResponse)
async def archive_snippet(
    snippet_id: int,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    await svc.archive(session, snippet_id)
    return OkResponse()


@router.post("/{snippet_id}/restore", response_model=OkResponse)
async def restore_snippet(
    snippet_id: int,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    await svc.restore(session, snippet_id)
    return OkResponse()

"""Snippets — short canned replies with `{{variable}}` placeholders.

Roadmap 1.5. Lighter than playbooks: a snippet is a high-frequency short reply
the operator drops into a conversation, not a durable investigation recipe.
Global (not category-scoped), no AI drafter.

Durable operator-owned knowledge (invariant #13): `snippets` rows are never
keyed by content signature and survive ingest / re-sync untouched — this service
is the only thing that ever writes them. Variable substitution happens
client-side from the ticket the operator is viewing (see
`webapp/src/utils/snippets.ts`); the body is stored verbatim with placeholders
intact, so this service is plain CRUD.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import Snippet
from app.util import naive_utcnow


async def list_all(session: AsyncSession, include_archived: bool = False) -> list[Snippet]:
    stmt = select(Snippet)
    if not include_archived:
        stmt = stmt.where(Snippet.archived_at.is_(None))
    stmt = stmt.order_by(Snippet.created_at.asc(), Snippet.id.asc())
    return list((await session.scalars(stmt)).all())


async def create(session: AsyncSession, title: str, body: str) -> Snippet:
    now = naive_utcnow()
    row = Snippet(title=title, body=body, created_at=now, updated_at=now)
    session.add(row)
    await session.commit()
    await session.refresh(row)
    metrics.incr("snippets_created_total")
    return row


async def update(
    session: AsyncSession,
    snippet_id: int,
    title: str | None,
    body: str | None,
) -> Snippet:
    row = await session.get(Snippet, snippet_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no snippet {snippet_id}")
    if title is not None:
        row.title = title
    if body is not None:
        row.body = body
    row.updated_at = naive_utcnow()
    await session.commit()
    await session.refresh(row)
    metrics.incr("snippets_updated_total")
    return row


async def archive(session: AsyncSession, snippet_id: int) -> Snippet:
    row = await session.get(Snippet, snippet_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no snippet {snippet_id}")
    if row.archived_at is None:
        row.archived_at = naive_utcnow()
        await session.commit()
        await session.refresh(row)
        metrics.incr("snippets_archived_total")
    return row


async def restore(session: AsyncSession, snippet_id: int) -> Snippet:
    row = await session.get(Snippet, snippet_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no snippet {snippet_id}")
    if row.archived_at is not None:
        row.archived_at = None
        await session.commit()
        await session.refresh(row)
    return row

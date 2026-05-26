"""Playbooks — reusable next-steps recipes scoped to a category.

Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md

Read-only lens over existing tables plus its own `playbooks` rows. Durable
operator-owned data — never keyed by content signature, never auto-busted.
The AI drafter reuses the OpenRouter client and excludes `internal_notes`
(invariant #4); only customer-visible `parts` + operator notes feed the prompt.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.metrics import metrics
from app.models import Playbook
from app.util import naive_utcnow


async def list_for_category(
    session: AsyncSession,
    category_id: int,
    include_archived: bool = False,
) -> list[Playbook]:
    stmt = select(Playbook).where(Playbook.category_id == category_id)
    if not include_archived:
        stmt = stmt.where(Playbook.archived_at.is_(None))
    stmt = stmt.order_by(Playbook.created_at.asc(), Playbook.id.asc())
    return list((await session.scalars(stmt)).all())


async def create(
    session: AsyncSession,
    category_id: int,
    label: str,
    body: str,
    source_ticket_id: str | None = None,
) -> Playbook:
    now = naive_utcnow()
    row = Playbook(
        category_id=category_id,
        label=label,
        body=body,
        source_ticket_id=source_ticket_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    metrics.incr("playbooks_created_total")
    return row


async def archive(session: AsyncSession, playbook_id: int) -> Playbook:
    row = await session.get(Playbook, playbook_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no playbook {playbook_id}")
    if row.archived_at is None:
        row.archived_at = naive_utcnow()
        await session.commit()
        await session.refresh(row)
        metrics.incr("playbooks_archived_total")
    return row

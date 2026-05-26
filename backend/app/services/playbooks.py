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
from app.models import Override, Playbook, Ticket
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


async def list_for_ticket(session: AsyncSession, ticket_id: str) -> list[Playbook]:
    """Active playbooks for the ticket's *effective* category.

    Effective category = ticket.category_id, unless a manual override is newer
    than the ticket's last update (override beats AI — mirrors the board's
    composition rule). Uncategorized tickets return an empty list.
    """
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"no ticket {ticket_id}")
    category_id = ticket.category_id
    override = await session.get(Override, ticket_id)
    if override is not None and ticket.updated_at <= override.set_at:
        category_id = override.category_id
    if category_id is None:
        return []
    return await list_for_category(session, category_id)


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


async def update(
    session: AsyncSession,
    playbook_id: int,
    label: str | None,
    body: str | None,
) -> Playbook:
    row = await session.get(Playbook, playbook_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no playbook {playbook_id}")
    if label is not None:
        row.label = label
    if body is not None:
        row.body = body
    row.updated_at = naive_utcnow()
    await session.commit()
    await session.refresh(row)
    metrics.incr("playbooks_updated_total")
    return row


async def restore(session: AsyncSession, playbook_id: int) -> Playbook:
    row = await session.get(Playbook, playbook_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no playbook {playbook_id}")
    if row.archived_at is not None:
        row.archived_at = None
        await session.commit()
        await session.refresh(row)
    return row


async def list_all(session: AsyncSession, include_archived: bool = False) -> list[Playbook]:
    stmt = select(Playbook)
    if not include_archived:
        stmt = stmt.where(Playbook.archived_at.is_(None))
    stmt = stmt.order_by(Playbook.category_id.asc(), Playbook.created_at.asc(), Playbook.id.asc())
    return list((await session.scalars(stmt)).all())

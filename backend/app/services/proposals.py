"""Proposal curation. Reference: plan.md §8, tasks.md T021–T024."""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import normalize_signature
from app.metrics import metrics
from app.models import (
    AICacheEntry,
    Category,
    CategoryProposal,
    RejectedProposalSignature,
)
from app.services.categories import get_fallback
from app.util import naive_utcnow

_EXAMPLE_LIMIT = 5


async def _get_pending(session: AsyncSession, proposal_id: int) -> CategoryProposal:
    proposal = await session.get(CategoryProposal, proposal_id)
    if proposal is None:
        raise HTTPException(status_code=404, detail=f"proposal {proposal_id} not found")
    if proposal.status != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"proposal {proposal_id} is already {proposal.status}",
        )
    return proposal


# ── T021 — list ───────────────────────────────────────────────────────────────


async def list_pending(
    session: AsyncSession,
) -> list[tuple[CategoryProposal, list[str]]]:
    """Pending proposals, each paired with up to 5 example ticket ids drawn from
    the cache rows currently grouped under that proposal. Examples are fetched in
    a single batched query (not one query per proposal)."""
    proposals = (
        await session.scalars(
            select(CategoryProposal)
            .where(CategoryProposal.status == "pending")
            .order_by(CategoryProposal.created_at.asc(), CategoryProposal.id.asc()),
        )
    ).all()
    if not proposals:
        return []

    proposal_ids = [p.id for p in proposals]
    rows = (
        await session.execute(
            select(AICacheEntry.proposal_id, AICacheEntry.ticket_id)
            .where(AICacheEntry.proposal_id.in_(proposal_ids))
            .order_by(AICacheEntry.proposal_id.asc(), AICacheEntry.ticket_id.asc()),
        )
    ).all()

    examples: dict[int, list[str]] = {}
    for proposal_id, ticket_id in rows:
        bucket = examples.setdefault(proposal_id, [])
        if len(bucket) < _EXAMPLE_LIMIT:
            bucket.append(ticket_id)

    return [(proposal, examples.get(proposal.id, [])) for proposal in proposals]


# ── T022 — approve ────────────────────────────────────────────────────────────


async def approve_proposal(
    session: AsyncSession,
    proposal_id: int,
    *,
    color: str | None,
    sort_order: int | None,
) -> Category:
    """Create a new active category from the proposal; repoint cache rows."""
    proposal = await _get_pending(session, proposal_id)

    clash = await session.scalar(
        select(Category.id).where(
            Category.is_active.is_(True),
            Category.name == proposal.name,
        ),
    )
    if clash is not None:
        raise HTTPException(
            status_code=409,
            detail=f"an active category named {proposal.name!r} already exists",
        )

    if sort_order is None:
        max_order = await session.scalar(select(func.max(Category.sort_order)))
        sort_order = int(max_order or 0) + 1

    category = Category(
        name=proposal.name,
        description=proposal.description,
        color=color,
        sort_order=sort_order,
        source="ai_proposed",
        is_active=True,
        is_fallback=False,
    )
    session.add(category)
    await session.flush()  # assigns category.id

    await session.execute(
        update(AICacheEntry)
        .where(AICacheEntry.proposal_id == proposal_id)
        .values(category_id=category.id, proposal_id=None),
    )
    proposal.status = "approved"
    proposal.resolved_category_id = category.id
    proposal.resolved_at = naive_utcnow()

    await session.commit()
    await session.refresh(category)
    metrics.incr("proposals_resolved_total.approved")
    return category


# ── T023 — merge into an existing category ────────────────────────────────────


async def merge_proposal(
    session: AsyncSession,
    proposal_id: int,
    category_id: int,
) -> int:
    """Reassign the proposal's tickets to an existing category. Returns moved count."""
    proposal = await _get_pending(session, proposal_id)
    target = await session.get(Category, category_id)
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail=f"category {category_id} not found")

    moved = await session.scalar(
        select(func.count())
        .select_from(AICacheEntry)
        .where(AICacheEntry.proposal_id == proposal_id),
    )
    await session.execute(
        update(AICacheEntry)
        .where(AICacheEntry.proposal_id == proposal_id)
        .values(category_id=category_id, proposal_id=None),
    )
    proposal.status = "merged"
    proposal.resolved_category_id = category_id
    proposal.resolved_at = naive_utcnow()

    await session.commit()
    metrics.incr("proposals_resolved_total.merged")
    return int(moved or 0)


# ── T024 — reject ─────────────────────────────────────────────────────────────


async def reject_proposal(session: AsyncSession, proposal_id: int) -> None:
    """Move the proposal's tickets to the fallback; record a rejected signature so
    the AI does not re-propose the same name."""
    proposal = await _get_pending(session, proposal_id)
    fallback = await get_fallback(session)

    await session.execute(
        update(AICacheEntry)
        .where(AICacheEntry.proposal_id == proposal_id)
        .values(category_id=fallback.id, proposal_id=None),
    )
    proposal.status = "rejected"
    proposal.resolved_category_id = fallback.id
    proposal.resolved_at = naive_utcnow()

    signature = normalize_signature(proposal.name)
    if await session.get(RejectedProposalSignature, signature) is None:
        session.add(
            RejectedProposalSignature(
                signature=signature,
                rejected_name=proposal.name,
            ),
        )

    await session.commit()
    metrics.incr("proposals_resolved_total.rejected")

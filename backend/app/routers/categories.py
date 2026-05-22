"""`GET /categories` — active categories + pending proposals.

Reference: plan.md §4 (API contract), tasks.md T007.

Future task slots (POST/PATCH/archive/merge) attach to the same router in
Phase 4 (T018, T020).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Category, CategoryProposal
from app.schemas import CategoriesResponse, CategoryProposalRead, CategoryRead

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=CategoriesResponse)
async def list_categories(session: AsyncSession = Depends(get_session)) -> CategoriesResponse:
    """Return active categories + pending proposals in display order.

    Order: categories by `sort_order` ascending (then id), proposals by `created_at`.
    Proposals are returned as a sibling list rather than mixed in — the client
    composes the column strip from both.
    """
    cat_rows = (
        await session.scalars(
            select(Category)
            .where(Category.is_active.is_(True))
            .order_by(Category.sort_order.asc(), Category.id.asc()),
        )
    ).all()

    proposal_rows = (
        await session.scalars(
            select(CategoryProposal)
            .where(CategoryProposal.status == "pending")
            .order_by(CategoryProposal.created_at.asc(), CategoryProposal.id.asc()),
        )
    ).all()

    return CategoriesResponse(
        categories=[CategoryRead.model_validate(c) for c in cat_rows],
        pending_proposals=[CategoryProposalRead.model_validate(p) for p in proposal_rows],
    )

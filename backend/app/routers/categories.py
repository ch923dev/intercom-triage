"""Category endpoints. Reference: plan.md §4, tasks.md T007, T018–T020."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.models import Category, CategoryProposal
from app.schemas import (
    CategoriesResponse,
    CategoryCreate,
    CategoryPatch,
    CategoryProposalRead,
    CategoryRead,
    MergeResponse,
    OkResponse,
)
from app.services import categories as svc

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=CategoriesResponse)
async def list_categories(session: AsyncSession = Depends(get_session)) -> CategoriesResponse:
    """T007 — active categories + pending proposals in display order."""
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


@router.post("", response_model=CategoryRead, status_code=201)
async def create_category(
    body: CategoryCreate,
    session: AsyncSession = Depends(get_session),
) -> CategoryRead:
    """T018 — create an active category."""
    category = await svc.create_category(session, body)
    return CategoryRead.model_validate(category)


@router.patch("/{category_id}", response_model=CategoryRead)
async def patch_category(
    category_id: int,
    body: CategoryPatch,
    session: AsyncSession = Depends(get_session),
) -> CategoryRead:
    """T018 — rename / recolor / reorder; id is preserved."""
    category = await svc.patch_category(session, category_id, body)
    return CategoryRead.model_validate(category)


@router.post("/{category_id}/archive", response_model=OkResponse)
async def archive_category(
    category_id: int,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """T018 + T019 — archive and sweep dependent rows to the fallback."""
    await svc.archive_category(session, category_id)
    return OkResponse()


@router.post("/{src_id}/merge-into/{dst_id}", response_model=MergeResponse)
async def merge_categories(
    src_id: int,
    dst_id: int,
    session: AsyncSession = Depends(get_session),
) -> MergeResponse:
    """T020 — move all tickets from `src` to `dst`, archive `src`."""
    moved = await svc.merge_categories(session, src_id, dst_id)
    return MergeResponse(moved_count=moved)

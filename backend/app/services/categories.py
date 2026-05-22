"""Category management. Reference: plan.md §8, tasks.md T018–T020.

Services raise `fastapi.HTTPException` directly — routers stay thin.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AICacheEntry, Category, Override
from app.schemas import CategoryCreate, CategoryPatch
from app.util import naive_utcnow


async def _get_active(session: AsyncSession, category_id: int) -> Category:
    category = await session.get(Category, category_id)
    if category is None or not category.is_active:
        raise HTTPException(status_code=404, detail=f"category {category_id} not found")
    return category


async def get_fallback(session: AsyncSession) -> Category:
    category = await session.scalar(
        select(Category).where(Category.is_fallback.is_(True)),
    )
    if category is None:
        raise RuntimeError("no fallback category — DB was not seeded")
    return category


# ── T018 — create / patch / archive ───────────────────────────────────────────


async def create_category(session: AsyncSession, data: CategoryCreate) -> Category:
    clash = await session.scalar(
        select(Category.id).where(
            Category.is_active.is_(True),
            Category.name == data.name,
        ),
    )
    if clash is not None:
        raise HTTPException(status_code=409, detail=f"category {data.name!r} already exists")

    category = Category(
        name=data.name,
        description=data.description,
        color=data.color,
        sort_order=data.sort_order,
        source="user_created",
        is_active=True,
        is_fallback=False,
    )
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return category


async def patch_category(
    session: AsyncSession,
    category_id: int,
    data: CategoryPatch,
) -> Category:
    category = await _get_active(session, category_id)
    if data.name is not None:
        category.name = data.name
    if data.description is not None:
        category.description = data.description
    if data.color is not None:
        category.color = data.color
    if data.sort_order is not None:
        category.sort_order = data.sort_order
    await session.commit()
    await session.refresh(category)
    return category


async def archive_category(session: AsyncSession, category_id: int) -> None:
    """Archive a category and sweep dependent rows to the fallback (T018 + T019)."""
    category = await _get_active(session, category_id)
    if category.is_fallback:
        raise HTTPException(status_code=409, detail="the fallback category cannot be archived")

    fallback = await get_fallback(session)
    category.is_active = False
    category.archived_at = naive_utcnow()

    # T019 — inline sweep, same transaction.
    await session.execute(
        update(AICacheEntry)
        .where(AICacheEntry.category_id == category_id)
        .values(category_id=fallback.id),
    )
    await session.execute(
        update(Override).where(Override.category_id == category_id).values(category_id=fallback.id),
    )
    await session.commit()


# ── T020 — merge ──────────────────────────────────────────────────────────────


async def merge_categories(session: AsyncSession, src_id: int, dst_id: int) -> int:
    """Move every ticket from `src` to `dst`, archive `src`. Returns moved count."""
    if src_id == dst_id:
        raise HTTPException(status_code=409, detail="cannot merge a category into itself")
    src = await _get_active(session, src_id)
    await _get_active(session, dst_id)  # validates dst exists + active
    if src.is_fallback:
        raise HTTPException(status_code=409, detail="the fallback category cannot be archived")

    moved = await session.scalar(
        select(func.count()).select_from(AICacheEntry).where(AICacheEntry.category_id == src_id),
    )

    await session.execute(
        update(AICacheEntry).where(AICacheEntry.category_id == src_id).values(category_id=dst_id),
    )
    await session.execute(
        update(Override).where(Override.category_id == src_id).values(category_id=dst_id),
    )
    src.is_active = False
    src.archived_at = naive_utcnow()
    await session.commit()
    return int(moved or 0)

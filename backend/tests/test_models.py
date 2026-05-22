"""T006 — schema creation, seeding, XOR constraint, FK enforcement."""

from __future__ import annotations

from datetime import UTC

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db import make_engine, make_session_factory
from app.models import (
    AICacheEntry,
    Category,
    Settings,
    init_db,
)


@pytest.mark.asyncio
async def test_init_db_seeds_seven_categories() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with factory() as session:
            cats = (await session.scalars(select(Category).order_by(Category.sort_order))).all()
            assert len(cats) == 7
            assert {c.name for c in cats} == {
                "Urgent",
                "Bug",
                "Feature Request",
                "Question",
                "Billing",
                "Complaint",
                "Other",
            }
            fallbacks = [c for c in cats if c.is_fallback]
            assert len(fallbacks) == 1 and fallbacks[0].name == "Other"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_is_idempotent() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        await init_db(engine, factory)
        async with factory() as session:
            count = len((await session.scalars(select(Category))).all())
            assert count == 7
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_inserts_singleton_settings() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with factory() as session:
            row = await session.scalar(select(Settings).where(Settings.id == 1))
            assert row is not None
            assert row.lookback_unit == "hours"
            assert row.lookback_value == 24
            assert row.states == ["open"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ai_cache_xor_rejects_both_set() -> None:
    """Inserting an ai_cache row with both category_id AND proposal_id must fail."""
    from datetime import datetime

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with factory() as session:
            # Pick an existing seeded category id.
            cat = await session.scalar(select(Category).limit(1))
            assert cat is not None

            session.add(
                AICacheEntry(
                    ticket_id="conv_test_xor",
                    category_id=cat.id,
                    proposal_id=1,  # non-existent but check fires before FK
                    summary="x",
                    confidence=0.5,
                    ticket_updated_at=datetime.now(UTC),
                ),
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ai_cache_xor_rejects_neither_set() -> None:
    from datetime import datetime

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with factory() as session:
            session.add(
                AICacheEntry(
                    ticket_id="conv_test_xor_none",
                    category_id=None,
                    proposal_id=None,
                    summary="x",
                    confidence=0.5,
                    ticket_updated_at=datetime.now(UTC),
                ),
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()

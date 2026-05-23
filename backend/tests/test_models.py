"""T006 — schema creation, seeding, XOR constraint, FK enforcement."""

from __future__ import annotations

from datetime import UTC

import pytest
from sqlalchemy import inspect as sqla_inspect
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from app.db import make_engine, make_session_factory
from app.models import (
    _ALEMBIC_INI,
    AICacheEntry,
    Category,
    Followup,
    Settings,
    TicketNote,
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


@pytest.mark.asyncio
async def test_init_db_creates_followup_and_note_tables() -> None:
    """T045 — fresh boot creates `followups` + `ticket_notes` with `mute_alarms`."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with factory() as session:
            assert (await session.scalars(select(Followup))).all() == []
            assert (await session.scalars(select(TicketNote))).all() == []
            row = await session.scalar(select(Settings).where(Settings.id == 1))
            assert row is not None and row.mute_alarms is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_alembic_version_matches_head() -> None:
    """After init_db, alembic_version row must equal the current head revision.

    This pins the contract: if a new migration is added without updating the
    head, or if the version table is not stamped correctly, this test fails.
    """
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        # Determine expected head from the script directory.
        alembic_cfg = AlembicConfig(str(_ALEMBIC_INI))
        script = ScriptDirectory.from_config(alembic_cfg)
        head_revision = script.get_current_head()

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            rows = result.fetchall()

        assert len(rows) == 1, "Expected exactly one row in alembic_version"
        assert (
            rows[0][0] == head_revision
        ), f"alembic_version={rows[0][0]!r} but expected head={head_revision!r}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_stamps_preexisting_schema() -> None:
    """A DB created by the old pre-Alembic path has all the app tables but no
    `alembic_version`. init_db must stamp the head revision instead of trying
    to re-run migration 0001 (which would fail with 'table already exists')."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "preexisting.db"
        url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

        # Pretend the legacy create_all path ran: build the schema directly
        # from Base.metadata, no alembic_version table.
        from app.models import Base

        engine = make_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
        finally:
            await engine.dispose()

        # Now init_db on the same file. Must NOT raise (the bug was an
        # OperationalError: table already exists). Must stamp head.
        engine = make_engine(url)
        factory = make_session_factory(engine)
        try:
            await init_db(engine, factory)
            alembic_cfg = AlembicConfig(str(_ALEMBIC_INI))
            script = ScriptDirectory.from_config(alembic_cfg)
            head_revision = script.get_current_head()

            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
            assert row is not None and row[0] == head_revision
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_init_db_stamps_after_failed_prior_boot() -> None:
    """A prior failed migration leaves alembic_version present but EMPTY
    (SQLite commits the DDL non-transactionally; the row insert never runs).
    init_db must treat that the same as a missing version table and stamp
    head, not re-run migrations from scratch."""
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "halfmigrated.db"
        url = f"sqlite+aiosqlite:///{db_path.as_posix()}"

        from app.models import Base

        engine = make_engine(url)
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
                # Mirror the relic of a failed Alembic boot: the version table
                # exists but no row was ever inserted.
                await conn.execute(
                    text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"),
                )
        finally:
            await engine.dispose()

        engine = make_engine(url)
        factory = make_session_factory(engine)
        try:
            await init_db(engine, factory)
            alembic_cfg = AlembicConfig(str(_ALEMBIC_INI))
            script = ScriptDirectory.from_config(alembic_cfg)
            head_revision = script.get_current_head()
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT version_num FROM alembic_version"))
                row = result.fetchone()
            assert row is not None and row[0] == head_revision
        finally:
            await engine.dispose()


@pytest.mark.asyncio
async def test_followup_reason_length_constraint() -> None:
    """T045 — a follow-up reason longer than 80 chars is rejected."""
    from datetime import datetime

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with factory() as session:
            session.add(
                Followup(
                    ticket_id="conv_long_reason",
                    due_at=datetime.now(UTC).replace(tzinfo=None),
                    reason="x" * 100,
                ),
            )
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


# ── Ticket-resolution schema tests (Task 1) ───────────────────────────────────


@pytest.mark.asyncio
async def test_ticket_has_resolution_columns() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with engine.connect() as conn:
            cols = {
                c["name"]
                for c in await conn.run_sync(
                    lambda sync_conn: sqla_inspect(sync_conn).get_columns("tickets")
                )
            }
        assert {
            "resolved_at",
            "resolved_source",
            "ai_resolve_enabled",
            "resolution_chip_dismissed_at",
        }.issubset(cols)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ticket_resolution_xor_check() -> None:
    """resolved_at and resolved_source must be both null or both non-null."""
    from app.models import Ticket
    from app.util import naive_utcnow

    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with factory() as session:
            ticket = Ticket(
                id="t1",
                title="x",
                state="open",
                author={},
                parts=[],
                created_at=naive_utcnow(),
                updated_at=naive_utcnow(),
                resolved_at=naive_utcnow(),
                resolved_source=None,  # one null, other not → must fail
            )
            session.add(ticket)
            with pytest.raises(IntegrityError):
                await session.commit()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ai_cache_has_resolution_columns() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with engine.connect() as conn:
            cols = {
                c["name"]
                for c in await conn.run_sync(
                    lambda sync_conn: sqla_inspect(sync_conn).get_columns("ai_cache")
                )
            }
        assert {
            "ai_resolution_verdict",
            "ai_resolution_confidence",
            "ai_resolution_reason",
        }.issubset(cols)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_settings_has_resolution_columns() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    factory = make_session_factory(engine)
    try:
        await init_db(engine, factory)
        async with engine.connect() as conn:
            cols = {
                c["name"]
                for c in await conn.run_sync(
                    lambda sync_conn: sqla_inspect(sync_conn).get_columns("settings")
                )
            }
        assert {"ai_resolve_default", "ai_resolve_confidence_threshold"}.issubset(cols)
    finally:
        await engine.dispose()

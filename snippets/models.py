"""SQLAlchemy 2.0 async models for the local triage tool.

Replaces the v1.1 Alembic migration. Schema is created via
`Base.metadata.create_all` on first startup (see `init_db` below), then seeded
with the seven default categories and the singleton settings row.

Works against SQLite by default (`sqlite+aiosqlite:///./data/triage.db`) and
against Postgres by swapping `DATABASE_URL` (`postgresql+asyncpg://...`). No
dialect-specific types are used — JSON columns use SQLAlchemy's portable JSON
type which maps to JSONB on Postgres and TEXT-with-JSON-fns on SQLite.

Reference: plan.md §5 (data model), tasks.md T006.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Text,
    text,
    select,
)
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# ── Base ──────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Declarative base. Add `naming_convention` here if you later move to Alembic."""
    pass


# ── Tables ────────────────────────────────────────────────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True)
    name:         Mapped[str]            = mapped_column(Text, nullable=False)
    description:  Mapped[str]            = mapped_column(Text, nullable=False)
    color:        Mapped[str | None]     = mapped_column(Text)
    sort_order:   Mapped[int]            = mapped_column(Integer, default=0, nullable=False)
    is_active:    Mapped[bool]           = mapped_column(default=True, nullable=False)
    is_fallback:  Mapped[bool]           = mapped_column(default=False, nullable=False)
    source:       Mapped[str]            = mapped_column(Text, nullable=False)
    created_at:   Mapped[datetime]       = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    archived_at:  Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "source IN ('seed', 'ai_proposed', 'user_created')",
            name="categories_source_check",
        ),
        # One row per (name) among active rows; archived rows can reuse names.
        Index(
            "ux_categories_name_active",
            "name",
            unique=True,
            sqlite_where=text("is_active"),
            postgresql_where=text("is_active"),
        ),
        # Exactly one fallback row across the table.
        Index(
            "ux_categories_fallback",
            "is_fallback",
            unique=True,
            sqlite_where=text("is_fallback"),
            postgresql_where=text("is_fallback"),
        ),
    )


class CategoryProposal(Base):
    __tablename__ = "category_proposals"

    id:                   Mapped[int]            = mapped_column(Integer, primary_key=True)
    name:                 Mapped[str]            = mapped_column(Text, nullable=False)
    description:          Mapped[str]            = mapped_column(Text, nullable=False)
    example_ticket_ids:   Mapped[list[str]]      = mapped_column(JSON, default=list, nullable=False)
    status:               Mapped[str]            = mapped_column(Text, default="pending", nullable=False)
    resolved_category_id: Mapped[int | None]     = mapped_column(ForeignKey("categories.id", ondelete="SET NULL"))
    created_at:           Mapped[datetime]       = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)
    resolved_at:          Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'merged', 'rejected')",
            name="proposals_status_check",
        ),
        Index("ix_proposals_status", "status"),
        # Two pending proposals can't share a name; resolved ones can.
        Index(
            "ux_proposals_name_pending",
            "name",
            unique=True,
            sqlite_where=text("status = 'pending'"),
            postgresql_where=text("status = 'pending'"),
        ),
    )


class AICacheEntry(Base):
    __tablename__ = "ai_cache"

    ticket_id:         Mapped[str]            = mapped_column(Text, primary_key=True)
    category_id:       Mapped[int | None]     = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    proposal_id:       Mapped[int | None]     = mapped_column(ForeignKey("category_proposals.id", ondelete="CASCADE"))
    summary:           Mapped[str]            = mapped_column(Text, nullable=False)
    confidence:        Mapped[float]          = mapped_column(Float, nullable=False)
    ticket_updated_at: Mapped[datetime]       = mapped_column(DateTime, nullable=False)
    cached_at:         Mapped[datetime]       = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)

    __table_args__ = (
        # XOR: exactly one of category_id, proposal_id is set.
        # In SQL: (a IS NULL) <> (b IS NULL) evaluates TRUE iff exactly one is NULL.
        CheckConstraint(
            "(category_id IS NULL) <> (proposal_id IS NULL)",
            name="ai_cache_xor_check",
        ),
        # Used by proposal-resolution sweeps (T022/T023/T024).
        Index(
            "ix_ai_cache_proposal",
            "proposal_id",
            sqlite_where=text("proposal_id IS NOT NULL"),
            postgresql_where=text("proposal_id IS NOT NULL"),
        ),
        # Used by archive sweep (T019) and merge (T020).
        Index(
            "ix_ai_cache_category",
            "category_id",
            sqlite_where=text("category_id IS NOT NULL"),
            postgresql_where=text("category_id IS NOT NULL"),
        ),
    )


class Override(Base):
    __tablename__ = "overrides"

    ticket_id:   Mapped[str]      = mapped_column(Text, primary_key=True)
    category_id: Mapped[int]      = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"), nullable=False)
    set_at:      Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)

    __table_args__ = (Index("ix_overrides_category", "category_id"),)


class Settings(Base):
    """Singleton — enforced by `CHECK (id = 1)`. The app inserts the row on first boot."""
    __tablename__ = "settings"

    id:                    Mapped[int]               = mapped_column(Integer, primary_key=True)
    lookback_unit:         Mapped[str]               = mapped_column(Text, default="hours", nullable=False)
    lookback_value:        Mapped[int]               = mapped_column(Integer, default=24, nullable=False)
    states:                Mapped[list[str]]         = mapped_column(JSON, default=lambda: ["open"], nullable=False)
    include_category_ids:  Mapped[list[int] | None]  = mapped_column(JSON)  # null = all
    updated_at:            Mapped[datetime]          = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)

    __table_args__ = (
        CheckConstraint("id = 1", name="settings_singleton_check"),
        CheckConstraint("lookback_unit IN ('hours', 'days')", name="settings_unit_check"),
        CheckConstraint("lookback_value BETWEEN 1 AND 720", name="settings_value_check"),
    )


class RejectedProposalSignature(Base):
    """Prevents the AI from re-proposing the same category after the user rejects it."""
    __tablename__ = "rejected_proposal_signatures"

    signature:     Mapped[str]      = mapped_column(Text, primary_key=True)
    rejected_name: Mapped[str]      = mapped_column(Text, nullable=False)
    rejected_at:   Mapped[datetime] = mapped_column(DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False)


# ── Seed data ─────────────────────────────────────────────────────────────────

DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {"name": "Urgent",          "description": "Outage, data loss, security incident, blocking issue, or angry customer threatening churn.", "color": "#ef4444", "sort_order": 0, "is_fallback": False},
    {"name": "Bug",             "description": "Something is broken or behaving unexpectedly (and is not urgent).",                          "color": "#f59e0b", "sort_order": 1, "is_fallback": False},
    {"name": "Feature Request", "description": "Customer is asking for capability that doesn't exist.",                                       "color": "#8b5cf6", "sort_order": 2, "is_fallback": False},
    {"name": "Question",        "description": "How-to, clarification, or a docs gap.",                                                       "color": "#3b82f6", "sort_order": 3, "is_fallback": False},
    {"name": "Billing",         "description": "Invoices, charges, plan changes, refunds, payment failures.",                                "color": "#10b981", "sort_order": 4, "is_fallback": False},
    {"name": "Complaint",       "description": "Dissatisfaction without a specific bug (UX, support quality, pricing).",                     "color": "#ec4899", "sort_order": 5, "is_fallback": False},
    {"name": "Other",           "description": "Anything that genuinely doesn't fit the categories above.",                                  "color": "#6b7280", "sort_order": 6, "is_fallback": True },
]


# ── Init + seed ───────────────────────────────────────────────────────────────

def make_engine(database_url: str) -> AsyncEngine:
    """SQLite needs `check_same_thread=False` via the URL, but aiosqlite handles it.
    For Postgres just pass the postgresql+asyncpg URL."""
    return create_async_engine(database_url, future=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db(engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Create schema if missing; seed defaults + singleton settings row if empty.

    Call from the FastAPI lifespan hook. Idempotent — re-runs leave existing data alone.
    """
    async with engine.begin() as conn:
        # For SQLite we want foreign keys enforced — off by default.
        if engine.dialect.name == "sqlite":
            await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # Seed categories if empty.
        existing = await session.scalar(select(Category.id).limit(1))
        if existing is None:
            for spec in DEFAULT_CATEGORIES:
                session.add(Category(source="seed", is_active=True, **spec))
            await session.flush()

        # Insert singleton settings row if missing.
        settings_row = await session.scalar(select(Settings).where(Settings.id == 1))
        if settings_row is None:
            session.add(Settings(id=1))

        await session.commit()


# ── Inline smoke test ─────────────────────────────────────────────────────────
#
# Run `python models.py` to spin up an in-memory DB and verify schema + seeds.

if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        engine = make_engine("sqlite+aiosqlite:///:memory:")
        session_factory = make_session_factory(engine)
        await init_db(engine, session_factory)

        async with session_factory() as session:
            cats = (await session.scalars(select(Category).order_by(Category.sort_order))).all()
            print(f"Seeded {len(cats)} categories:")
            for c in cats:
                marker = " (fallback)" if c.is_fallback else ""
                print(f"  {c.sort_order}. {c.name}{marker}")

            settings = await session.scalar(select(Settings))
            print(f"\nSettings: lookback={settings.lookback_value} {settings.lookback_unit}, states={settings.states}")

        await engine.dispose()

    asyncio.run(main())

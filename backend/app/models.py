"""SQLAlchemy 2.0 async models for the local triage tool.

Ported from `snippets/models.py` (reference). Schema is created via
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
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    select,
    text,
)
from sqlalchemy import inspect as sqla_inspect
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# ── Base ──────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Declarative base. Add `naming_convention` here if you later move to Alembic."""


# ── Tables ────────────────────────────────────────────────────────────────────


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    color: Mapped[str | None] = mapped_column(Text)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_fallback: Mapped[bool] = mapped_column(default=False, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    example_ticket_ids: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    status: Mapped[str] = mapped_column(Text, default="pending", nullable=False)
    resolved_category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)

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

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
    )
    proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("category_proposals.id", ondelete="CASCADE"),
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    ticket_updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    cached_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

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

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    set_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (Index("ix_overrides_category", "category_id"),)


class Settings(Base):
    """Singleton — enforced by `CHECK (id = 1)`. The app inserts the row on first boot."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    lookback_unit: Mapped[str] = mapped_column(Text, default="hours", nullable=False)
    lookback_value: Mapped[int] = mapped_column(Integer, default=24, nullable=False)
    states: Mapped[list[str]] = mapped_column(
        JSON,
        default=lambda: ["open"],
        nullable=False,
    )
    include_category_ids: Mapped[list[int] | None] = mapped_column(JSON)  # null = all
    mute_alarms: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("0"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="settings_singleton_check"),
        CheckConstraint("lookback_unit IN ('hours', 'days')", name="settings_unit_check"),
        CheckConstraint("lookback_value BETWEEN 1 AND 720", name="settings_value_check"),
    )


class RejectedProposalSignature(Base):
    """Prevents the AI from re-proposing the same category after the user rejects it."""

    __tablename__ = "rejected_proposal_signatures"

    signature: Mapped[str] = mapped_column(Text, primary_key=True)
    rejected_name: Mapped[str] = mapped_column(Text, nullable=False)
    rejected_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class Followup(Base):
    """A per-ticket reminder (US-012). At most one row per ticket — `ticket_id`
    is the PK, so `PUT` upserts. No FK: the ticket id is owned by Intercom."""

    __tablename__ = "followups"

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    due_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    fired: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint(
            "reason IS NULL OR length(reason) <= 80",
            name="followups_reason_len_check",
        ),
        Index("ix_followups_due_at", "due_at"),
    )


class TicketNote(Base):
    """A per-ticket free-text note (US-014). One row per ticket; an empty body
    deletes the row, so every stored row is non-empty by invariant."""

    __tablename__ = "ticket_notes"

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )


class Ticket(Base):
    """An ingested + categorized conversation — the operator's board data.

    The Chrome extension fetches conversations from Intercom via the operator's
    logged-in session and pushes them to `POST /tickets/ingest`; the backend
    categorizes them and stores the result here, so `GET /tickets` serves the
    board without a live Intercom call. `author` + `parts` are JSON blobs of
    the hydrated conversation (parts carry ISO `created_at` strings).
    """

    __tablename__ = "tickets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    parts: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"),
    )
    proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("category_proposals.id", ondelete="SET NULL"),
    )
    summary: Mapped[str] = mapped_column(Text, default="", nullable=False)
    ai_confidence: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_tickets_updated_at", "updated_at"),
        Index("ix_tickets_category", "category_id"),
    )


# ── Seed data ─────────────────────────────────────────────────────────────────
#
# Swatches use oklch to match the design palette (plan.md §8b).
# Browsers Chrome 111+, Firefox 113+, Safari 15.4+ render oklch in CSS;
# values are stored as opaque strings and surfaced as-is in the client.

DEFAULT_CATEGORIES: list[dict[str, Any]] = [
    {
        "name": "Urgent",
        "description": "Outage, data loss, security incident, blocking issue, or angry customer threatening churn.",
        "color": "oklch(0.62 0.20 25)",
        "sort_order": 0,
        "is_fallback": False,
    },
    {
        "name": "Bug",
        "description": "Something is broken or behaving unexpectedly (and is not urgent).",
        "color": "oklch(0.56 0.18 285)",
        "sort_order": 1,
        "is_fallback": False,
    },
    {
        "name": "Feature Request",
        "description": "Customer is asking for capability that doesn't exist.",
        "color": "oklch(0.66 0.13 205)",
        "sort_order": 2,
        "is_fallback": False,
    },
    {
        "name": "Question",
        "description": "How-to, clarification, or a docs gap.",
        "color": "oklch(0.72 0.13 92)",
        "sort_order": 3,
        "is_fallback": False,
    },
    {
        "name": "Billing",
        "description": "Invoices, charges, plan changes, refunds, payment failures.",
        "color": "oklch(0.62 0.13 148)",
        "sort_order": 4,
        "is_fallback": False,
    },
    {
        "name": "Complaint",
        "description": "Dissatisfaction without a specific bug (UX, support quality, pricing).",
        "color": "oklch(0.66 0.16 50)",
        "sort_order": 5,
        "is_fallback": False,
    },
    {
        "name": "Other",
        "description": "Anything that genuinely doesn't fit the categories above.",
        "color": "oklch(0.65 0.00 0)",
        "sort_order": 6,
        "is_fallback": True,
    },
]


# ── Init + seed ───────────────────────────────────────────────────────────────


def _ensure_mute_alarms_column(conn: Any) -> None:
    """One-time additive migration: add `settings.mute_alarms` if missing.

    Runs inside the DDL transaction in `init_db`. No-op once the column exists.
    """
    inspector = sqla_inspect(conn)
    columns = {col["name"] for col in inspector.get_columns("settings")}
    if "mute_alarms" in columns:
        return
    conn.exec_driver_sql("ALTER TABLE settings ADD COLUMN mute_alarms BOOLEAN DEFAULT 0 NOT NULL")


async def init_db(engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Create schema if missing; seed defaults + singleton settings row if empty.

    Call from the FastAPI lifespan hook. Idempotent — re-runs leave existing data alone.
    """
    async with engine.begin() as conn:
        # SQLite needs FKs explicitly enabled per connection — but `engine.begin()`
        # opens one fresh connection here only for DDL. App-level FK enforcement is
        # set up via the `connect` event listener below.
        if engine.dialect.name == "sqlite":
            await conn.exec_driver_sql("PRAGMA foreign_keys = ON")
        await conn.run_sync(Base.metadata.create_all)
        # create_all adds the new `followups`/`ticket_notes` tables but never new
        # columns on an existing table — backfill `settings.mute_alarms` for DBs
        # created before Phase 10 (T045). Graduates to Alembic at T104.
        await conn.run_sync(_ensure_mute_alarms_column)

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


# ── SQLite FK enforcement (per-connection) ────────────────────────────────────
#
# SQLite ships with foreign keys OFF. SQLAlchemy doesn't carry the PRAGMA across
# connections — we need to set it on every new connection from the pool.

from sqlalchemy import event  # noqa: E402  (kept local to its usage)
from sqlalchemy.engine import Engine  # noqa: E402


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    # Only fire for SQLite — Postgres connections have no such concept.
    try:
        is_sqlite = "sqlite" in type(dbapi_connection).__module__.lower()
    except Exception:
        is_sqlite = False
    if not is_sqlite:
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


# ── Inline smoke test ─────────────────────────────────────────────────────────
#
# Run `python -m app.models` to spin up an in-memory DB and verify schema + seeds.

if __name__ == "__main__":  # pragma: no cover
    import asyncio

    from app.db import make_engine, make_session_factory

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

            settings_row = await session.scalar(select(Settings))
            assert settings_row is not None
            print(
                f"\nSettings: lookback={settings_row.lookback_value} {settings_row.lookback_unit}, "
                f"states={settings_row.states}",
            )

        await engine.dispose()

    asyncio.run(main())

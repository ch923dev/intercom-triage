"""SQLAlchemy 2.0 async models for the local triage tool.

Schema is managed via Alembic (see `backend/alembic/`). On first startup
`init_db` runs `alembic upgrade head`, which creates all tables and applies
any pending migrations. Seeding (categories + singleton settings row) happens
after migrations complete.

Works against SQLite by default (`sqlite+aiosqlite:///./data/triage.db`) and
against Postgres by swapping `DATABASE_URL` (`postgresql+asyncpg://...`). No
dialect-specific types are used — JSON columns use SQLAlchemy's portable JSON
type which maps to JSONB on Postgres and TEXT-with-JSON-fns on SQLite.

Reference: plan.md §5 (data model), tasks.md T006.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
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

from alembic.config import Config as AlembicConfig
from alembic.runtime.environment import EnvironmentContext
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory

# ── Base ──────────────────────────────────────────────────────────────────────


class Base(DeclarativeBase):
    """Declarative base for all ORM models. Alembic reads `Base.metadata` for autogenerate."""


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
    ai_resolution_verdict: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_resolution_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_resolution_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Roadmap 0.2 — triage facets cached alongside the categorization result so a
    # cache hit re-populates the ticket row without a fresh AI call. Nullable for
    # legacy rows; `ai_labels` is a JSON string array (defaults to []).
    ai_priority: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_sentiment: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_labels: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
        nullable=False,
    )
    # Roadmap 4.2 (T107) — structured kind for non-actionable cache entries.
    non_actionable_kind: Mapped[str | None] = mapped_column(Text, nullable=True)

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
        CheckConstraint(
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict "
            "IN ('resolved','not_resolved','non_actionable')",
            name="ai_cache_resolution_verdict_check",
        ),
        CheckConstraint(
            "ai_resolution_reason IS NULL OR length(ai_resolution_reason) <= 120",
            name="ai_cache_resolution_reason_len_check",
        ),
        # Roadmap 0.2 — triage enums (nullable; pre-0.2 cache rows carry NULL).
        CheckConstraint(
            "ai_priority IS NULL OR ai_priority IN ('low','normal','high','urgent')",
            name="ai_cache_ai_priority_check",
        ),
        CheckConstraint(
            "ai_sentiment IS NULL OR ai_sentiment IN ('negative','neutral','positive')",
            name="ai_cache_ai_sentiment_check",
        ),
        # Roadmap 4.2 (T107) — non-actionable kind enum.
        CheckConstraint(
            "non_actionable_kind IS NULL OR non_actionable_kind "
            "IN ('auto_reply','thanks','spam','out_of_office','other')",
            name="ai_cache_non_actionable_kind_check",
        ),
    )


class Override(Base):
    __tablename__ = "overrides"

    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    acted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    # When False, ingest skips AI categorization entirely — every ticket lands
    # in the fallback category and the operator fills in subject/summary by hand.
    use_ai: Mapped[bool] = mapped_column(
        default=True,
        server_default=text("1"),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    ai_resolve_default: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("0"),
        nullable=False,
    )
    ai_resolve_confidence_threshold: Mapped[float] = mapped_column(
        Float,
        default=0.7,
        server_default=text("0.7"),
        nullable=False,
    )
    # When True (default), the Board hides category columns that currently have
    # zero open tickets. Resolved column always shows regardless.
    hide_empty_categories: Mapped[bool] = mapped_column(
        default=True,
        server_default=text("1"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="settings_singleton_check"),
        CheckConstraint("lookback_unit IN ('hours', 'days')", name="settings_unit_check"),
        CheckConstraint("lookback_value BETWEEN 1 AND 720", name="settings_value_check"),
        CheckConstraint(
            "ai_resolve_confidence_threshold BETWEEN 0.0 AND 1.0",
            name="settings_ai_resolve_threshold_check",
        ),
    )


class User(Base):
    """Mirror of an OnlySales identity. NOT a credential store — no password."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    onlysales_id: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=True, server_default=text("1"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_users_onlysales_id", "onlysales_id", unique=True),
        Index("ix_users_email", "email", unique=True),
    )


class Session(Base):
    """Refresh-token store + revocation ledger. PK is an opaque session id."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    prev_refresh_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    onlysales_refresh_encrypted: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_sessions_refresh_hash", "refresh_token_hash"),
        Index("ix_sessions_prev_refresh_hash", "prev_refresh_token_hash"),
        Index("ix_sessions_user_id", "user_id"),
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


class NoteEntry(Base):
    """A timestamped append-only entry on a ticket's investigation log.

    Replaces the freeform `ticket_notes.body` scratchpad with a log of
    `(timestamp, body)` items. Each entry may carry an optional timer
    (`timer_min`) and an optional `reason` that mirrors the wording on the
    follow-up row. Soft-linked to `followups` by `ticket_id`: when a new
    entry has `timer_min` set, the service upserts the matching `followups`
    row inside the same transaction.

    Append-only — corrections are new entries. `deleted_at` is a soft-delete
    for hard mistakes only.
    """

    __tablename__ = "note_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    timer_min: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("length(body) > 0", name="note_entries_body_nonempty"),
        CheckConstraint(
            "reason IS NULL OR length(reason) <= 80",
            name="note_entries_reason_len_check",
        ),
        CheckConstraint(
            "timer_min IS NULL OR (timer_min BETWEEN 1 AND 1440)",
            name="note_entries_timer_range_check",
        ),
        Index("ix_note_entries_ticket", "ticket_id"),
        Index("ix_note_entries_created", "created_at"),
    )


class NoteAttachment(Base):
    """A file attachment owned by either a note entry or a ticket (spec:
    note attachments). Content-addressed by sha256 on disk so identical
    uploads dedupe automatically. Polymorphic owner — `owner_kind` is
    'entry' (owner_id = str of NoteEntry.id) or 'ticket' (owner_id =
    ticket_id). `ticket_id` is always populated so list-by-ticket is one
    index lookup regardless of owner kind."""

    __tablename__ = "note_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_kind: Mapped[str] = mapped_column(Text, nullable=False)
    owner_id: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_id: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(Text, nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint(
            "owner_kind IN ('entry','ticket')",
            name="note_attachments_owner_kind_check",
        ),
        CheckConstraint("length(sha256) = 64", name="note_attachments_sha256_len_check"),
        CheckConstraint("size_bytes >= 0", name="note_attachments_size_nonneg_check"),
        Index("ix_note_attachments_owner", "owner_kind", "owner_id"),
        Index("ix_note_attachments_ticket", "ticket_id"),
        Index("ix_note_attachments_sha256", "sha256"),
    )


class Playbook(Base):
    """A reusable next-steps recipe for an issue, scoped to a category.

    Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md. Durable,
    operator-owned knowledge — NOT a cache. It is never keyed by content
    signature and survives ingest / re-sync untouched. The flyout lists
    active playbooks for a ticket's effective category; the library page
    manages them. `source_ticket_id` is the exemplar the operator solved it
    on (informational; `SET NULL` if that ticket row is ever removed).
    """

    __tablename__ = "playbooks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(
        ForeignKey("categories.id", ondelete="CASCADE"),
        nullable=False,
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    source_ticket_id: Mapped[str | None] = mapped_column(
        ForeignKey("tickets.id", ondelete="SET NULL"),
        nullable=True,
    )
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("length(label) > 0", name="playbooks_label_nonempty"),
        CheckConstraint("length(body) > 0", name="playbooks_body_nonempty"),
        Index(
            "ix_playbooks_category_active",
            "category_id",
            sqlite_where=text("archived_at IS NULL"),
            postgresql_where=text("archived_at IS NULL"),
        ),
    )


class Snippet(Base):
    """A short, reusable canned reply with `{{variable}}` placeholders.

    Lighter than a `Playbook`: a snippet is a high-frequency short response
    (e.g. a greeting or a stock answer) the operator drops into a reply, not a
    durable investigation recipe. Global — not category-scoped. Durable,
    operator-owned knowledge (invariant #13): never keyed by content signature,
    survives ingest / re-sync untouched. Variable substitution is performed
    client-side from the ticket the operator is viewing; the body is stored
    verbatim with placeholders intact.
    """

    __tablename__ = "snippets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("length(title) > 0", name="snippets_title_nonempty"),
        CheckConstraint("length(body) > 0", name="snippets_body_nonempty"),
        Index(
            "ix_snippets_active",
            "created_at",
            sqlite_where=text("archived_at IS NULL"),
            postgresql_where=text("archived_at IS NULL"),
        ),
    )


class TicketCluster(Base):
    """One recurring-issue cluster, produced by the offline clustering job.

    Roadmap 3.1. The job (see `app/ai/clustering.py` + the background loop in
    `main.py`) periodically clusters RESOLVED tickets' EXISTING embeddings
    (`ticket_embeddings`, built from `parts[]` + operator note only — invariant
    #4) with HDBSCAN, then labels each cluster with c-TF-IDF top terms drawn
    from `parts[]` + title ONLY (never `internal_notes`, #4). HDBSCAN noise
    points (label -1) are NOT force-fit into a cluster — they are simply
    excluded, so every row here is a genuine cluster.

    Snapshot semantics: each run is atomic — the job deletes the prior rows and
    inserts the fresh ones in one transaction. Reading `ticket_embeddings`
    never touches `ai_cache` / the content signature (#6). Member ticket ids
    live in the `ticket_cluster_members` join (cascade-deleted with the cluster).
    """

    __tablename__ = "ticket_clusters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Human-readable c-TF-IDF label, e.g. "login error password reset". Built
    # from customer-visible text only (#4).
    label: Mapped[str] = mapped_column(Text, nullable=False)
    # Ordered top terms behind the label (JSON string array) for the UI / 3.2.
    top_terms: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )

    __table_args__ = (
        CheckConstraint("size >= 0", name="ticket_clusters_size_nonneg"),
        Index("ix_ticket_clusters_size", "size"),
    )


class TicketClusterMember(Base):
    """A resolved ticket's membership in a `TicketCluster` (roadmap 3.1).

    No FK to `tickets` (ticket ids are owned by Intercom and rows can churn on
    re-sync, mirroring `followups`); cascade-deleted with the parent cluster so
    a fresh clustering run wipes the old membership cleanly.
    """

    __tablename__ = "ticket_cluster_members"

    cluster_id: Mapped[int] = mapped_column(
        ForeignKey("ticket_clusters.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ticket_id: Mapped[str] = mapped_column(Text, primary_key=True)

    __table_args__ = (Index("ix_ticket_cluster_members_ticket", "ticket_id"),)


class Ticket(Base):
    """An ingested + categorized conversation — the operator's board data.

    The backend polls Intercom server-side and pushes conversations through
    `ingest_tickets`; the result is stored here so `GET /tickets` serves the
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
    internal_notes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
        nullable=False,
    )
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
    # Roadmap 0.2 — triage facets from the SAME categorization call (no extra AI
    # call). Nullable for pre-0.2 rows; ingest writes 'normal'/'neutral'/[] on a
    # fallback. `ai_labels` stores secondary multi-label tags as a JSON string
    # array (simplest durable option — no join table for a single-operator tool).
    ai_priority: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_sentiment: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_labels: Mapped[list[str]] = mapped_column(
        JSON,
        default=list,
        server_default=text("'[]'"),
        nullable=False,
    )
    # When True, the operator manually edited the field via PATCH /tickets/{id}.
    # The ingest pipeline preserves edited values across re-syncs.
    title_user_edited: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("0"),
        nullable=False,
    )
    summary_user_edited: Mapped[bool] = mapped_column(
        default=False,
        server_default=text("0"),
        nullable=False,
    )
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=text("CURRENT_TIMESTAMP"),
        nullable=False,
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolved_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_resolve_enabled: Mapped[bool | None] = mapped_column(nullable=True)
    resolution_chip_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Roadmap 4.1 (T106) — operator "parked / snoozed" state: a deferred-action
    # ticket. Orthogonal to resolution; the trio is all-set-or-all-null and a
    # ticket is never both parked and resolved. "ready" (parked_until <= now) is
    # derived on read, not stored.
    parked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    parked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional free-text elaboration (mainly for reason='other'); only set while
    # parked, cleared with the trio by clear_parked.
    parked_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Roadmap 4.2 (T107) — structured kind for non-actionable tickets. Only set
    # when resolved_source = 'non_actionable'; nullable; AI-derived.
    non_actionable_kind: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Phase 2 (T169) — attribution. Board-state only; AI/system resolve → NULL.
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Phase 3 (T170) — assignment. assigned_to NULL = unassigned.
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_tickets_updated_at", "updated_at"),
        Index("ix_tickets_category", "category_id"),
        Index(
            "ix_tickets_resolved_at",
            "resolved_at",
            sqlite_where=text("resolved_at IS NOT NULL"),
            postgresql_where=text("resolved_at IS NOT NULL"),
        ),
        CheckConstraint(
            "(resolved_at IS NULL) = (resolved_source IS NULL)",
            name="tickets_resolved_xor_check",
        ),
        CheckConstraint(
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable','ai_resolved')",
            name="tickets_resolved_source_check",
        ),
        # Roadmap 0.2 — triage enums (nullable; pre-0.2 rows carry NULL).
        CheckConstraint(
            "ai_priority IS NULL OR ai_priority IN ('low','normal','high','urgent')",
            name="tickets_ai_priority_check",
        ),
        CheckConstraint(
            "ai_sentiment IS NULL OR ai_sentiment IN ('negative','neutral','positive')",
            name="tickets_ai_sentiment_check",
        ),
        CheckConstraint(
            "(parked_at IS NULL) = (parked_until IS NULL) "
            "AND (parked_at IS NULL) = (parked_reason IS NULL)",
            name="tickets_parked_trio_check",
        ),
        CheckConstraint(
            "parked_reason IS NULL OR parked_reason "
            "IN ('waiting_on_customer','waiting_on_third_party','waiting_internal','other')",
            name="tickets_parked_reason_check",
        ),
        CheckConstraint(
            "NOT (parked_at IS NOT NULL AND resolved_at IS NOT NULL)",
            name="tickets_not_parked_and_resolved_check",
        ),
        CheckConstraint(
            "parked_note IS NULL OR (parked_at IS NOT NULL AND length(parked_note) <= 200)",
            name="tickets_parked_note_check",
        ),
        # Roadmap 4.2 (T107) — non-actionable kind enum; only valid while non-actionable.
        CheckConstraint(
            "non_actionable_kind IS NULL OR (resolved_source = 'non_actionable' "
            "AND non_actionable_kind "
            "IN ('auto_reply','thanks','spam','out_of_office','other'))",
            name="tickets_non_actionable_kind_check",
        ),
        CheckConstraint(
            "(assigned_to IS NULL) = (assigned_at IS NULL)",
            name="tickets_assigned_pair_check",
        ),
        Index("ix_tickets_assigned_to", "assigned_to"),
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

# Path to alembic.ini, resolved relative to this file so it works regardless
# of cwd (tests, uvicorn, direct invocation).
_ALEMBIC_INI = Path(__file__).parent.parent / "alembic.ini"


def _make_alembic_cfg() -> AlembicConfig:
    """Build an AlembicConfig pointing at our alembic.ini."""
    return AlembicConfig(str(_ALEMBIC_INI))


def _run_migrations_sync(connection: Any) -> None:
    """Run all pending Alembic migrations using an existing (sync) connection.

    This is called via `await conn.run_sync(...)` so `connection` is a
    synchronous SQLAlchemy `Connection` (not the raw DBAPI cursor).  By
    reusing the same connection we avoid the in-memory-SQLite-per-connection
    problem: every *new* connection to `sqlite+aiosqlite:///:memory:` is a
    distinct empty database, so Alembic must migrate the same connection that
    the session factory talks to.

    We drive Alembic via `EnvironmentContext` + `MigrationContext` directly,
    bypassing `env.py` entirely, which is the correct approach for programmatic
    use with an existing connection.

    Cases handled:
      - app tables exist AND `alembic_version` has a row  → `upgrade head`
        (idempotent — Alembic skips applied revisions).
      - app tables exist AND `alembic_version` is missing OR empty
        (pre-Alembic DB, or the relic of a previous failed boot which created
        the version table non-transactionally and never wrote a row)  →
        `stamp head`. Schema is already at the head shape; we just need to
        record the revision so future migrations apply cleanly.
      - Empty DB  → `upgrade head` from scratch.
    """
    cfg = _make_alembic_cfg()
    script = ScriptDirectory.from_config(cfg)
    inspector = sqla_inspect(connection)
    existing_tables = set(inspector.get_table_names())
    has_version_table = "alembic_version" in existing_tables
    # `categories` is a stable proxy for "the app's tables are here" — it's
    # been part of the schema since the first release.
    has_app_tables = "categories" in existing_tables
    # An empty `alembic_version` table is the fingerprint of a previous failed
    # migration attempt: SQLite's non-transactional DDL committed the table
    # but the version row was never written. From Alembic's view that's "at
    # base"; from ours, the schema is already at head. Treat the same as a
    # missing version table.
    version_row_present = False
    if has_version_table:
        row = connection.exec_driver_sql("SELECT version_num FROM alembic_version").first()
        version_row_present = row is not None

    if has_app_tables and not version_row_present:
        context = MigrationContext.configure(
            connection=connection,
            opts={"target_metadata": Base.metadata},
        )
        context.stamp(script, "head")
        return

    def do_upgrade(rev: Any, context: Any) -> Any:
        return script._upgrade_revs("head", rev)

    with EnvironmentContext(cfg, script, fn=do_upgrade, destination_rev="head") as env_ctx:
        env_ctx.configure(
            connection=connection,
            target_metadata=Base.metadata,
            render_as_batch=True,
        )
        with env_ctx.begin_transaction():
            env_ctx.run_migrations()


async def init_db(engine: AsyncEngine, session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Apply all Alembic migrations then seed defaults + singleton settings row.

    Call from the FastAPI lifespan hook. Idempotent — re-runs leave existing
    data alone (Alembic tracks applied revisions in `alembic_version`; seeding
    checks before inserting).

    Why we drive migrations via the existing engine connection rather than via
    `alembic.command.upgrade`:

    `alembic.command.upgrade` invokes env.py which calls `asyncio.run()` on a
    fresh engine with `NullPool`.  For file-based databases that works fine.
    For `sqlite+aiosqlite:///:memory:` each new connection is a *different*
    in-memory database — Alembic's tables would live in a throwaway DB, not the
    one the app uses.  By passing `run_sync` our existing connection we ensure
    migrations happen in the same database the session factory talks to.
    """
    async with engine.begin() as conn:
        await conn.run_sync(_run_migrations_sync)

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


def _is_sqlite_connection(dbapi_connection: Any) -> bool:
    try:
        return "sqlite" in type(dbapi_connection).__module__.lower()
    except Exception:
        return False


@event.listens_for(Engine, "connect")
def _set_sqlite_pragmas(dbapi_connection: Any, connection_record: Any) -> None:
    # Only fire for SQLite — Postgres connections have no such concept.
    if not _is_sqlite_connection(dbapi_connection):
        return
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys = ON")
    finally:
        cursor.close()


# ── sqlite-vec extension load (per-connection) ────────────────────────────────
#
# The `vec0` virtual table (embeddings store, migration 0014) is provided by the
# sqlite-vec loadable extension. Like the FK PRAGMA above, it does not carry
# across connections — every new SQLite connection must load it before the
# vec table is usable. SQLAlchemy's aiosqlite dialect surfaces the raw
# `sqlite3.Connection` here, which exposes `enable_load_extension`. Postgres is
# unaffected (the guard skips non-SQLite). Best-effort: if sqlite-vec is not
# installed (embeddings disabled / heavy dep skipped) the load is silently
# skipped so the rest of the app boots — only the embeddings layer is degraded.


# Set True once the vec0 extension actually loads on a SQLite connection, so
# `/health` can report whether the embedding layer is operational rather than
# silently degraded (the load is best-effort and otherwise leaves no signal).
_sqlite_vec_loaded: bool = False


def sqlite_vec_loaded() -> bool:
    """Whether the sqlite-vec (vec0) extension successfully loaded on a SQLite
    connection. Postgres deployments leave this False — there it is irrelevant."""
    return _sqlite_vec_loaded


@event.listens_for(Engine, "connect")
def _load_sqlite_vec(dbapi_connection: Any, connection_record: Any) -> None:
    if not _is_sqlite_connection(dbapi_connection):
        return
    try:
        import sqlite_vec
    except ImportError:
        # Embeddings disabled / heavy dep skipped — the vec0 table is unusable,
        # but the rest of the app boots normally. Only the embedding layer is
        # degraded (the ingest hook is best-effort, see services/tickets.py).
        return

    def _load(raw: Any) -> None:
        raw.enable_load_extension(True)
        try:
            sqlite_vec.load(raw)
            global _sqlite_vec_loaded
            _sqlite_vec_loaded = True
        finally:
            raw.enable_load_extension(False)

    # aiosqlite (our async default) runs the real sqlite3 connection on a worker
    # thread: its `enable_load_extension` / `load_extension` are coroutines, so
    # they cannot be called synchronously here. Bridge onto that thread via the
    # adapter's `await_` + aiosqlite's `_execute`, touching the underlying
    # sqlite3.Connection (`_connection`). A plain sync sqlite3 connection (e.g.
    # a future sync engine) exposes `enable_load_extension` directly.
    driver = getattr(dbapi_connection, "driver_connection", dbapi_connection)
    raw_sqlite3 = getattr(driver, "_connection", None)
    await_ = getattr(dbapi_connection, "await_", None)
    if raw_sqlite3 is not None and await_ is not None and hasattr(driver, "_execute"):
        await_(driver._execute(_load, raw_sqlite3))
    elif hasattr(dbapi_connection, "enable_load_extension"):
        _load(dbapi_connection)


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

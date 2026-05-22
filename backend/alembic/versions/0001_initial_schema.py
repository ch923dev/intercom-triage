"""Initial schema — all tables at their pre-extension baseline.

Excluded columns that were added in subsequent migrations:
  - settings.mute_alarms      (→ 0002)
  - tickets.internal_notes    (→ 0003)
  - tickets.title_user_edited (→ 0004)
  - tickets.summary_user_edited (→ 0004)
  - settings.use_ai           (→ 0005)

Revision ID: 0001
Revises: (none — first migration)
Create Date: 2026-05-23 00:00:00.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # ── categories ────────────────────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("color", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "source IN ('seed', 'ai_proposed', 'user_created')",
            name="categories_source_check",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ux_categories_name_active",
        "categories",
        ["name"],
        unique=True,
        sqlite_where=sa.text("is_active"),
        postgresql_where=sa.text("is_active"),
    )
    op.create_index(
        "ux_categories_fallback",
        "categories",
        ["is_fallback"],
        unique=True,
        sqlite_where=sa.text("is_fallback"),
        postgresql_where=sa.text("is_fallback"),
    )

    # ── category_proposals ────────────────────────────────────────────────────
    op.create_table(
        "category_proposals",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("example_ticket_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column(
            "resolved_category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'merged', 'rejected')",
            name="proposals_status_check",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_proposals_status", "category_proposals", ["status"])
    op.create_index(
        "ux_proposals_name_pending",
        "category_proposals",
        ["name"],
        unique=True,
        sqlite_where=sa.text("status = 'pending'"),
        postgresql_where=sa.text("status = 'pending'"),
    )

    # ── ai_cache ──────────────────────────────────────────────────────────────
    op.create_table(
        "ai_cache",
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("category_proposals.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("ticket_updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "cached_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "(category_id IS NULL) <> (proposal_id IS NULL)",
            name="ai_cache_xor_check",
        ),
        sa.PrimaryKeyConstraint("ticket_id"),
    )
    op.create_index(
        "ix_ai_cache_proposal",
        "ai_cache",
        ["proposal_id"],
        sqlite_where=sa.text("proposal_id IS NOT NULL"),
        postgresql_where=sa.text("proposal_id IS NOT NULL"),
    )
    op.create_index(
        "ix_ai_cache_category",
        "ai_cache",
        ["category_id"],
        sqlite_where=sa.text("category_id IS NOT NULL"),
        postgresql_where=sa.text("category_id IS NOT NULL"),
    )

    # ── overrides ─────────────────────────────────────────────────────────────
    op.create_table(
        "overrides",
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "set_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("ticket_id"),
    )
    op.create_index("ix_overrides_category", "overrides", ["category_id"])

    # ── settings (baseline — without mute_alarms and use_ai) ─────────────────
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("lookback_unit", sa.Text(), nullable=False, server_default="hours"),
        sa.Column("lookback_value", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("states", sa.JSON(), nullable=False),
        sa.Column("include_category_ids", sa.JSON(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint("id = 1", name="settings_singleton_check"),
        sa.CheckConstraint(
            "lookback_unit IN ('hours', 'days')", name="settings_unit_check"
        ),
        sa.CheckConstraint(
            "lookback_value BETWEEN 1 AND 720", name="settings_value_check"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # ── rejected_proposal_signatures ──────────────────────────────────────────
    op.create_table(
        "rejected_proposal_signatures",
        sa.Column("signature", sa.Text(), nullable=False),
        sa.Column("rejected_name", sa.Text(), nullable=False),
        sa.Column(
            "rejected_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("signature"),
    )

    # ── followups ─────────────────────────────────────────────────────────────
    op.create_table(
        "followups",
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("due_at", sa.DateTime(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("fired", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "reason IS NULL OR length(reason) <= 80",
            name="followups_reason_len_check",
        ),
        sa.PrimaryKeyConstraint("ticket_id"),
    )
    op.create_index("ix_followups_due_at", "followups", ["due_at"])

    # ── ticket_notes ──────────────────────────────────────────────────────────
    op.create_table(
        "ticket_notes",
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("ticket_id"),
    )

    # ── tickets (baseline — without internal_notes, *_user_edited) ────────────
    op.create_table(
        "tickets",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("state", sa.Text(), nullable=True),
        sa.Column("priority", sa.Text(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("author", sa.JSON(), nullable=False),
        sa.Column("parts", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "proposal_id",
            sa.Integer(),
            sa.ForeignKey("category_proposals.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("ai_confidence", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column(
            "ingested_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tickets_updated_at", "tickets", ["updated_at"])
    op.create_index("ix_tickets_category", "tickets", ["category_id"])


def downgrade() -> None:
    # Drop in reverse dependency order.
    op.drop_table("tickets")
    op.drop_table("ticket_notes")
    op.drop_table("followups")
    op.drop_table("rejected_proposal_signatures")
    op.drop_table("settings")
    op.drop_table("overrides")
    op.drop_table("ai_cache")
    op.drop_table("category_proposals")
    op.drop_table("categories")

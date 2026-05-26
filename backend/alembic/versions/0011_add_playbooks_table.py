"""Add playbooks table.

Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md

Reusable next-steps recipes scoped to a category. Durable operator-owned
knowledge — NOT a cache. `category_id` FK cascades on category delete;
`source_ticket_id` FK sets null when the exemplar ticket row is removed.
A partial index on active rows backs the per-category flyout lookup.

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-26 00:00:11.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "playbooks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "category_id",
            sa.Integer(),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column(
            "source_ticket_id",
            sa.Text(),
            sa.ForeignKey("tickets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("length(label) > 0", name="playbooks_label_nonempty"),
        sa.CheckConstraint("length(body) > 0", name="playbooks_body_nonempty"),
    )
    op.create_index(
        "ix_playbooks_category_active",
        "playbooks",
        ["category_id"],
        sqlite_where=sa.text("archived_at IS NULL"),
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_playbooks_category_active", table_name="playbooks")
    op.drop_table("playbooks")

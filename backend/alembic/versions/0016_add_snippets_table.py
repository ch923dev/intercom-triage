"""Add snippets table.

Roadmap 1.5 — snippet / canned-response manager.

Short, reusable canned replies with `{{variable}}` placeholders. Lighter than
playbooks: global (not category-scoped), no AI draft. Durable operator-owned
knowledge (invariant #13) — never keyed by content signature, survives ingest /
re-sync untouched. A partial index on active rows backs the library listing.

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-27 00:00:16.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "snippets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
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
        sa.CheckConstraint("length(title) > 0", name="snippets_title_nonempty"),
        sa.CheckConstraint("length(body) > 0", name="snippets_body_nonempty"),
    )
    op.create_index(
        "ix_snippets_active",
        "snippets",
        ["created_at"],
        sqlite_where=sa.text("archived_at IS NULL"),
        postgresql_where=sa.text("archived_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_snippets_active", table_name="snippets")
    op.drop_table("snippets")

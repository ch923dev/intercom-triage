"""Add tickets.title_user_edited and tickets.summary_user_edited columns.

Operator-editable title/summary: when an operator manually edits a ticket's
title or summary via PATCH /tickets/{id}, the ingest pipeline must preserve
those values across re-syncs. These boolean flags track which fields the
operator has touched.

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-23 00:00:03.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "title_user_edited",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )
        batch_op.add_column(
            sa.Column(
                "summary_user_edited",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("summary_user_edited")
        batch_op.drop_column("title_user_edited")

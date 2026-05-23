"""Add settings.hide_empty_categories column.

When True (default), the Board hides category columns that currently have
zero open tickets. Resolved column always shows regardless.

Revision ID: 0007
Revises: 0006
Create Date: 2026-05-23 00:00:06.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "hide_empty_categories",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("hide_empty_categories")

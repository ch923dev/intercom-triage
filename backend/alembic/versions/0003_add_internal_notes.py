"""Add tickets.internal_notes column.

Intercom team-notes feature: conversations now carry internal notes written
by teammates. The extension fetches them and pushes them alongside the
conversation parts. Existing rows default to an empty list.

Revision ID: 0003
Revises: 0002
Create Date: 2026-05-23 00:00:02.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(
            sa.Column(
                "internal_notes",
                sa.JSON(),
                nullable=False,
                server_default="'[]'",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("internal_notes")

"""Add settings.use_ai column.

AI toggle: when False, the ingest pipeline skips AI categorization entirely
and every ticket lands in the fallback category. The operator fills in
subject/summary by hand. Existing rows default to True (1 = AI on).

Revision ID: 0005
Revises: 0004
Create Date: 2026-05-23 00:00:04.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "use_ai",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("use_ai")

"""Add settings.mute_alarms column.

Phase 10 (T045) added a per-operator alarm-mute toggle. Existing databases
created before this release are missing the column; this migration adds it
with a safe default of False (0).

Revision ID: 0002
Revises: 0001
Create Date: 2026-05-23 00:00:01.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "mute_alarms",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("mute_alarms")

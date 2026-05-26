"""Add tickets.resolution_cleared_at column.

Stamped whenever the operator clears a resolution (reopen or drag-out).
Used by _maybe_auto_resolve_from_ai to guard against re-resolving a ticket
the operator deliberately reopened — auto-resolve is skipped while the
content_signature has not advanced past resolution_cleared_at.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-27 00:00:01.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("resolution_cleared_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("resolution_cleared_at")

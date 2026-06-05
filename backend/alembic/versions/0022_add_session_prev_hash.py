"""Add sessions.prev_refresh_token_hash — refresh reuse-detection (T168).

Stores the immediately-preceding refresh hash so a replayed (rotated-away)
token is detected and the session chain revoked. Additive.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-05 00:00:22.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("prev_refresh_token_hash", sa.Text(), nullable=True))
    op.create_index("ix_sessions_prev_refresh_hash", "sessions", ["prev_refresh_token_hash"])


def downgrade() -> None:
    op.drop_index("ix_sessions_prev_refresh_hash", table_name="sessions")
    op.drop_column("sessions", "prev_refresh_token_hash")

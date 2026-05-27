"""Add tickets.parked_note (roadmap 4.1, T106).

Optional free-text elaboration for a parked ticket — mainly when the structured
`parked_reason` is 'other'. Only set while parked (cleared with the trio);
bounded to 200 chars. Additive, nullable.

Revision ID: 0019
Revises: 0018
Create Date: 2026-05-27 00:00:19.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("parked_note", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "tickets_parked_note_check",
            "parked_note IS NULL OR (parked_at IS NOT NULL AND length(parked_note) <= 200)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_parked_note_check", type_="check")
        batch_op.drop_column("parked_note")

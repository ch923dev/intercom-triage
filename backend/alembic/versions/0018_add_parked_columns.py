"""Add tickets.parked_at / parked_until / parked_reason (roadmap 4.1, T106).

Operator "parked / snoozed" state. Orthogonal to resolution: trio is
all-or-none, reason is an enum, and a ticket is never both parked and resolved.

Revision ID: 0018
Revises: 0017
Create Date: 2026-05-27 00:00:18.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("parked_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("parked_until", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("parked_reason", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "tickets_parked_trio_check",
            "(parked_at IS NULL) = (parked_until IS NULL) "
            "AND (parked_at IS NULL) = (parked_reason IS NULL)",
        )
        batch_op.create_check_constraint(
            "tickets_parked_reason_check",
            "parked_reason IS NULL OR parked_reason "
            "IN ('waiting_on_customer','waiting_on_third_party','waiting_internal','other')",
        )
        batch_op.create_check_constraint(
            "tickets_not_parked_and_resolved_check",
            "NOT (parked_at IS NOT NULL AND resolved_at IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_not_parked_and_resolved_check", type_="check")
        batch_op.drop_constraint("tickets_parked_reason_check", type_="check")
        batch_op.drop_constraint("tickets_parked_trio_check", type_="check")
        batch_op.drop_column("parked_reason")
        batch_op.drop_column("parked_until")
        batch_op.drop_column("parked_at")

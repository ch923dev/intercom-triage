"""Add assignment XOR-pair CHECK: assigned_to ⇔ assigned_at (review #10b).

Both-null or both-set, mirroring the resolved (0023) and parked (0018) pairs so a
half-set assignment can never be persisted. Additive guard — no column change.

Revision ID: 0025
Revises: 0024
Create Date: 2026-06-08 00:00:25.000000 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.create_check_constraint(
            "tickets_assigned_pair_check",
            "(assigned_to IS NULL) = (assigned_at IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_assigned_pair_check", type_="check")

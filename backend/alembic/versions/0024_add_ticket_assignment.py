"""Add assignment columns: tickets.assigned_to + assigned_at (T170).

assigned_to FK users.id (SET NULL), assigned_at naive-UTC. Both nullable.
Additive. Reference: multi-hosted-user-design.md §5.2.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-05 00:00:24.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("assigned_to", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tickets_assigned_to_users",
            "users",
            ["assigned_to"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.add_column(sa.Column("assigned_at", sa.DateTime(), nullable=True))
        batch_op.create_index("ix_tickets_assigned_to", ["assigned_to"])


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_index("ix_tickets_assigned_to")
        batch_op.drop_constraint("fk_tickets_assigned_to_users", type_="foreignkey")
        batch_op.drop_column("assigned_at")
        batch_op.drop_column("assigned_to")

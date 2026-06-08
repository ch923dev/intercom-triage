"""Add attribution columns: tickets.resolved_by, overrides.acted_by (T169).

Both FK users.id, nullable, ON DELETE SET NULL — AI/system actions stay NULL.
Additive. Reference: docs/superpowers/specs/2026-06-05-multi-hosted-user-design.md §5.2.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-05 00:00:23.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("resolved_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_tickets_resolved_by_users",
            "users",
            ["resolved_by"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("overrides") as batch_op:
        batch_op.add_column(sa.Column("acted_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_overrides_acted_by_users",
            "users",
            ["acted_by"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("overrides") as batch_op:
        batch_op.drop_constraint("fk_overrides_acted_by_users", type_="foreignkey")
        batch_op.drop_column("acted_by")
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("fk_tickets_resolved_by_users", type_="foreignkey")
        batch_op.drop_column("resolved_by")

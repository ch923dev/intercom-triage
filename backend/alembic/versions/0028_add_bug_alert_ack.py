"""Add bug_alerts.acked_at + acked_by (T183).

Acknowledgement is a state of its own, not a synonym for dismissal: acked means
someone owns it, dismissed means it is finished. The pair is XOR-locked by CHECK
so "acknowledged by nobody" and "acknowledged at no time" are both unstorable,
mirroring resolved_at/resolved_source (invariant #10) and the parked trio (#14).

`acked_by` is FK users.id ON DELETE SET NULL — a deactivated operator's row must
not take the acknowledgement with it. Additive.
Reference: spec.md FR-084/FR-085, plan.md §22, tasks.md T183.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-15 00:00:28.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # One batch block: SQLite has to rebuild the table to gain a table-level
    # CHECK, and doing the columns in a separate block would rebuild it twice.
    with op.batch_alter_table("bug_alerts") as batch_op:
        batch_op.add_column(sa.Column("acked_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("acked_by", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_bug_alerts_acked_by_users",
            "users",
            ["acked_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "bug_alerts_ack_pair_check",
            "(acked_at IS NULL) = (acked_by IS NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("bug_alerts") as batch_op:
        batch_op.drop_constraint("bug_alerts_ack_pair_check", type_="check")
        batch_op.drop_constraint("fk_bug_alerts_acked_by_users", type_="foreignkey")
        batch_op.drop_column("acked_by")
        batch_op.drop_column("acked_at")

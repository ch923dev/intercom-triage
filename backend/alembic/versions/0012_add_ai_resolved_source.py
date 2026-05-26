"""Add 'ai_resolved' to tickets.resolved_source CHECK constraint.

AI auto-resolve used verdict='resolved' directly as resolved_source, but the
CheckConstraint only allowed ('manual','intercom_closed','non_actionable').
This adds the fourth legal value 'ai_resolved' so AI-resolved tickets
commit without IntegrityError.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-27 00:00:00.000000 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable','ai_resolved')",
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable')",
        )

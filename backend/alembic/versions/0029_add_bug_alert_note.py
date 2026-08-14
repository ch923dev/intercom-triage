"""Add bug_alerts.note + note_by + note_at (T187).

The incident record for a defect: root cause / workaround / what was done. A
trio, CHECK-locked all-set-or-all-null like the parked fields (invariant #14) —
a note with no author or no time is not a record of anything.

`note_by` is FK users.id ON DELETE SET NULL and holds the MOST RECENT author:
the board is team-wide, so any operator may correct a note, and one column can
only honestly say who last touched it. No history table by design (plan §23).

Additive. Reference: spec.md FR-089/FR-090, plan.md §23, tasks.md T187.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-15 00:00:29.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    # One batch block: SQLite rebuilds the table to gain a table-level CHECK, and
    # splitting the columns out would rebuild it twice.
    with op.batch_alter_table("bug_alerts") as batch_op:
        batch_op.add_column(sa.Column("note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("note_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("note_at", sa.DateTime(), nullable=True))
        batch_op.create_foreign_key(
            "fk_bug_alerts_note_by_users",
            "users",
            ["note_by"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_check_constraint(
            "bug_alerts_note_trio_check",
            "(note IS NULL AND note_by IS NULL AND note_at IS NULL) "
            "OR (note IS NOT NULL AND note_by IS NOT NULL AND note_at IS NOT NULL)",
        )
        batch_op.create_check_constraint(
            "bug_alerts_note_len_check",
            "note IS NULL OR length(note) <= 2000",
        )


def downgrade() -> None:
    with op.batch_alter_table("bug_alerts") as batch_op:
        batch_op.drop_constraint("bug_alerts_note_len_check", type_="check")
        batch_op.drop_constraint("bug_alerts_note_trio_check", type_="check")
        batch_op.drop_constraint("fk_bug_alerts_note_by_users", type_="foreignkey")
        batch_op.drop_column("note_at")
        batch_op.drop_column("note_by")
        batch_op.drop_column("note")

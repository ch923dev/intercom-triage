"""Add note_entries table (time-tabled notes spec).

Spec: docs/superpowers/specs/2026-05-23-time-tabled-notes-design.md

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-23 00:00:08.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "note_entries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("timer_min", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("length(body) > 0", name="note_entries_body_nonempty"),
        sa.CheckConstraint(
            "reason IS NULL OR length(reason) <= 80",
            name="note_entries_reason_len_check",
        ),
        sa.CheckConstraint(
            "timer_min IS NULL OR (timer_min BETWEEN 1 AND 1440)",
            name="note_entries_timer_range_check",
        ),
    )
    op.create_index("ix_note_entries_ticket", "note_entries", ["ticket_id"])
    op.create_index("ix_note_entries_created", "note_entries", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_note_entries_created", table_name="note_entries")
    op.drop_index("ix_note_entries_ticket", table_name="note_entries")
    op.drop_table("note_entries")

"""Add note_attachments table (note attachments spec).

Spec: docs/superpowers/specs/2026-05-23-note-attachments-design.md

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-23 00:00:09.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "note_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("owner_kind", sa.Text(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=False),
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("mime", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("stored_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "owner_kind IN ('entry','ticket')",
            name="note_attachments_owner_kind_check",
        ),
        sa.CheckConstraint(
            "length(sha256) = 64", name="note_attachments_sha256_len_check"
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name="note_attachments_size_nonneg_check"
        ),
    )
    op.create_index(
        "ix_note_attachments_owner", "note_attachments", ["owner_kind", "owner_id"]
    )
    op.create_index("ix_note_attachments_ticket", "note_attachments", ["ticket_id"])
    op.create_index("ix_note_attachments_sha256", "note_attachments", ["sha256"])


def downgrade() -> None:
    op.drop_index("ix_note_attachments_sha256", table_name="note_attachments")
    op.drop_index("ix_note_attachments_ticket", table_name="note_attachments")
    op.drop_index("ix_note_attachments_owner", table_name="note_attachments")
    op.drop_table("note_attachments")

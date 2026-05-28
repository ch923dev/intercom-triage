"""Add non_actionable_kind to tickets + ai_cache (roadmap 4.2 / T107).

Structured kind for non-actionable tickets: auto_reply / thanks / spam /
out_of_office / other. AI-derived; nullable; only set when the ticket is
non-actionable. Additive — pre-existing rows carry NULL.

Revision ID: 0020
Revises: 0019
Create Date: 2026-05-28 00:00:20.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_KINDS = ("auto_reply", "thanks", "spam", "out_of_office", "other")
_KIND_LIST = ",".join(f"'{k}'" for k in _KINDS)


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("non_actionable_kind", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "tickets_non_actionable_kind_check",
            f"non_actionable_kind IS NULL OR (resolved_source = 'non_actionable' "
            f"AND non_actionable_kind IN ({_KIND_LIST}))",
        )
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.add_column(sa.Column("non_actionable_kind", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ai_cache_non_actionable_kind_check",
            f"non_actionable_kind IS NULL OR non_actionable_kind IN ({_KIND_LIST})",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_non_actionable_kind_check", type_="check")
        batch_op.drop_column("non_actionable_kind")
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_non_actionable_kind_check", type_="check")
        batch_op.drop_column("non_actionable_kind")

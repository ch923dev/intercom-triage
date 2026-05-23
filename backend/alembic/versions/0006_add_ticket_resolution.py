"""Add ticket-resolution fields.

Adds:
- tickets.resolved_at, .resolved_source, .ai_resolve_enabled, .resolution_chip_dismissed_at
- ai_cache.ai_resolution_verdict, .ai_resolution_confidence, .ai_resolution_reason
- settings.ai_resolve_default, .ai_resolve_confidence_threshold

Revision ID: 0006
Revises: 0005
Create Date: 2026-05-23 00:00:05.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("resolved_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("resolved_source", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_resolve_enabled", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("resolution_chip_dismissed_at", sa.DateTime(), nullable=True))
        batch_op.create_check_constraint(
            "tickets_resolved_xor_check",
            "(resolved_at IS NULL) = (resolved_source IS NULL)",
        )
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source IN ('manual','intercom_closed')",
        )
    op.create_index(
        "ix_tickets_resolved_at",
        "tickets",
        ["resolved_at"],
        sqlite_where=sa.text("resolved_at IS NOT NULL"),
        postgresql_where=sa.text("resolved_at IS NOT NULL"),
    )

    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.add_column(sa.Column("ai_resolution_verdict", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_resolution_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("ai_resolution_reason", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ai_cache_resolution_verdict_check",
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict IN ('resolved','not_resolved')",
        )
        batch_op.create_check_constraint(
            "ai_cache_resolution_reason_len_check",
            "ai_resolution_reason IS NULL OR length(ai_resolution_reason) <= 120",
        )

    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("ai_resolve_default", sa.Boolean(), nullable=False, server_default="0"),
        )
        batch_op.add_column(
            sa.Column(
                "ai_resolve_confidence_threshold",
                sa.Float(),
                nullable=False,
                server_default="0.7",
            ),
        )
        batch_op.create_check_constraint(
            "settings_ai_resolve_threshold_check",
            "ai_resolve_confidence_threshold BETWEEN 0.0 AND 1.0",
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_constraint("settings_ai_resolve_threshold_check", type_="check")
        batch_op.drop_column("ai_resolve_confidence_threshold")
        batch_op.drop_column("ai_resolve_default")

    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_resolution_reason_len_check", type_="check")
        batch_op.drop_constraint("ai_cache_resolution_verdict_check", type_="check")
        batch_op.drop_column("ai_resolution_reason")
        batch_op.drop_column("ai_resolution_confidence")
        batch_op.drop_column("ai_resolution_verdict")

    op.drop_index("ix_tickets_resolved_at", table_name="tickets")
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.drop_constraint("tickets_resolved_xor_check", type_="check")
        batch_op.drop_column("resolution_chip_dismissed_at")
        batch_op.drop_column("ai_resolve_enabled")
        batch_op.drop_column("resolved_source")
        batch_op.drop_column("resolved_at")

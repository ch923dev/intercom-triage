"""Widen resolution verdict + resolved_source CHECK constraints.

Adds 'non_actionable' to:
- tickets.resolved_source ∈ {'manual', 'intercom_closed', 'non_actionable'}
- ai_cache.ai_resolution_verdict ∈ {'resolved', 'not_resolved', 'non_actionable'}

Reference: docs/superpowers/specs/2026-05-25-non-actionable-tickets-design.md §3.

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-25 00:00:00.000000 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable')",
        )

    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_resolution_verdict_check", type_="check")
        batch_op.create_check_constraint(
            "ai_cache_resolution_verdict_check",
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict "
            "IN ('resolved','not_resolved','non_actionable')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_resolution_verdict_check", type_="check")
        batch_op.create_check_constraint(
            "ai_cache_resolution_verdict_check",
            "ai_resolution_verdict IS NULL OR ai_resolution_verdict "
            "IN ('resolved','not_resolved')",
        )

    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source IN ('manual','intercom_closed')",
        )

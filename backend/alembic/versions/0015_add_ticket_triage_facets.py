"""Add roadmap-0.2 triage facets (priority / sentiment / multi-label).

Purely additive, nullable columns on the SAME categorization output (no new AI
call, cache key unchanged). Adds:
- tickets.ai_priority, .ai_sentiment, .ai_labels
- ai_cache.ai_priority, .ai_sentiment, .ai_labels

`ai_labels` stores secondary multi-label tags as a JSON string array (defaults
to '[]'); `ai_priority` / `ai_sentiment` are nullable enums guarded by CHECKs.

Revision ID: 0015
Revises: 0014
Create Date: 2026-05-27 00:00:00.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.add_column(sa.Column("ai_priority", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_sentiment", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("ai_labels", sa.JSON(), nullable=False, server_default="[]"),
        )
        batch_op.create_check_constraint(
            "tickets_ai_priority_check",
            "ai_priority IS NULL OR ai_priority IN ('low','normal','high','urgent')",
        )
        batch_op.create_check_constraint(
            "tickets_ai_sentiment_check",
            "ai_sentiment IS NULL OR ai_sentiment IN ('negative','neutral','positive')",
        )

    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.add_column(sa.Column("ai_priority", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("ai_sentiment", sa.Text(), nullable=True))
        batch_op.add_column(
            sa.Column("ai_labels", sa.JSON(), nullable=False, server_default="[]"),
        )
        batch_op.create_check_constraint(
            "ai_cache_ai_priority_check",
            "ai_priority IS NULL OR ai_priority IN ('low','normal','high','urgent')",
        )
        batch_op.create_check_constraint(
            "ai_cache_ai_sentiment_check",
            "ai_sentiment IS NULL OR ai_sentiment IN ('negative','neutral','positive')",
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_ai_sentiment_check", type_="check")
        batch_op.drop_constraint("ai_cache_ai_priority_check", type_="check")
        batch_op.drop_column("ai_labels")
        batch_op.drop_column("ai_sentiment")
        batch_op.drop_column("ai_priority")

    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_ai_sentiment_check", type_="check")
        batch_op.drop_constraint("tickets_ai_priority_check", type_="check")
        batch_op.drop_column("ai_labels")
        batch_op.drop_column("ai_sentiment")
        batch_op.drop_column("ai_priority")

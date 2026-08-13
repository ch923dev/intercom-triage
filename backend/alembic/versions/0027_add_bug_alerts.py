"""Add bug_alerts table + bug verdict columns on ai_cache (US-044).

Early bug detection rides the existing categorization call as a fifth facet, so
the verdict lands on `ai_cache` alongside the other AI-derived fields (a cache
HIT must still yield a verdict — cf. 0026, which added `subject` for exactly
this reason). `bug_alerts` is the dedup + outbox table: PK on `ticket_id` makes a
duplicate Slack post impossible by construction, and `posted_at IS NULL` is the
outbox.

Additive — pre-existing `ai_cache` rows carry NULL and are NOT backfilled
(design decision 3: no historical re-scan).

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-13 00:00:27.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.add_column(sa.Column("bug_severity", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("bug_confidence", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("bug_evidence", sa.Text(), nullable=True))
        batch_op.create_check_constraint(
            "ai_cache_bug_severity_check",
            "bug_severity IS NULL OR bug_severity IN ('low','medium','high')",
        )
        batch_op.create_check_constraint(
            "ai_cache_bug_evidence_len_check",
            "bug_evidence IS NULL OR length(bug_evidence) <= 200",
        )

    op.create_table(
        "bug_alerts",
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.Column("severity", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("occurrences", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("first_detected_at", sa.DateTime(), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(), nullable=False),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("posted_severity", sa.Text(), nullable=True),
        sa.Column("slack_channel", sa.Text(), nullable=True),
        sa.Column("slack_ts", sa.Text(), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("ticket_id"),
        sa.CheckConstraint(
            "severity IN ('low','medium','high')",
            name="bug_alerts_severity_check",
        ),
        sa.CheckConstraint(
            "posted_severity IS NULL OR posted_severity IN ('low','medium','high')",
            name="bug_alerts_posted_severity_check",
        ),
        sa.CheckConstraint(
            "evidence IS NULL OR length(evidence) <= 200",
            name="bug_alerts_evidence_len_check",
        ),
        sa.CheckConstraint("occurrences >= 1", name="bug_alerts_occurrences_check"),
    )
    op.create_index("ix_bug_alerts_outbox", "bug_alerts", ["posted_at", "dismissed_at"])


def downgrade() -> None:
    op.drop_index("ix_bug_alerts_outbox", table_name="bug_alerts")
    op.drop_table("bug_alerts")
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_constraint("ai_cache_bug_evidence_len_check", type_="check")
        batch_op.drop_constraint("ai_cache_bug_severity_check", type_="check")
        batch_op.drop_column("bug_evidence")
        batch_op.drop_column("bug_confidence")
        batch_op.drop_column("bug_severity")

"""Add ticket_clusters + ticket_cluster_members tables.

Roadmap 3.1 — recurring-issue clustering. The offline periodic job clusters
RESOLVED tickets' existing embeddings (HDBSCAN) and labels each cluster with
c-TF-IDF top terms from the customer-visible `parts[]` + title only (invariant
#4). HDBSCAN noise points (label -1) are excluded, never force-fit. Reading
`ticket_embeddings` never touches `ai_cache` / the content signature (#6).

Snapshot semantics: each run wipes the prior rows and inserts the fresh ones in
one transaction. Member ids live in the join table, cascade-deleted with the
parent cluster. No FK from members to `tickets` — ticket ids are Intercom-owned
and churn on re-sync (mirrors `followups`).

Revision ID: 0017
Revises: 0016
Create Date: 2026-05-27 00:00:17.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "ticket_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("top_terms", sa.JSON(), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column(
            "computed_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("size >= 0", name="ticket_clusters_size_nonneg"),
    )
    op.create_index("ix_ticket_clusters_size", "ticket_clusters", ["size"])

    op.create_table(
        "ticket_cluster_members",
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("ticket_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["cluster_id"],
            ["ticket_clusters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("cluster_id", "ticket_id"),
    )
    op.create_index(
        "ix_ticket_cluster_members_ticket",
        "ticket_cluster_members",
        ["ticket_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ticket_cluster_members_ticket", table_name="ticket_cluster_members")
    op.drop_table("ticket_cluster_members")
    op.drop_index("ix_ticket_clusters_size", table_name="ticket_clusters")
    op.drop_table("ticket_clusters")

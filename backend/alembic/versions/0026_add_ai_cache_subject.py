"""Add subject to ai_cache (review fix — cache-hit title wipe).

The AI-generated `subject` (the ticket's fallback title for title-less Intercom
conversations) was written to `tickets.title` on the first sync but never cached.
A cache-hit re-sync then re-derived the title from a cached result whose subject
defaulted to "" and wiped the card headline to NULL. Cache the subject so the
cache-read path carries the real value.

Additive — pre-existing rows carry NULL (treated as "no cached subject").

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-23 00:00:26.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.add_column(sa.Column("subject", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ai_cache") as batch_op:
        batch_op.drop_column("subject")

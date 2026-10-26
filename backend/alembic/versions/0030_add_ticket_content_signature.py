"""Add tickets.content_signature_at — the last customer-visible part's timestamp (T205).

Intercom's `updated_at` advances on internal notes, assignments and snoozes. The
override rule and the resolution chip keyed on it, so a teammate's internal note
silently reverted an operator's manual category and raised a false "new reply"
chip. They now compare against this column instead: the same value the AI cache
keys on (invariant #6), written by `_upsert_ticket` on every ingest.

Backfilled from the stored `parts` JSON (max part `created_at`, else the
ticket's `created_at` — exactly `services.tickets._content_signature`), so the
fix applies to existing rows without waiting for a re-sync.

Revision ID: 0030
Revises: 0029
Create Date: 2026-10-26 00:00:30.000000 UTC
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None

_tickets = sa.table(
    "tickets",
    sa.column("id", sa.Text()),
    sa.column("parts", sa.JSON()),
    sa.column("created_at", sa.DateTime()),
    sa.column("content_signature_at", sa.DateTime()),
)


def _naive_utc(raw: str) -> datetime:
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def _signature(parts: list[dict[str, Any]] | None, created_at: datetime) -> datetime:
    stamps = [_naive_utc(p["created_at"]) for p in parts or [] if p.get("created_at")]
    return max(stamps) if stamps else created_at


def upgrade() -> None:
    op.add_column("tickets", sa.Column("content_signature_at", sa.DateTime(), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.select(_tickets.c.id, _tickets.c.parts, _tickets.c.created_at)).all()
    for row in rows:
        bind.execute(
            _tickets.update()
            .where(_tickets.c.id == row.id)
            .values(content_signature_at=_signature(row.parts, row.created_at))
        )

    with op.batch_alter_table("tickets") as batch_op:
        batch_op.alter_column("content_signature_at", existing_type=sa.DateTime(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("content_signature_at")

"""Migration 0030 backfills `tickets.content_signature_at` from the stored
parts (T205), so the override/chip fix applies to existing rows without waiting
for a re-sync — and the table rebuild keeps the existing constraints."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.exc import IntegrityError

from alembic.runtime.environment import EnvironmentContext
from alembic.script import ScriptDirectory
from app.models import Base, _make_alembic_cfg


def _migrate(connection: Connection, target: str, *, down: bool = False) -> None:
    cfg = _make_alembic_cfg()
    script = ScriptDirectory.from_config(cfg)

    def step(rev: Any, context: Any) -> Any:
        return script._downgrade_revs(target, rev) if down else script._upgrade_revs(target, rev)

    with EnvironmentContext(cfg, script, fn=step, destination_rev=target) as env:
        env.configure(connection=connection, target_metadata=Base.metadata, render_as_batch=True)
        with env.begin_transaction():
            env.run_migrations()


def _insert_ticket(conn: Connection, ticket_id: str, *, parts: list[dict[str, Any]]) -> None:
    conn.execute(
        text(
            "INSERT INTO tickets (id, author, parts, created_at, updated_at) "
            "VALUES (:id, '{}', :parts, :created, :updated)"
        ),
        {
            "id": ticket_id,
            "parts": json.dumps(parts),
            "created": "2026-05-01 08:00:00.000000",
            # Intercom's updated_at — deliberately later than every part, the
            # way an internal note leaves it.
            "updated": "2026-05-01 18:00:00.000000",
        },
    )


@pytest.fixture
def conn_at_0029() -> Iterator[Connection]:
    engine = create_engine("sqlite://")
    with engine.connect() as conn:
        _migrate(conn, "0029")
        conn.commit()
        yield conn
    engine.dispose()


def test_backfill_takes_the_last_part_not_updated_at(conn_at_0029: Connection) -> None:
    conn = conn_at_0029
    # Stored shape: parts are `model_dump(mode="json")`, so ISO strings with Z.
    _insert_ticket(
        conn,
        "with-parts",
        parts=[
            {"body": "first", "created_at": "2026-05-01T09:00:00Z"},
            {"body": "admin reply", "created_at": "2026-05-01T11:30:00Z", "is_admin": True},
        ],
    )
    _insert_ticket(conn, "no-parts", parts=[])
    conn.commit()

    _migrate(conn, "0030")
    conn.commit()

    rows = dict(conn.execute(text("SELECT id, content_signature_at FROM tickets")).tuples().all())
    assert str(rows["with-parts"]).startswith("2026-05-01 11:30:00")
    assert str(rows["no-parts"]).startswith("2026-05-01 08:00:00")


def test_column_is_not_null_and_rebuild_keeps_constraints(conn_at_0029: Connection) -> None:
    conn = conn_at_0029
    _migrate(conn, "0030")
    conn.commit()

    columns = {r[1]: r for r in conn.exec_driver_sql("PRAGMA table_info(tickets)")}
    assert columns["content_signature_at"][3] == 1  # notnull

    # The batch rebuild must not drop the resolved_at ⇔ resolved_source pair
    # CHECK (invariant #10) — SQLite only keeps it if the rebuild reflected it.
    with pytest.raises(IntegrityError):
        conn.execute(
            text(
                "INSERT INTO tickets (id, author, parts, created_at, updated_at, "
                "content_signature_at, resolved_at) VALUES ('bad', '{}', '[]', "
                "'2026-05-01', '2026-05-01', '2026-05-01', '2026-05-01')"
            )
        )
    conn.rollback()


def test_downgrade_drops_the_column(conn_at_0029: Connection) -> None:
    conn = conn_at_0029
    _migrate(conn, "0030")
    _migrate(conn, "0029", down=True)
    conn.commit()
    columns = {r[1] for r in conn.exec_driver_sql("PRAGMA table_info(tickets)")}
    assert "content_signature_at" not in columns

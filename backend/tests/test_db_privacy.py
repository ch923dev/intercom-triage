"""The engine must never stringify bound parameters into an exception.

Reference: plan.md §11, tasks.md T194. NFR-006 / NFR-016, invariant #20.

Bound parameters on the ingest commit are `tickets.parts` (the whole customer
thread) and on the `bug_alerts` upsert are `evidence` (a verbatim customer
sentence). Two call sites stringify a DB exception into a log line —
`main._intercom_poll_loop` (`error=str(exc)`) and `bug_alerts.record_bug_alerts`
(`exc_info=True`) — so `hide_parameters=True` is what keeps those lines free of
customer text.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import StatementError

from app.db import make_engine

_QUOTE = "the refund never arrived and I want an explanation"


async def test_engine_hides_bound_parameters_on_statement_error() -> None:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.connect() as conn:
            with pytest.raises(StatementError) as excinfo:
                await conn.execute(
                    text("INSERT INTO no_such_table (body) VALUES (:quote)"),
                    {"quote": _QUOTE},
                )
        rendered = str(excinfo.value)
        assert _QUOTE not in rendered
        assert "hidden" in rendered
    finally:
        await engine.dispose()


async def test_engine_declares_hide_parameters() -> None:
    """Structural guard: the flag survives a refactor of the error path above."""
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    try:
        assert engine.sync_engine.hide_parameters is True
    finally:
        await engine.dispose()

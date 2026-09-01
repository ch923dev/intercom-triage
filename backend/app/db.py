"""Engine + session factory + FastAPI dependency.

Reference: plan.md §5, tasks.md T006.

`models.init_db` consumes the engine + session factory created here. Route
handlers depend on `get_session`, which reads the factory bound onto
`app.state.session_factory` in the lifespan hook (see `main.py`).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    """SQLite refuses to create the file if the parent dir doesn't exist."""
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        return
    rel = database_url[len(prefix) :]
    if rel.startswith(":memory:") or not rel:
        return
    Path(rel).parent.mkdir(parents=True, exist_ok=True)


def make_engine(database_url: str) -> AsyncEngine:
    """Create the async engine. Works for SQLite (default) and Postgres.

    `hide_parameters=True` is a privacy control, not a tuning knob. Every
    SQLAlchemy `StatementError` stringifies its bound parameters, and the bound
    parameters of the ingest commit and the `bug_alerts` upsert are customer
    conversation text: `tickets.parts` (the whole thread) and `evidence` (a
    verbatim customer sentence). Two call sites stringify such an exception —
    `main._intercom_poll_loop` (`error=str(exc)`) and
    `bug_alerts.record_bug_alerts` (`exc_info=True`) — and both are correct as
    written only because of this flag. NFR-006 / NFR-016, invariant #20.
    """
    _ensure_sqlite_parent_dir(database_url)
    return create_async_engine(database_url, future=True, hide_parameters=True)


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a per-request async session."""
    factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with factory() as session:
        yield session

"""Alembic environment — async-aware, SQLite-safe, URL from AppConfig.

Key design decisions:
- Uses run_async_migrations() so the async engine (aiosqlite / asyncpg) is
  used directly.  Alembic 1.13+ supports async via run_sync on the connection.
- render_as_batch=True enables SQLite's copy-rebuild path for ALTER TABLE.
  This is a no-op on Postgres (which supports real ALTER TABLE).
- The database URL is pulled from AppConfig so there is a single source of
  truth and no hardcoded URL in alembic.ini.
- For tests, conftest.py sets the DATABASE_URL env var before init_db is
  called, so AppConfig picks up the in-memory URL automatically.
"""

from __future__ import annotations

import asyncio
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

# ---------------------------------------------------------------------------
# Ensure the backend/ directory is on sys.path so `app.*` imports work when
# the alembic CLI is invoked from backend/.
# ---------------------------------------------------------------------------
_backend_dir = Path(__file__).parent.parent
if str(_backend_dir) not in sys.path:
    sys.path.insert(0, str(_backend_dir))

from app.config import AppConfig  # noqa: E402
from app.models import Base  # noqa: E402

# ---------------------------------------------------------------------------
# Alembic Config object — provides access to alembic.ini values.
# ---------------------------------------------------------------------------
config = context.config

# Interpret the config file's logging section if present.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata our migrations are checked against.
target_metadata = Base.metadata


def _get_url() -> str:
    """Return the database URL.

    Priority order:
    1. cfg.attributes["database_url_override"] — set by _make_alembic_cfg in
       models.py when init_db calls programmatic upgrade (covers tests).
    2. sqlalchemy.url from alembic.ini — set by _make_alembic_cfg as a
       fallback so the alembic CLI also picks up the right URL.
    3. AppConfig().database_url — last resort (alembic CLI without explicit URL).
    """
    override: str | None = config.attributes.get("database_url_override")
    if override:
        return override
    ini_url: str | None = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    return AppConfig().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL to stdout, no DB connection)."""
    url = _get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations synchronously inside an async connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine and drive migrations through it."""
    url = _get_url()
    connectable = create_async_engine(url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    """Entry point for online (connected) migrations."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

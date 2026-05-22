"""Test fixtures — in-memory SQLite + ASGI client + direct session access.

References: tasks.md T005–T028.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig, get_config
from app.db import make_engine, make_session_factory
from app.main import create_app
from app.models import init_db


@pytest.fixture
def test_config() -> AppConfig:
    """Config pinned to an in-memory SQLite + dummy secrets.

    SQLAlchemy keeps a single connection alive for `:memory:` (StaticPool), so
    the schema seeded by `init_db` is visible to every session in the test.
    """
    return AppConfig(
        intercom_access_token="test-intercom-token",
        openrouter_api_key="test-openrouter-key",
        database_url="sqlite+aiosqlite:///:memory:",
        host="127.0.0.1",
        port=8000,
        cache_ttl_seconds=300,
        ai_concurrency=4,
    )


@pytest_asyncio.fixture
async def app(test_config: AppConfig) -> AsyncIterator[FastAPI]:
    """A wired app against a fresh seeded DB. External clients default to None;
    a test can set `app.state.intercom` / `app.state.openrouter` itself."""
    get_config.cache_clear()
    application = create_app()

    engine = make_engine(test_config.database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine, session_factory)

    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.config = test_config
    application.state.intercom = None
    application.state.openrouter = None
    application.dependency_overrides[get_config] = lambda: test_config

    yield application

    await engine.dispose()
    get_config.cache_clear()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    """Direct DB session for service-level tests + assertions."""
    factory = app.state.session_factory
    async with factory() as s:
        yield s

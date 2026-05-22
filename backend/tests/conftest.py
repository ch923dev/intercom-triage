"""Test fixtures — in-memory SQLite + ASGI client.

References: tasks.md T005, T006, T007.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.config import AppConfig, get_config
from app.db import make_engine, make_session_factory
from app.main import create_app
from app.models import init_db


@pytest.fixture
def test_config() -> AppConfig:
    """Config pinned to an in-memory SQLite + dummy secrets."""
    # NOTE: shared in-memory connection across the same engine; works because
    # SQLAlchemy's aiosqlite driver keeps one connection alive per engine.
    return AppConfig(
        intercom_access_token="test-intercom-token",
        openrouter_api_key="test-openrouter-key",
        database_url="sqlite+aiosqlite:///:memory:",
        host="127.0.0.1",
        port=8000,
    )


@pytest_asyncio.fixture
async def client(test_config: AppConfig) -> AsyncIterator[AsyncClient]:
    """ASGI client with the lifespan-equivalent boot wired up against a fresh DB."""
    get_config.cache_clear()
    app = create_app()

    engine = make_engine(test_config.database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine, session_factory)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.config = test_config

    # Override the cached config so /health sees test values.
    app.dependency_overrides[get_config] = lambda: test_config

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()
    get_config.cache_clear()

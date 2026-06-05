"""Test fixtures — in-memory SQLite + ASGI client + direct session access.

References: tasks.md T005–T028.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embeddings
from app.config import AppConfig, get_config
from app.db import make_engine, make_session_factory
from app.deps import CurrentUser, get_current_user, require_session_or_bearer
from app.main import create_app
from app.models import User, init_db


class FakeEncoder:
    """Deterministic, fully-offline stand-in for the sentence-transformers model.

    Records every text it was asked to encode (so tests can assert which content
    was/wasn't embedded — invariant #4) and returns a 384-dim vector derived from
    a hash of the text. Identical text → identical vector (distance ~0 on a
    nearest-neighbour query); the real ~80 MB model never loads.
    """

    def __init__(self) -> None:
        self.encoded: list[str] = []

    def encode_one(self, text: str) -> list[float]:
        self.encoded.append(text)
        # Expand a stable digest into EMBEDDING_DIM floats in [-1, 1].
        out: list[float] = []
        seed = 0
        while len(out) < embeddings.EMBEDDING_DIM:
            digest = hashlib.sha256(f"{seed}:{text}".encode()).digest()
            for byte in digest:
                out.append((byte / 127.5) - 1.0)
                if len(out) >= embeddings.EMBEDDING_DIM:
                    break
            seed += 1
        return out


@pytest.fixture(autouse=True)
def fake_encoder() -> Iterator[FakeEncoder]:
    """Inject the deterministic fake encoder for EVERY test so the suite stays
    offline and fast — the real model is never downloaded or loaded."""
    encoder = FakeEncoder()
    embeddings.set_encoder(encoder)
    try:
        yield encoder
    finally:
        embeddings.set_encoder(None)


@pytest.fixture
def test_config(tmp_path_factory: pytest.TempPathFactory) -> AppConfig:
    """Config pinned to an in-memory SQLite + dummy secrets + an isolated
    on-disk attachments dir under a pytest tmp path. Each test session gets
    its own attachments tree so uploads do not bleed across tests."""
    attachments_root = tmp_path_factory.mktemp("attachments")
    return AppConfig(
        openrouter_api_key="test-openrouter-key",
        # Dummy token so the broad suite boots non-degraded; tests that exercise
        # the missing-token path construct their own AppConfig with it cleared.
        intercom_access_token="test-intercom-token",
        intercom_workspace_app_id="testworkspace",
        database_url="sqlite+aiosqlite:///:memory:",
        cache_ttl_seconds=300,
        ai_concurrency=4,
        attachments_dir=attachments_root,
        session_jwt_secret="test-session-secret",
        session_cookie_secure=False,  # http://test base URL — no Secure flag
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

    # The get_current_user override returns id=1; seed the matching mirror user
    # so attribution / assignment FKs (resolved_by, assigned_to) resolve.
    async with session_factory() as seed_session:
        seed_session.add(
            User(
                id=1,
                onlysales_id="seed-oid",
                email="op@test",
                name="Seed Operator",
                scope="admin",
            )
        )
        await seed_session.commit()

    application.state.engine = engine
    application.state.session_factory = session_factory
    application.state.config = test_config
    application.state.openrouter = None
    application.state.onlysales = None
    application.dependency_overrides[get_config] = lambda: test_config
    application.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1, onlysales_id="seed-oid", email="op@test", scope="admin"
    )
    application.dependency_overrides[require_session_or_bearer] = lambda: None

    yield application

    await engine.dispose()
    get_config.cache_clear()


@pytest_asyncio.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def unauth_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client with NO get_current_user override — for testing the 401 gate."""
    app.dependency_overrides.pop(get_current_user, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def session(app: FastAPI) -> AsyncIterator[AsyncSession]:
    """Direct DB session for service-level tests + assertions."""
    factory = app.state.session_factory
    async with factory() as s:
        yield s

"""Refresh reuse-detection: a replayed rotated token revokes the chain."""

from __future__ import annotations

import pytest

from app.clients.onlysales import OnlySalesIdentity
from app.models import Session as SessionRow
from app.models import User
from app.services import auth as svc


@pytest.fixture
async def seeded(session):
    user = User(onlysales_id="oid-1", email="op@x", scope="agent")
    session.add(user)
    await session.flush()
    issued = await svc.complete_login(
        session,
        identity=OnlySalesIdentity(
            access_token="os-access",
            refresh_token=None,
            onlysales_id="oid-1",
            email="op@x",
            name="Op",
            scope="agent",
        ),
        jwt_secret="s" * 32,
        access_ttl=1800,
        refresh_ttl=2_592_000,
        encryption_key="",
        new_session_id="sess-1",
    )
    return user, issued


async def test_reuse_of_rotated_token_revokes_chain(session, seeded) -> None:
    _user, issued = seeded
    r1 = issued.refresh_cookie
    rotated = await svc.rotate_session(
        session, raw_refresh=r1, jwt_secret="s" * 32, access_ttl=1800, refresh_ttl=2_592_000
    )
    r2 = rotated.refresh_cookie
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(
            session, raw_refresh=r1, jwt_secret="s" * 32, access_ttl=1800, refresh_ttl=2_592_000
        )
    row = await session.get(SessionRow, "sess-1")
    assert row is not None and row.revoked_at is not None
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(
            session, raw_refresh=r2, jwt_secret="s" * 32, access_ttl=1800, refresh_ttl=2_592_000
        )

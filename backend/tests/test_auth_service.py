"""Phase 1 — auth service: login → mirror + session; refresh rotates; logout revokes."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.clients.onlysales import OnlySalesIdentity
from app.models import Session as SessionRow
from app.models import User
from app.security import tokens
from app.services import auth as svc

SECRET = "svc-secret"


def _identity(refresh: str | None = "os-refresh") -> OnlySalesIdentity:
    return OnlySalesIdentity(
        access_token="os-access",
        refresh_token=refresh,
        onlysales_id="oid-1",
        email="op@example.com",
        name="Op E",
        scope="admin",
    )


@pytest.mark.asyncio
async def test_login_creates_user_and_session(session) -> None:
    out = await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id=str(uuid.uuid4()),
    )
    claims = tokens.verify_access_token(SECRET, out.access_token)
    user = await session.scalar(select(User).where(User.onlysales_id == "oid-1"))
    assert user is not None
    assert claims.user_id == user.id
    assert user.last_login_at is not None
    sess = await session.scalar(
        select(SessionRow).where(
            SessionRow.refresh_token_hash == tokens.hash_refresh_token(out.refresh_cookie)
        )
    )
    assert sess is not None
    assert sess.revoked_at is None


@pytest.mark.asyncio
async def test_login_is_idempotent_on_user(session) -> None:
    await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id="s1",
    )
    await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id="s2",
    )
    users = (await session.scalars(select(User).where(User.onlysales_id == "oid-1"))).all()
    assert len(users) == 1


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_keeps_session(session) -> None:
    login = await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id="s1",
    )
    rotated = await svc.rotate_session(
        session,
        raw_refresh=login.refresh_cookie,
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
    )
    assert rotated.refresh_cookie != login.refresh_cookie
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(
            session,
            raw_refresh=login.refresh_cookie,
            jwt_secret=SECRET,
            access_ttl=1800,
            refresh_ttl=3600,
        )


@pytest.mark.asyncio
async def test_logout_revokes(session) -> None:
    login = await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id="s1",
    )
    await svc.revoke_by_refresh(session, raw_refresh=login.refresh_cookie)
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(
            session,
            raw_refresh=login.refresh_cookie,
            jwt_secret=SECRET,
            access_ttl=1800,
            refresh_ttl=3600,
        )

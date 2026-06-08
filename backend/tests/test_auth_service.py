"""Phase 1 — auth service: login → mirror + session; refresh rotates; logout revokes."""

from __future__ import annotations

import logging
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
async def test_refresh_reuse_is_logged(session, caplog) -> None:
    """Reuse-detection is the most security-relevant branch — replaying a
    rotated-away token must emit a WARNING so a genuine theft is distinguishable
    in the logs from a benign two-tab double-refresh (which trips the same path).
    """
    login = await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id="s1",
    )
    await svc.rotate_session(
        session,
        raw_refresh=login.refresh_cookie,
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
    )
    with caplog.at_level(logging.WARNING, logger="triage"):
        with pytest.raises(svc.AuthSessionError):
            # Replay the now-superseded original token → reuse-detection fires.
            await svc.rotate_session(
                session,
                raw_refresh=login.refresh_cookie,
                jwt_secret=SECRET,
                access_ttl=1800,
                refresh_ttl=3600,
            )
    assert any("refresh_reuse_detected" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_rotate_rejects_inactive_user(session) -> None:
    """A deactivated user's refresh must be rejected. This is the hard-revocation
    point: the stateless access JWT is NOT re-checked per request (see invariant
    #16), so deactivation takes full effect only when the access token expires
    and the next refresh lands here."""
    login = await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id="s1",
    )
    user = await session.scalar(select(User).where(User.onlysales_id == "oid-1"))
    assert user is not None
    user.is_active = False
    await session.commit()
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(
            session,
            raw_refresh=login.refresh_cookie,
            jwt_secret=SECRET,
            access_ttl=1800,
            refresh_ttl=3600,
        )


@pytest.mark.asyncio
async def test_revoke_all_for_user_kills_every_session(session) -> None:
    """`revoke_all_for_user` (the /auth/logout-all path) must revoke EVERY live
    session for the user, so a refresh on any of them fails afterwards."""
    cookies = []
    for sid in ("s1", "s2", "s3"):
        out = await svc.complete_login(
            session,
            identity=_identity(),
            jwt_secret=SECRET,
            access_ttl=1800,
            refresh_ttl=3600,
            encryption_key="",
            new_session_id=sid,
        )
        cookies.append(out.refresh_cookie)
    user = await session.scalar(select(User).where(User.onlysales_id == "oid-1"))
    assert user is not None
    await svc.revoke_all_for_user(session, user_id=user.id)
    for cookie in cookies:
        with pytest.raises(svc.AuthSessionError):
            await svc.rotate_session(
                session,
                raw_refresh=cookie,
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

"""Auth orchestration — mirror the OnlySales identity, manage our sessions.

complete_login: upsert user mirror + create a session + mint an access token.
rotate_session: validate a refresh cookie, rotate it, re-mint access.
revoke_by_refresh / revoke_all_for_user: logout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.onlysales import OnlySalesIdentity
from app.models import Session as SessionRow
from app.models import User
from app.security import tokens
from app.util import naive_utcnow


class AuthSessionError(Exception):
    """Raised when a refresh cookie is unknown, expired, or revoked."""


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_cookie: str
    user: User


async def _upsert_user(session: AsyncSession, identity: OnlySalesIdentity) -> User:
    user = await session.scalar(select(User).where(User.onlysales_id == identity.onlysales_id))
    if user is None:
        user = User(onlysales_id=identity.onlysales_id, email=identity.email)
        session.add(user)
    user.email = identity.email
    user.name = identity.name
    user.scope = identity.scope
    user.last_login_at = naive_utcnow()
    await session.flush()
    return user


def _mint(user: User, secret: str, ttl: int) -> str:
    return tokens.mint_access_token(
        secret,
        user_id=user.id,
        onlysales_id=user.onlysales_id,
        email=user.email,
        scope=user.scope,
        ttl_seconds=ttl,
    )


async def complete_login(
    session: AsyncSession,
    *,
    identity: OnlySalesIdentity,
    jwt_secret: str,
    access_ttl: int,
    refresh_ttl: int,
    encryption_key: str,
    new_session_id: str,
) -> IssuedSession:
    user = await _upsert_user(session, identity)
    raw_refresh = tokens.generate_refresh_token()
    now = naive_utcnow()
    row = SessionRow(
        id=new_session_id,
        user_id=user.id,
        refresh_token_hash=tokens.hash_refresh_token(raw_refresh),
        onlysales_refresh_encrypted=tokens.encrypt_secret(encryption_key, identity.refresh_token)
        if identity.refresh_token
        else None,
        issued_at=now,
        expires_at=now + timedelta(seconds=refresh_ttl),
        last_used_at=now,
    )
    session.add(row)
    access = _mint(user, jwt_secret, access_ttl)
    await session.commit()
    return IssuedSession(access_token=access, refresh_cookie=raw_refresh, user=user)


async def _active_session(session: AsyncSession, raw_refresh: str) -> SessionRow:
    row = await session.scalar(
        select(SessionRow).where(
            SessionRow.refresh_token_hash == tokens.hash_refresh_token(raw_refresh)
        )
    )
    if row is None:
        raise AuthSessionError("unknown refresh token")
    if row.revoked_at is not None:
        raise AuthSessionError("session revoked")
    if row.expires_at <= naive_utcnow():
        raise AuthSessionError("session expired")
    return row


async def rotate_session(
    session: AsyncSession,
    *,
    raw_refresh: str,
    jwt_secret: str,
    access_ttl: int,
    refresh_ttl: int,
) -> IssuedSession:
    row = await _active_session(session, raw_refresh)
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthSessionError("user inactive")
    new_raw = tokens.generate_refresh_token()
    now = naive_utcnow()
    row.refresh_token_hash = tokens.hash_refresh_token(new_raw)
    row.last_used_at = now
    row.expires_at = now + timedelta(seconds=refresh_ttl)
    access = _mint(user, jwt_secret, access_ttl)
    await session.commit()
    return IssuedSession(access_token=access, refresh_cookie=new_raw, user=user)


async def revoke_by_refresh(session: AsyncSession, *, raw_refresh: str) -> None:
    row = await session.scalar(
        select(SessionRow).where(
            SessionRow.refresh_token_hash == tokens.hash_refresh_token(raw_refresh)
        )
    )
    if row is not None and row.revoked_at is None:
        row.revoked_at = naive_utcnow()
        await session.commit()


async def revoke_all_for_user(session: AsyncSession, *, user_id: int) -> None:
    await session.execute(
        update(SessionRow)
        .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=naive_utcnow())
    )
    await session.commit()

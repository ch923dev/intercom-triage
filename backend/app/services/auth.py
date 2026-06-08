"""Auth orchestration — mirror the OnlySales identity, manage our sessions.

complete_login: upsert user mirror + create a session + mint an access token.
rotate_session: validate a refresh cookie, rotate it, re-mint access.
revoke_by_refresh / revoke_all_for_user: logout.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.onlysales import OnlySalesIdentity
from app.models import Session as SessionRow
from app.models import User
from app.observability import log_event
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


async def _lookup_session(
    session: AsyncSession, raw_refresh: str
) -> tuple[SessionRow | None, bool]:
    """Find the session by current hash, else by the previous (rotated-away)
    hash. Returns (row, reused) — reused=True means a superseded token was
    replayed (theft signal)."""
    h = tokens.hash_refresh_token(raw_refresh)
    row = await session.scalar(select(SessionRow).where(SessionRow.refresh_token_hash == h))
    if row is not None:
        return row, False
    prior = await session.scalar(select(SessionRow).where(SessionRow.prev_refresh_token_hash == h))
    return prior, prior is not None


async def rotate_session(
    session: AsyncSession,
    *,
    raw_refresh: str,
    jwt_secret: str,
    access_ttl: int,
    refresh_ttl: int,
) -> IssuedSession:
    row, reused = await _lookup_session(session, raw_refresh)
    if row is None:
        raise AuthSessionError("unknown refresh token")
    if reused:
        # Reuse-detection: a rotated-away token was replayed — treat as a theft
        # signal and revoke this session immediately. There is no session-family
        # id; this single row *is* the chain, so revoking it ends the lineage.
        # Emit a WARNING so a genuine replay is visible in the logs (and
        # distinguishable from the benign double-refresh described below).
        #
        # Accepted tradeoff (plan §19, NFR-014): two browser tabs sharing one
        # cookie, or a double-fired refresh (two concurrent 401-retry paths
        # racing before the first refresh completes), can both present the same
        # now-superseded token and trip this branch, forcing a re-login.  For a
        # small team the incidence is low and the security guarantee (a replayed
        # stolen token ends the chain) outweighs the friction.  If this becomes
        # a problem the fix is to serialize refresh requests in the webapp with
        # an in-flight Promise deduplicator, or to introduce a short
        # prev_token_grace_window — neither is implemented in v1.
        log_event(
            "refresh_reuse_detected",
            level=logging.WARNING,
            session_id=row.id,
            user_id=row.user_id,
        )
        if row.revoked_at is None:
            row.revoked_at = naive_utcnow()
            await session.commit()
        raise AuthSessionError("refresh token reuse detected")
    if row.revoked_at is not None:
        raise AuthSessionError("session revoked")
    if row.expires_at <= naive_utcnow():
        raise AuthSessionError("session expired")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthSessionError("user inactive")
    new_raw = tokens.generate_refresh_token()
    now = naive_utcnow()
    row.prev_refresh_token_hash = row.refresh_token_hash
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

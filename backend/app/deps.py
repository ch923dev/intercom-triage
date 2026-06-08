"""FastAPI dependencies that read process-wide state off `app.state`.

The OpenRouter client and the resolved config are bound onto `app.state` in
the lifespan hook (see `main.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.intercom import IntercomClient
from app.clients.onlysales import OnlySalesClient
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.db import get_session
from app.models import Session as SessionRow
from app.security import tokens
from app.util import naive_utcnow


def get_app_config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.config
    return config


def get_openrouter(request: Request) -> OpenRouterClient | None:
    client: OpenRouterClient | None = getattr(request.app.state, "openrouter", None)
    return client


def get_intercom(request: Request) -> IntercomClient | None:
    client: IntercomClient | None = getattr(request.app.state, "intercom", None)
    return client


@dataclass(frozen=True)
class CurrentUser:
    id: int
    onlysales_id: str
    email: str
    scope: str | None


def get_onlysales(request: Request) -> OnlySalesClient:
    client: OnlySalesClient | None = getattr(request.app.state, "onlysales", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth backend not configured"
        )
    return client


def get_current_user(request: Request) -> CurrentUser:
    """Verify the Bearer access token offline. 401 on any failure. No DB hit.

    `is_active` is deliberately NOT re-checked here — that would cost a DB read
    per request and defeat the stateless-JWT design (invariant #16). A user
    deactivated mid-session therefore keeps a usable access token until it
    expires (<= session_access_ttl_seconds, ~30 min); hard revocation lands on
    the next /auth/refresh, which DOES reject an inactive user
    (services.auth.rotate_session)."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = header[7:].strip()
    secret: str = request.app.state.config.session_jwt_secret
    try:
        claims = tokens.verify_access_token(secret, token)
    except tokens.TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return CurrentUser(
        id=claims.user_id,
        onlysales_id=claims.onlysales_id,
        email=claims.email,
        scope=claims.scope,
    )


async def require_session_or_bearer(
    request: Request,
    session: AsyncSession = Depends(get_session),  # noqa: B008
    config: AppConfig = Depends(get_app_config),  # noqa: B008
) -> None:
    """Authorize a safe GET via Bearer access token OR the session cookie.

    Used only for <img>-loaded attachment bytes, which cannot send an
    Authorization header. Read-only routes only.
    """
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            tokens.verify_access_token(config.session_jwt_secret, header[7:].strip())
            return
        except tokens.TokenError:
            pass
    cookie = request.cookies.get(config.session_cookie_name)
    if cookie:
        row = await session.scalar(
            select(SessionRow).where(
                SessionRow.refresh_token_hash == tokens.hash_refresh_token(cookie)
            )
        )
        if row is not None and row.revoked_at is None and row.expires_at > naive_utcnow():
            return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="auth required",
        headers={"WWW-Authenticate": "Bearer"},
    )

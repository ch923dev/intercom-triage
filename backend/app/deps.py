"""FastAPI dependencies that read process-wide state off `app.state`.

The OpenRouter client and the resolved config are bound onto `app.state` in
the lifespan hook (see `main.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.clients.intercom import IntercomClient
from app.clients.onlysales import OnlySalesClient
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.security import tokens


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
    """Verify the Bearer access token offline. 401 on any failure. No DB hit."""
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

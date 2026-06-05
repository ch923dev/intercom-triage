"""Auth + users endpoints. Public: /auth/login, /auth/refresh. Spec §6."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.onlysales import OnlySalesAuthError, OnlySalesClient
from app.config import AppConfig
from app.db import get_session
from app.deps import CurrentUser, get_app_config, get_current_user, get_onlysales
from app.models import User
from app.schemas import LoginRequest, LoginResponse, MeResponse, UserOut, UserRef
from app.security.ratelimit import FixedWindowLimiter
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])

_ip_limiter: FixedWindowLimiter | None = None
_email_limiter: FixedWindowLimiter | None = None


def _limiters(config: AppConfig) -> tuple[FixedWindowLimiter, FixedWindowLimiter]:
    global _ip_limiter, _email_limiter
    if _ip_limiter is None or _email_limiter is None:
        _ip_limiter = FixedWindowLimiter(
            max_attempts=config.login_rate_max_attempts,
            window_seconds=config.login_rate_window_seconds,
        )
        _email_limiter = FixedWindowLimiter(
            max_attempts=config.login_rate_max_attempts,
            window_seconds=config.login_rate_window_seconds,
        )
    return _ip_limiter, _email_limiter


def _set_refresh_cookie(response: Response, config: AppConfig, value: str) -> None:
    response.set_cookie(
        key=config.session_cookie_name,
        value=value,
        max_age=config.session_refresh_ttl_seconds,
        httponly=True,
        secure=config.session_cookie_secure,
        samesite=config.session_cookie_samesite,  # type: ignore[arg-type]
        path="/",
    )


def _check_origin(request: Request, config: AppConfig) -> None:
    """CSRF defense for cookie-authenticated endpoints: Origin must be allowed."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in config.cors_allowed_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad origin")


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        onlysales_id=user.onlysales_id,
        email=user.email,
        name=user.name,
        scope=user.scope,
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    onlysales: OnlySalesClient = Depends(get_onlysales),
    config: AppConfig = Depends(get_app_config),
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    ip_limiter, email_limiter = _limiters(config)
    ip_ok = ip_limiter.allow(client_ip)
    email_ok = email_limiter.allow(body.email)
    if not (ip_ok and email_ok):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts"
        )
    try:
        identity = await onlysales.login(email=body.email, password=body.password)
    except OnlySalesAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    issued = await svc.complete_login(
        session,
        identity=identity,
        jwt_secret=config.session_jwt_secret,
        access_ttl=config.session_access_ttl_seconds,
        refresh_ttl=config.session_refresh_ttl_seconds,
        encryption_key=config.session_refresh_encryption_key,
        new_session_id=str(uuid.uuid4()),
    )
    _set_refresh_cookie(response, config, issued.refresh_cookie)
    return LoginResponse(access_token=issued.access_token, user=_user_out(issued.user))


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
) -> LoginResponse:
    _check_origin(request, config)
    cookie = request.cookies.get(config.session_cookie_name)
    if not cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no session")
    try:
        issued = await svc.rotate_session(
            session,
            raw_refresh=cookie,
            jwt_secret=config.session_jwt_secret,
            access_ttl=config.session_access_ttl_seconds,
            refresh_ttl=config.session_refresh_ttl_seconds,
        )
    except svc.AuthSessionError as exc:
        response.delete_cookie(config.session_cookie_name, path="/")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_refresh_cookie(response, config, issued.refresh_cookie)
    return LoginResponse(access_token=issued.access_token, user=_user_out(issued.user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    _check_origin(request, config)
    cookie = request.cookies.get(config.session_cookie_name)
    if cookie:
        await svc.revoke_by_refresh(session, raw_refresh=cookie)
    response.delete_cookie(config.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    await svc.revoke_all_for_user(session, user_id=user.id)
    response.delete_cookie(config.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
async def me(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> MeResponse:
    row = await session.get(User, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return MeResponse(user=_user_out(row))


users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("", response_model=list[UserRef])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(get_current_user),
) -> list[UserRef]:
    rows = (await session.scalars(select(User).where(User.is_active.is_(True)))).all()
    return [UserRef(id=r.id, name=r.name) for r in rows]

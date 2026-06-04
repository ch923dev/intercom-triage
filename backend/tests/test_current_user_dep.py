"""Phase 1 — get_current_user verifies the Bearer access token offline."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from app.config import AppConfig
from app.deps import CurrentUser, get_current_user
from app.security import tokens

SECRET = "dep-secret"


def _request_with(app: FastAPI, authorization: str | None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {"type": "http", "headers": headers, "app": app}
    return Request(scope)


def _app() -> FastAPI:
    app = FastAPI()
    app.state.config = AppConfig(session_jwt_secret=SECRET)
    return app


def test_returns_current_user_for_valid_token() -> None:
    app = _app()
    token = tokens.mint_access_token(
        SECRET,
        user_id=5,
        onlysales_id="oid",
        email="op@example.com",
        scope="admin",
        ttl_seconds=1800,
    )
    user = get_current_user(_request_with(app, f"Bearer {token}"))
    assert isinstance(user, CurrentUser)
    assert user.id == 5
    assert user.email == "op@example.com"
    assert user.scope == "admin"


def test_401_when_header_missing() -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with(_app(), None))
    assert exc.value.status_code == 401


def test_401_when_token_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with(_app(), "Bearer garbage"))
    assert exc.value.status_code == 401

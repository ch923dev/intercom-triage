"""Phase 1 — auth wire schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import LoginRequest, LoginResponse, UserOut


def test_login_request_lowercases_and_trims_email() -> None:
    req = LoginRequest(email="  OP@Example.COM ", password="pw")
    assert req.email == "op@example.com"


def test_login_request_requires_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="op@example.com", password="")


def test_login_response_shape() -> None:
    resp = LoginResponse(
        access_token="jwt",
        user=UserOut(id=1, onlysales_id="oid", email="op@example.com", name="Op", scope="admin"),
    )
    assert resp.access_token == "jwt"
    assert resp.user.email == "op@example.com"

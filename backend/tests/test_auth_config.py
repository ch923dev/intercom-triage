"""Phase 1 — auth config fields exist with the documented defaults."""

from __future__ import annotations

from app.config import AppConfig


def test_auth_defaults() -> None:
    cfg = AppConfig(session_jwt_secret="x")
    assert cfg.session_jwt_secret == "x"
    assert cfg.session_access_ttl_seconds == 1800
    assert cfg.session_refresh_ttl_seconds == 30 * 24 * 3600
    assert cfg.onlysales_auth_base == "https://pyapi.onlysales.io"
    assert cfg.session_cookie_name == "triage_refresh"
    assert cfg.session_cookie_secure is True
    assert cfg.session_cookie_samesite == "lax"
    assert cfg.login_rate_max_attempts == 10
    assert cfg.login_rate_window_seconds == 300
    assert cfg.cors_allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_session_secret_configured_property() -> None:
    assert AppConfig(session_jwt_secret="").session_secret_configured is False
    assert AppConfig(session_jwt_secret="abc").session_secret_configured is True

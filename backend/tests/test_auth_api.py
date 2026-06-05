"""Phase 1 — /auth/login + /auth/refresh + /auth/logout end-to-end."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.clients.onlysales import OnlySalesIdentity
from app.deps import get_current_user, get_onlysales


class FakeOnlySales:
    async def login(self, *, email: str, password: str) -> OnlySalesIdentity:
        if password != "good":
            from app.clients.onlysales import OnlySalesAuthError

            raise OnlySalesAuthError("Invalid credentials")
        return OnlySalesIdentity(
            access_token="os-access",
            refresh_token="os-refresh",
            onlysales_id="oid-1",
            email=email,
            name="Op E",
            scope="admin",
        )

    async def aclose(self) -> None:  # pragma: no cover
        pass


@pytest.fixture
def login_app(app: FastAPI) -> FastAPI:
    app.dependency_overrides.pop(get_current_user, None)
    app.state.onlysales = FakeOnlySales()
    app.dependency_overrides[get_onlysales] = lambda: app.state.onlysales
    return app


@pytest.mark.asyncio
async def test_login_sets_cookie_and_returns_access_token(login_app: FastAPI) -> None:
    transport = ASGITransport(app=login_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/auth/login", json={"email": "op@example.com", "password": "good"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"]
        assert body["user"]["email"] == "op@example.com"
        assert "triage_refresh" in resp.cookies

        token = body["access_token"]
        me = await ac.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["user"]["onlysales_id"] == "oid-1"


@pytest.mark.asyncio
async def test_login_rejects_bad_password(login_app: FastAPI) -> None:
    transport = ASGITransport(app=login_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/auth/login", json={"email": "op@example.com", "password": "bad"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limited_per_ip_across_emails(login_app: FastAPI) -> None:
    """Per-IP limiter trips even when the email changes each attempt.

    The old combined-key limiter keyed on f"{ip}:{email}", so each distinct
    email opened a fresh bucket and the per-IP cap was never enforced.  The new
    dual-limiter records the IP separately, so after login_rate_max_attempts
    (default 10) attempts from the same IP — regardless of which email —
    the 11th attempt must return 429.
    """
    import app.routers.auth as auth_router

    # Reset module-level limiter globals so this test starts from a clean slate
    # even if other tests already initialised them.
    auth_router._ip_limiter = None
    auth_router._email_limiter = None
    try:
        transport = ASGITransport(app=login_app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            # Fire 10 attempts — each with a DIFFERENT email so the old combined key
            # would never trip.  Bad password so OnlySales always returns 401.
            for i in range(10):
                r = await ac.post(
                    "/auth/login",
                    json={"email": f"user{i}@example.com", "password": "bad"},
                )
                assert r.status_code == 401, f"attempt {i}: expected 401, got {r.status_code}"

            # 11th attempt — per-IP window is now exhausted regardless of email.
            r = await ac.post(
                "/auth/login",
                json={"email": "new_email@example.com", "password": "bad"},
            )
            assert r.status_code == 429, f"expected 429 (per-IP rate limit), got {r.status_code}"
    finally:
        # Tear down so the exhausted buckets don't bleed into subsequent tests.
        auth_router._ip_limiter = None
        auth_router._email_limiter = None


@pytest.mark.asyncio
async def test_refresh_rotates_and_logout_revokes(login_app: FastAPI) -> None:
    transport = ASGITransport(app=login_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/auth/login", json={"email": "op@example.com", "password": "good"})
        assert login.status_code == 200

        refreshed = await ac.post("/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"]

        out = await ac.post("/auth/logout")
        assert out.status_code == 204

        again = await ac.post("/auth/refresh")
        assert again.status_code == 401

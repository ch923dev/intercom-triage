"""T19 — attachment image GETs accept a session cookie; mutations stay Bearer-only."""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import get_current_user, require_session_or_bearer
from app.models import Session as SessionRow
from app.models import User
from app.security import tokens
from app.util import naive_utcnow

# ── helpers ────────────────────────────────────────────────────────────────────


def _unauth_overrides_removed(app: FastAPI) -> None:
    """Strip BOTH auth overrides so the real dep logic runs (tests 401 paths)."""
    app.dependency_overrides.pop(get_current_user, None)
    app.dependency_overrides.pop(require_session_or_bearer, None)


# ── 401 without any auth ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_raw_thumb_401_without_any_auth(app: FastAPI) -> None:
    """No bearer, no cookie → 401 for both image-bytes routes."""
    _unauth_overrides_removed(app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        assert (await ac.get("/attachments/1/raw")).status_code == 401
        assert (await ac.get("/attachments/1/thumb")).status_code == 401


@pytest.mark.asyncio
async def test_upload_list_delete_401_without_bearer(app: FastAPI) -> None:
    """Mutations / list require a Bearer token; cookie alone is NOT accepted."""
    _unauth_overrides_removed(app)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        assert (await ac.get("/attachments", params={"ticket_id": "T1"})).status_code == 401
        assert (await ac.delete("/attachments/1")).status_code == 401
        resp = await ac.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("a.txt", b"hi", "text/plain")},
        )
        assert resp.status_code == 401


# ── cookie path: 404-not-401 proves auth passed ────────────────────────────────


@pytest.mark.asyncio
async def test_raw_accepts_valid_session_cookie_nonexistent_id(
    app: FastAPI, session: AsyncSession
) -> None:
    """A request with a valid session cookie for a nonexistent attachment id
    must NOT be 401 — the auth layer passes, and the service returns 404.
    A 404 (not 401) proves the cookie auth succeeded."""
    raw_cookie = "cookie-raw-token-nonexistent"
    user = User(onlysales_id="oid-img-ne", email="img-ne@test")
    session.add(user)
    await session.flush()
    now = naive_utcnow()
    session.add(
        SessionRow(
            id="img-sess-ne",
            user_id=user.id,
            refresh_token_hash=tokens.hash_refresh_token(raw_cookie),
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    # Remove the blanket override so the real require_session_or_bearer runs.
    app.dependency_overrides.pop(require_session_or_bearer, None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("triage_refresh", raw_cookie)
        resp = await ac.get("/attachments/99999/raw")
        # 404 (not 401) proves the cookie auth passed; the service just didn't
        # find the attachment.
        assert resp.status_code == 404, f"expected 404 from cookie auth, got {resp.status_code}"

        resp_thumb = await ac.get("/attachments/99999/thumb")
        assert (
            resp_thumb.status_code == 404
        ), f"expected 404 from cookie auth on thumb, got {resp_thumb.status_code}"


@pytest.mark.asyncio
async def test_raw_rejects_expired_session_cookie(app: FastAPI, session: AsyncSession) -> None:
    """An expired session cookie must be treated as no auth → 401."""
    raw_cookie = "cookie-expired-token"
    user = User(onlysales_id="oid-img-exp", email="img-exp@test")
    session.add(user)
    await session.flush()
    now = naive_utcnow()
    session.add(
        SessionRow(
            id="img-sess-exp",
            user_id=user.id,
            refresh_token_hash=tokens.hash_refresh_token(raw_cookie),
            issued_at=now - timedelta(hours=2),
            expires_at=now - timedelta(hours=1),  # already expired
        )
    )
    await session.commit()

    app.dependency_overrides.pop(require_session_or_bearer, None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("triage_refresh", raw_cookie)
        resp = await ac.get("/attachments/99999/raw")
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_raw_rejects_revoked_session_cookie(app: FastAPI, session: AsyncSession) -> None:
    """A revoked session cookie must be treated as no auth → 401."""
    raw_cookie = "cookie-revoked-token"
    user = User(onlysales_id="oid-img-rev", email="img-rev@test")
    session.add(user)
    await session.flush()
    now = naive_utcnow()
    session.add(
        SessionRow(
            id="img-sess-rev",
            user_id=user.id,
            refresh_token_hash=tokens.hash_refresh_token(raw_cookie),
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            revoked_at=now,  # already revoked
        )
    )
    await session.commit()

    app.dependency_overrides.pop(require_session_or_bearer, None)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("triage_refresh", raw_cookie)
        resp = await ac.get("/attachments/99999/raw")
        assert resp.status_code == 401


# ── full round-trip: upload via authed client, fetch raw via cookie ─────────────


@pytest.mark.asyncio
async def test_raw_accepts_valid_session_cookie_real_attachment(
    app: FastAPI, session: AsyncSession
) -> None:
    """Upload an attachment via the authed client (Bearer override in place),
    then fetch the raw bytes using ONLY the session cookie — no Bearer header.
    Must return 200."""
    raw_cookie = "cookie-raw-token-real"
    user = User(onlysales_id="oid-img-real", email="img-real@test")
    session.add(user)
    await session.flush()
    now = naive_utcnow()
    session.add(
        SessionRow(
            id="img-sess-real",
            user_id=user.id,
            refresh_token_hash=tokens.hash_refresh_token(raw_cookie),
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    transport = ASGITransport(app=app)

    # 1. Upload via the authed client (get_current_user override still active).
    async with AsyncClient(transport=transport, base_url="http://test") as authed:
        up = await authed.post(
            "/attachments",
            data={"owner_kind": "ticket", "owner_id": "T1", "ticket_id": "T1"},
            files={"file": ("hello.txt", b"hello cookie", "text/plain")},
        )
        assert up.status_code == 200
        attachment_id = up.json()["id"]

    # 2. Remove the require_session_or_bearer override so the real dep runs.
    app.dependency_overrides.pop(require_session_or_bearer, None)

    # 3. Fetch raw using only the session cookie (no Bearer header).
    async with AsyncClient(transport=transport, base_url="http://test") as cookie_client:
        cookie_client.cookies.set("triage_refresh", raw_cookie)
        resp = await cookie_client.get(f"/attachments/{attachment_id}/raw")
        assert resp.status_code == 200
        assert resp.content == b"hello cookie"


@pytest.mark.asyncio
async def test_list_rejects_cookie_only(app: FastAPI, session: AsyncSession) -> None:
    """The list route requires a Bearer token; a valid session cookie is NOT
    sufficient (cookie-only auth is intentionally restricted to raw/thumb)."""
    raw_cookie = "cookie-list-test-token"
    user = User(onlysales_id="oid-list-test", email="list-test@test")
    session.add(user)
    await session.flush()
    now = naive_utcnow()
    session.add(
        SessionRow(
            id="list-test-sess",
            user_id=user.id,
            refresh_token_hash=tokens.hash_refresh_token(raw_cookie),
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
    )
    await session.commit()

    # Remove BOTH overrides — the list route uses get_current_user (Bearer-only).
    _unauth_overrides_removed(app)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.cookies.set("triage_refresh", raw_cookie)
        resp = await ac.get("/attachments", params={"ticket_id": "T1"})
        assert resp.status_code == 401

"""Phase 1 — users + sessions tables exist and round-trip."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session as SessionRow
from app.models import User
from app.util import naive_utcnow


@pytest.mark.asyncio
async def test_user_and_session_roundtrip(session) -> None:
    user = User(
        onlysales_id="oid-1",
        email="op@example.com",
        name="Op Erator",
        scope="admin",
    )
    session.add(user)
    await session.flush()

    sess = SessionRow(
        id="sess-1",
        user_id=user.id,
        refresh_token_hash="deadbeef",
        onlysales_refresh_encrypted=None,
        issued_at=naive_utcnow(),
        expires_at=naive_utcnow(),
    )
    session.add(sess)
    await session.commit()

    got = await session.scalar(select(User).where(User.onlysales_id == "oid-1"))
    assert got is not None
    assert got.email == "op@example.com"
    assert got.is_active is True

    got_sess = await session.get(SessionRow, "sess-1")
    assert got_sess is not None
    assert got_sess.user_id == user.id
    assert got_sess.revoked_at is None


@pytest.mark.asyncio
async def test_session_stores_prev_refresh_hash(session) -> None:
    user = User(onlysales_id="oid-x", email="x@x")
    session.add(user)
    await session.flush()
    row = SessionRow(
        id="sess-1",
        user_id=user.id,
        refresh_token_hash="h2",
        prev_refresh_token_hash="h1",
        issued_at=naive_utcnow(),
        expires_at=naive_utcnow(),
        last_used_at=naive_utcnow(),
    )
    session.add(row)
    await session.flush()
    got = await session.get(SessionRow, "sess-1")
    assert got is not None and got.prev_refresh_token_hash == "h1"

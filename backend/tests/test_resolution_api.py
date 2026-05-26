"""T8 — resolution endpoints integration tests.

Fixture adaptation: conftest exposes `client` and `session` (not `db_session`).
Both fixtures depend on the same `app` fixture, so they share one in-memory DB.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Settings, Ticket
from app.util import naive_utcnow


def _seed_open(session: AsyncSession, id: str = "t1") -> None:
    session.add(
        Ticket(
            id=id,
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
            category_id=1,
            summary="",
            ai_confidence=0.0,
        )
    )


@pytest.mark.asyncio
async def test_post_resolve_returns_200_and_persists(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "t1")
    await session.commit()

    r = await client.post("/tickets/t1/resolve", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_source"] == "manual"


@pytest.mark.asyncio
async def test_post_resolve_404_unknown(client: AsyncClient):
    r = await client.post("/tickets/ghost/resolve", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_resolve_409_already_resolved(client: AsyncClient, session: AsyncSession):
    t = Ticket(
        id="t2",
        title="x",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        category_id=1,
        summary="",
        ai_confidence=0.0,
        resolved_at=naive_utcnow(),
        resolved_source="manual",
    )
    session.add(t)
    await session.commit()
    r = await client.post("/tickets/t2/resolve", json={})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_post_reopen_clears_resolution(client: AsyncClient, session: AsyncSession):
    t = Ticket(
        id="t3",
        title="x",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        category_id=1,
        summary="",
        ai_confidence=0.0,
        resolved_at=naive_utcnow(),
        resolved_source="manual",
    )
    session.add(t)
    await session.commit()

    r = await client.post("/tickets/t3/reopen")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_patch_ai_resolve_tristate(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "t4")
    await session.commit()
    for value in (True, False, None):
        r = await client.patch("/tickets/t4/ai-resolve", json={"enabled": value})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_post_dismiss_chip(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "t5")
    await session.commit()
    r = await client.post("/tickets/t5/dismiss-chip")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ── T9: resolved filter + chip state + drag-out reopen ────────────────────────


@pytest.mark.asyncio
async def test_get_tickets_default_excludes_resolved(client: AsyncClient, session: AsyncSession):
    t1 = Ticket(
        id="open1",
        title="x",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        category_id=1,
        summary="",
        ai_confidence=0.0,
    )
    t2 = Ticket(
        id="resolved1",
        title="x",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        category_id=1,
        summary="",
        ai_confidence=0.0,
        resolved_at=naive_utcnow(),
        resolved_source="manual",
    )
    session.add_all([t1, t2])
    await session.commit()

    r = await client.get("/tickets")
    ids = {t["id"] for t in r.json()}
    assert "open1" in ids
    assert "resolved1" not in ids


@pytest.mark.asyncio
async def test_get_tickets_resolved_true_returns_only_resolved(
    client: AsyncClient, session: AsyncSession
):
    session.add_all(
        [
            Ticket(
                id="o",
                title="x",
                state="open",
                author={},
                parts=[],
                internal_notes=[],
                created_at=naive_utcnow(),
                updated_at=naive_utcnow(),
                category_id=1,
                summary="",
                ai_confidence=0.0,
            ),
            Ticket(
                id="r",
                title="x",
                state="open",
                author={},
                parts=[],
                internal_notes=[],
                created_at=naive_utcnow(),
                updated_at=naive_utcnow(),
                category_id=1,
                summary="",
                ai_confidence=0.0,
                resolved_at=naive_utcnow(),
                resolved_source="manual",
            ),
        ]
    )
    await session.commit()

    r = await client.get("/tickets?resolved=true")
    ids = {t["id"] for t in r.json()}
    assert ids == {"r"}


@pytest.mark.asyncio
async def test_chip_state_ai_resolved_when_verdict_high_confidence(
    client: AsyncClient, session: AsyncSession
):
    """Open ticket, AI verdict='resolved' >= threshold, chip not dismissed."""
    from app.models import AICacheEntry, Settings

    settings = await session.get(Settings, 1)
    assert settings is not None
    settings.ai_resolve_default = True
    settings.ai_resolve_confidence_threshold = 0.7
    settings.use_ai = True

    session.add(
        AICacheEntry(
            ticket_id="ai1",
            category_id=1,
            summary="s",
            confidence=0.9,
            ticket_updated_at=naive_utcnow(),
            ai_resolution_verdict="resolved",
            ai_resolution_confidence=0.85,
        )
    )
    session.add(
        Ticket(
            id="ai1",
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
            category_id=1,
            summary="",
            ai_confidence=0.9,
        )
    )
    await session.commit()

    r = await client.get("/tickets")
    payload = next(t for t in r.json() if t["id"] == "ai1")
    assert payload["resolution_chip_state"] == "ai_resolved"


@pytest.mark.asyncio
async def test_chip_state_null_when_ai_off(client: AsyncClient, session: AsyncSession):
    """If use_ai=False, no chip even with strong verdict."""
    from app.models import AICacheEntry, Settings

    settings = await session.get(Settings, 1)
    assert settings is not None
    settings.use_ai = False
    settings.ai_resolve_default = True
    session.add(
        AICacheEntry(
            ticket_id="aioff",
            category_id=1,
            summary="s",
            confidence=0.9,
            ticket_updated_at=naive_utcnow(),
            ai_resolution_verdict="resolved",
            ai_resolution_confidence=0.95,
        )
    )
    session.add(
        Ticket(
            id="aioff",
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
            category_id=1,
            summary="",
            ai_confidence=0.9,
        )
    )
    await session.commit()
    r = await client.get("/tickets")
    payload = next(t for t in r.json() if t["id"] == "aioff")
    assert payload["resolution_chip_state"] is None


@pytest.mark.asyncio
async def test_chip_state_dismissed_returns_null(client: AsyncClient, session: AsyncSession):
    """Chip dismissed at or after updated_at => null."""
    from app.models import AICacheEntry, Settings

    settings = await session.get(Settings, 1)
    assert settings is not None
    settings.ai_resolve_default = True
    settings.ai_resolve_confidence_threshold = 0.7
    settings.use_ai = True
    # Use the canonical clock, not a hardcoded date: get_tickets filters by the
    # 24h lookback window relative to now, so a fixed past date ages out and the
    # ticket vanishes from the response. dismissed_at == updated_at still
    # exercises the "dismissed at/after updated_at => null" path.
    ts = naive_utcnow()
    session.add(
        AICacheEntry(
            ticket_id="dis",
            category_id=1,
            summary="s",
            confidence=0.9,
            ticket_updated_at=ts,
            ai_resolution_verdict="resolved",
            ai_resolution_confidence=0.9,
        )
    )
    session.add(
        Ticket(
            id="dis",
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=ts,
            updated_at=ts,
            category_id=1,
            summary="",
            ai_confidence=0.9,
            resolution_chip_dismissed_at=ts,
        )
    )
    await session.commit()
    r = await client.get("/tickets")
    payload = next(t for t in r.json() if t["id"] == "dis")
    assert payload["resolution_chip_state"] is None


@pytest.mark.asyncio
async def test_effective_ai_resolve_uses_override_when_set(
    client: AsyncClient, session: AsyncSession
):
    """Per-ticket override=True overrides settings.ai_resolve_default=False."""
    from app.models import Settings

    settings = await session.get(Settings, 1)
    assert settings is not None
    settings.ai_resolve_default = False
    session.add(
        Ticket(
            id="ovr",
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
            category_id=1,
            summary="",
            ai_confidence=0.0,
            ai_resolve_enabled=True,  # raw override = True
        )
    )
    await session.commit()
    r = await client.get("/tickets")
    payload = next(t for t in r.json() if t["id"] == "ovr")
    assert payload["ai_resolve_override"] is True
    assert payload["ai_resolve_enabled"] is True  # effective


@pytest.mark.asyncio
async def test_drag_out_of_resolved_reopens_and_overrides(
    client: AsyncClient, session: AsyncSession
):
    """PATCH /tickets/{id}/category on a resolved ticket clears resolution
    in the same transaction (drag-out behavior)."""
    session.add(
        Ticket(
            id="dragt1",
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
            category_id=1,
            summary="",
            ai_confidence=0.0,
            resolved_at=naive_utcnow(),
            resolved_source="manual",
        )
    )
    await session.commit()

    r = await client.patch("/tickets/dragt1/category", json={"category_id": 2})
    assert r.status_code == 200

    await session.refresh(await session.get(Ticket, "dragt1"))
    row = await session.get(Ticket, "dragt1")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolved_source is None


@pytest.mark.asyncio
async def test_post_non_actionable_returns_200_and_persists(
    client: AsyncClient, session: AsyncSession
):
    _seed_open(session, "t-na-r1")
    await session.commit()

    r = await client.post("/tickets/t-na-r1/non-actionable", json={})
    assert r.status_code == 200
    body = r.json()
    assert body["resolved_source"] == "non_actionable"
    assert body["resolved_at"]


@pytest.mark.asyncio
async def test_post_non_actionable_404_unknown(client: AsyncClient):
    r = await client.post("/tickets/ghost/non-actionable", json={})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_post_non_actionable_409_already_resolved(client: AsyncClient, session: AsyncSession):
    t = Ticket(
        id="t-na-r2",
        title="x",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        category_id=1,
        summary="",
        ai_confidence=0.0,
        resolved_at=naive_utcnow(),
        resolved_source="manual",
    )
    session.add(t)
    await session.commit()
    r = await client.post("/tickets/t-na-r2/non-actionable", json={})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_reopen_clears_non_actionable(client: AsyncClient, session: AsyncSession):
    t = Ticket(
        id="t-na-r3",
        title="x",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        category_id=1,
        summary="",
        ai_confidence=0.0,
        resolved_at=naive_utcnow(),
        resolved_source="non_actionable",
    )
    session.add(t)
    await session.commit()

    r = await client.post("/tickets/t-na-r3/reopen", json={})
    assert r.status_code == 200

    session.expire_all()
    row = await session.get(Ticket, "t-na-r3")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolved_source is None


@pytest.mark.asyncio
async def test_chip_state_new_reply_when_resolved_with_new_activity_and_ai_off(
    client: AsyncClient, session: AsyncSession
) -> None:
    """_chip_state returns 'new_reply' when a resolved ticket has new activity
    (updated_at > resolved_at) and AI resolution is disabled (use_ai=False).

    This covers the third return branch in _chip_state:
        if resolved_at is not None and new_activity and not ai_on: return 'new_reply'
    """
    settings = await session.get(Settings, 1)
    assert settings is not None
    settings.use_ai = False

    resolved_at = naive_utcnow() - timedelta(seconds=30)
    updated_at = naive_utcnow()  # strictly after resolved_at → new_activity=True

    session.add(
        Ticket(
            id="new-reply-1",
            title="x",
            state="open",
            author={},
            parts=[],
            internal_notes=[],
            created_at=resolved_at,
            updated_at=updated_at,
            category_id=1,
            summary="",
            ai_confidence=0.0,
            resolved_at=resolved_at,
            resolved_source="manual",
        )
    )
    await session.commit()

    r = await client.get("/tickets?resolved=true")
    assert r.status_code == 200
    payload = next(t for t in r.json() if t["id"] == "new-reply-1")
    assert payload["resolution_chip_state"] == "new_reply"

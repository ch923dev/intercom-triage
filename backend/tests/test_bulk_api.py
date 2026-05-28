"""Endpoint-level tests for the bulk-action surface.

Tasks: T075 (resolve / reopen), T076 (recategorize), T077 (dismiss-chip),
T078 (follow-up set / clear). Each bulk endpoint returns `BulkResult` —
200 with mixed `ok_ids` + `failed[]` even when every per-id call failed.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import MAX_BULK_IDS
from app.models import Ticket
from app.util import naive_utcnow


def _seed_open(session: AsyncSession, ticket_id: str) -> None:
    session.add(
        Ticket(
            id=ticket_id,
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


def _seed_resolved(session: AsyncSession, ticket_id: str) -> None:
    session.add(
        Ticket(
            id=ticket_id,
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


# ── /tickets/bulk/resolve ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_resolve_happy_path(client: AsyncClient, session: AsyncSession) -> None:
    for tid in ("t1", "t2", "t3"):
        _seed_open(session, tid)
    await session.commit()

    r = await client.post("/tickets/bulk/resolve", json={"ticket_ids": ["t1", "t2", "t3"]})
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"t1", "t2", "t3"}
    assert body["failed"] == []

    for tid in ("t1", "t2", "t3"):
        row = await session.get(Ticket, tid)
        assert row is not None
        assert row.resolved_at is not None
        assert row.resolved_source == "manual"


@pytest.mark.asyncio
async def test_bulk_resolve_partial_failure(client: AsyncClient, session: AsyncSession) -> None:
    _seed_open(session, "ok1")
    _seed_open(session, "ok2")
    _seed_resolved(session, "already")  # 409 path
    await session.commit()

    r = await client.post(
        "/tickets/bulk/resolve",
        json={"ticket_ids": ["ok1", "ok2", "already"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"ok1", "ok2"}
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == "already"


@pytest.mark.asyncio
async def test_bulk_resolve_unknown_id_in_failed(
    client: AsyncClient, session: AsyncSession
) -> None:
    _seed_open(session, "real")
    await session.commit()

    r = await client.post("/tickets/bulk/resolve", json={"ticket_ids": ["real", "ghost"]})
    assert r.status_code == 200
    body = r.json()
    assert body["ok_ids"] == ["real"]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == "ghost"


@pytest.mark.asyncio
async def test_bulk_resolve_deduplicates_ids(client: AsyncClient, session: AsyncSession) -> None:
    _seed_open(session, "dup")
    await session.commit()

    r = await client.post(
        "/tickets/bulk/resolve",
        json={"ticket_ids": ["dup", "dup", "dup"]},
    )
    assert r.status_code == 200
    body = r.json()
    # Duplicate ids processed exactly once.
    assert body["ok_ids"] == ["dup"]
    assert body["failed"] == []


@pytest.mark.asyncio
async def test_bulk_resolve_empty_array_422(client: AsyncClient) -> None:
    r = await client.post("/tickets/bulk/resolve", json={"ticket_ids": []})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_resolve_over_cap_422(client: AsyncClient) -> None:
    ids = [f"t{i}" for i in range(MAX_BULK_IDS + 1)]
    r = await client.post("/tickets/bulk/resolve", json={"ticket_ids": ids})
    assert r.status_code == 422


# ── /tickets/bulk/reopen ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_reopen_happy_path(client: AsyncClient, session: AsyncSession) -> None:
    for tid in ("r1", "r2"):
        _seed_resolved(session, tid)
    await session.commit()

    r = await client.post("/tickets/bulk/reopen", json={"ticket_ids": ["r1", "r2"]})
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"r1", "r2"}
    assert body["failed"] == []

    for tid in ("r1", "r2"):
        row = await session.get(Ticket, tid)
        assert row is not None
        assert row.resolved_at is None
        assert row.resolved_source is None


@pytest.mark.asyncio
async def test_bulk_reopen_409_on_open_ticket(client: AsyncClient, session: AsyncSession) -> None:
    _seed_resolved(session, "wasResolved")
    _seed_open(session, "neverWas")
    await session.commit()

    r = await client.post(
        "/tickets/bulk/reopen",
        json={"ticket_ids": ["wasResolved", "neverWas"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok_ids"] == ["wasResolved"]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == "neverWas"


# ── /tickets/bulk/category ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_recategorize_happy_path(client: AsyncClient, session: AsyncSession) -> None:
    from app.models import Override

    for tid in ("c1", "c2", "c3"):
        _seed_open(session, tid)
    await session.commit()

    r = await client.patch(
        "/tickets/bulk/category",
        json={"ticket_ids": ["c1", "c2", "c3"], "category_id": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"c1", "c2", "c3"}
    assert body["failed"] == []

    for tid in ("c1", "c2", "c3"):
        ov = await session.get(Override, tid)
        assert ov is not None
        assert ov.category_id == 2


@pytest.mark.asyncio
async def test_bulk_recategorize_unknown_ticket_404(
    client: AsyncClient, session: AsyncSession
) -> None:
    _seed_open(session, "real")
    await session.commit()

    r = await client.patch(
        "/tickets/bulk/category",
        json={"ticket_ids": ["real", "ghost"], "category_id": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok_ids"] == ["real"]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == "ghost"


@pytest.mark.asyncio
async def test_bulk_recategorize_unknown_category_422(
    client: AsyncClient, session: AsyncSession
) -> None:
    _seed_open(session, "real")
    await session.commit()

    r = await client.patch(
        "/tickets/bulk/category",
        json={"ticket_ids": ["real"], "category_id": 9999},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_recategorize_clears_resolution(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Dragging a resolved ticket into a category column reopens it (drag-out)."""
    _seed_resolved(session, "drag1")
    await session.commit()

    r = await client.patch(
        "/tickets/bulk/category",
        json={"ticket_ids": ["drag1"], "category_id": 2},
    )
    assert r.status_code == 200

    row = await session.get(Ticket, "drag1")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolved_source is None


# ── /tickets/bulk/dismiss-chip ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_dismiss_chip_stamps_updated_at(
    client: AsyncClient, session: AsyncSession
) -> None:
    for tid in ("d1", "d2", "d3"):
        _seed_open(session, tid)
    await session.commit()

    r = await client.post(
        "/tickets/bulk/dismiss-chip",
        json={"ticket_ids": ["d1", "d2", "d3"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"d1", "d2", "d3"}
    assert body["failed"] == []

    for tid in ("d1", "d2", "d3"):
        row = await session.get(Ticket, tid)
        assert row is not None
        assert row.resolution_chip_dismissed_at == row.updated_at


@pytest.mark.asyncio
async def test_bulk_dismiss_chip_unknown_id_in_failed(
    client: AsyncClient, session: AsyncSession
) -> None:
    _seed_open(session, "d1")
    await session.commit()

    r = await client.post(
        "/tickets/bulk/dismiss-chip",
        json={"ticket_ids": ["d1", "ghost"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok_ids"] == ["d1"]
    assert len(body["failed"]) == 1
    assert body["failed"][0]["id"] == "ghost"


# ── /followups/bulk ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_set_followup_inserts_rows(client: AsyncClient, session: AsyncSession) -> None:
    from app.models import Followup

    r = await client.put(
        "/followups/bulk",
        json={
            "ticket_ids": ["f1", "f2", "f3", "f4"],
            "due_at": "2026-06-01T12:00:00Z",
            "reason": "check in",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"f1", "f2", "f3", "f4"}
    assert body["failed"] == []

    for tid in ("f1", "f2", "f3", "f4"):
        row = await session.get(Followup, tid)
        assert row is not None
        assert row.reason == "check in"
        assert row.fired is False


@pytest.mark.asyncio
async def test_bulk_set_followup_upserts_existing(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Re-setting on an id with an existing follow-up overwrites in place."""
    from app.models import Followup

    r1 = await client.put(
        "/followups/bulk",
        json={
            "ticket_ids": ["upd1"],
            "due_at": "2026-06-01T12:00:00Z",
            "reason": "first",
        },
    )
    assert r1.status_code == 200

    r2 = await client.put(
        "/followups/bulk",
        json={
            "ticket_ids": ["upd1"],
            "due_at": "2026-07-15T09:00:00Z",
            "reason": "second",
        },
    )
    assert r2.status_code == 200
    await session.commit()
    row = await session.get(Followup, "upd1")
    assert row is not None
    await session.refresh(row)
    assert row.reason == "second"


@pytest.mark.asyncio
async def test_bulk_set_followup_rejects_reason_over_80(client: AsyncClient) -> None:
    r = await client.put(
        "/followups/bulk",
        json={
            "ticket_ids": ["any"],
            "due_at": "2026-06-01T12:00:00Z",
            "reason": "x" * 81,
        },
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_clear_followup_deletes_rows(client: AsyncClient, session: AsyncSession) -> None:
    from app.models import Followup

    await client.put(
        "/followups/bulk",
        json={
            "ticket_ids": ["c1", "c2", "c3"],
            "due_at": "2026-06-01T12:00:00Z",
            "reason": None,
        },
    )

    r = await client.request(
        "DELETE",
        "/followups/bulk",
        json={"ticket_ids": ["c1", "c2", "c3"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"c1", "c2", "c3"}
    assert body["failed"] == []

    for tid in ("c1", "c2", "c3"):
        assert await session.get(Followup, tid) is None


@pytest.mark.asyncio
async def test_bulk_clear_followup_idempotent(client: AsyncClient) -> None:
    """Ids without a follow-up still land in ok_ids — matches single-id DELETE."""
    r = await client.request(
        "DELETE",
        "/followups/bulk",
        json={"ticket_ids": ["nope1", "nope2"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"nope1", "nope2"}
    assert body["failed"] == []


# ── /metrics — bulk counters (T084) ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_action_increments_metrics(client: AsyncClient, session: AsyncSession) -> None:
    from app.metrics import metrics

    metrics.reset()
    for tid in ("m1", "m2", "m3"):
        _seed_open(session, tid)
    _seed_resolved(session, "already")
    await session.commit()

    r = await client.post(
        "/tickets/bulk/resolve",
        json={"ticket_ids": ["m1", "m2", "m3", "already"]},
    )
    assert r.status_code == 200

    counters = metrics.snapshot()
    # Partial outcome — 3 ok, 1 failed.
    assert counters.get("bulk_actions_total.resolve.partial", 0) == 1
    assert counters.get("bulk_action_ids_total.resolve", 0) == 3


@pytest.mark.asyncio
async def test_bulk_action_all_ok_outcome(client: AsyncClient, session: AsyncSession) -> None:
    from app.metrics import metrics

    metrics.reset()
    for tid in ("ok1", "ok2"):
        _seed_open(session, tid)
    await session.commit()

    await client.post("/tickets/bulk/resolve", json={"ticket_ids": ["ok1", "ok2"]})

    counters = metrics.snapshot()
    assert counters.get("bulk_actions_total.resolve.ok", 0) == 1
    assert counters.get("bulk_action_ids_total.resolve", 0) == 2


@pytest.mark.asyncio
async def test_bulk_action_all_fail_outcome(client: AsyncClient) -> None:
    from app.metrics import metrics

    metrics.reset()
    # No seeded tickets — every id is unknown.
    r = await client.post(
        "/tickets/bulk/resolve",
        json={"ticket_ids": ["ghost1", "ghost2"]},
    )
    assert r.status_code == 200

    counters = metrics.snapshot()
    assert counters.get("bulk_actions_total.resolve.fail", 0) == 1
    assert counters.get("bulk_action_ids_total.resolve", 0) == 0


# ── /tickets/bulk/non-actionable ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_non_actionable_happy(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "b-na-1")
    _seed_open(session, "b-na-2")
    _seed_open(session, "b-na-3")
    await session.commit()

    r = await client.post(
        "/tickets/bulk/non-actionable",
        json={"ticket_ids": ["b-na-1", "b-na-2", "b-na-3"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body["ok_ids"]) == {"b-na-1", "b-na-2", "b-na-3"}
    assert body["failed"] == []


@pytest.mark.asyncio
async def test_bulk_non_actionable_partial(client: AsyncClient, session: AsyncSession):
    _seed_open(session, "b-na-4")
    t = Ticket(
        id="b-na-5",
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

    r = await client.post(
        "/tickets/bulk/non-actionable",
        json={"ticket_ids": ["b-na-4", "b-na-5"]},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok_ids"] == ["b-na-4"]
    assert [f["id"] for f in body["failed"]] == ["b-na-5"]


@pytest.mark.asyncio
async def test_bulk_non_actionable_cap_exceeded(client: AsyncClient):
    r = await client.post(
        "/tickets/bulk/non-actionable",
        json={"ticket_ids": [f"x{i}" for i in range(201)]},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_non_actionable_empty(client: AsyncClient):
    r = await client.post("/tickets/bulk/non-actionable", json={"ticket_ids": []})
    assert r.status_code == 422


# ── T107 regression: bulk recategorize clears non_actionable_kind ─────────────


@pytest.mark.asyncio
async def test_bulk_recategorize_clears_non_actionable_kind(
    client: AsyncClient, session: AsyncSession
) -> None:
    """Bulk recategorize a non_actionable ticket must null non_actionable_kind.

    Regression for T107: the inline reopen in bulk_recategorize previously
    cleared resolved_at/resolved_source but not non_actionable_kind, violating
    the tickets_non_actionable_kind_check constraint → IntegrityError on commit.
    """
    session.add(
        Ticket(
            id="na-kind-1",
            title="auto reply",
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
            non_actionable_kind="spam",
        )
    )
    await session.commit()

    r = await client.patch(
        "/tickets/bulk/category",
        json={"ticket_ids": ["na-kind-1"], "category_id": 2},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok_ids"] == ["na-kind-1"], f"expected ok, got: {body}"
    assert body["failed"] == []

    from app.models import Override

    session.expire_all()
    row = await session.get(Ticket, "na-kind-1")
    assert row is not None
    assert row.resolved_at is None
    assert row.resolved_source is None
    assert row.non_actionable_kind is None
    ov = await session.get(Override, "na-kind-1")
    assert ov is not None
    assert ov.category_id == 2

"""Stats dashboard rollups (roadmap 1.3).

Seeds a handful of tickets directly into the in-memory DB and asserts the four
success metrics: category breakdown, volume trend, resolution mix
(`resolved_source`, invariant #10), and time-to-resolve buckets.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.models import Override, Ticket
from app.services import stats as svc
from app.util import naive_utcnow


def _ticket(
    tid: str,
    *,
    category_id: int | None,
    created_offset_days: float = 0.0,
    resolved_source: str | None = None,
    resolved_offset_hours: float | None = None,
    first_part_offset_hours: float = 0.0,
) -> Ticket:
    """Build a ticket relative to `now`. `created_offset_days` is days BEFORE
    now. The single customer part is `first_part_offset_hours` after creation;
    `resolved_offset_hours` (if set) is measured from creation too."""
    created = naive_utcnow() - timedelta(days=created_offset_days)
    first_part = created + timedelta(hours=first_part_offset_hours)
    resolved_at = None
    if resolved_offset_hours is not None:
        resolved_at = created + timedelta(hours=resolved_offset_hours)
    return Ticket(
        id=tid,
        title="t",
        state="open" if resolved_source is None else "closed",
        author={},
        parts=[
            {
                "author": {"id": "u1", "name": "C", "type": "user"},
                "body": "hi",
                "created_at": first_part.isoformat() + "Z",
                "is_admin": False,
            }
        ],
        internal_notes=[],
        created_at=created,
        updated_at=created,
        category_id=category_id,
        summary="",
        ai_confidence=0.0,
        resolved_at=resolved_at,
        resolved_source=resolved_source,
    )


@pytest.mark.asyncio
async def test_category_breakdown_counts_effective_category(session):
    # Two tickets in cat 1, one in cat 2.
    session.add(_ticket("a", category_id=1))
    session.add(_ticket("b", category_id=1))
    session.add(_ticket("c", category_id=2))
    await session.commit()

    out = await svc.get_stats(session, window_days=30)

    assert out.total_tickets == 3
    by_id = {c.category_id: c.count for c in out.category_breakdown}
    assert by_id[1] == 2
    assert by_id[2] == 1


@pytest.mark.asyncio
async def test_category_breakdown_override_beats_ai_category(session):
    # AI says cat 1, operator override says cat 2 → effective is cat 2.
    # `set_at` is stamped explicitly to mirror production (set_override /
    # bulk both pass naive_utcnow()); the server_default CURRENT_TIMESTAMP is
    # seconds-precision and would look stale next to the ticket's microsecond
    # updated_at from the same instant.
    session.add(_ticket("a", category_id=1))
    await session.commit()
    session.add(Override(ticket_id="a", category_id=2, set_at=naive_utcnow()))
    await session.commit()

    out = await svc.get_stats(session, window_days=30)
    by_id = {c.category_id: c.count for c in out.category_breakdown}
    assert by_id == {2: 1}


@pytest.mark.asyncio
async def test_category_breakdown_stale_override_loses_to_ai(session):
    # Override set BEFORE the ticket's last update → stale → AI category wins,
    # matching the board / playbooks / clusters rule (invariant #11). The bare
    # SQL coalesce ignored the timestamp and miscounted this under the override.
    session.add(_ticket("a", category_id=1))
    await session.commit()
    stale = naive_utcnow() - timedelta(hours=1)
    session.add(Override(ticket_id="a", category_id=2, set_at=stale))
    await session.commit()

    out = await svc.get_stats(session, window_days=30)
    by_id = {c.category_id: c.count for c in out.category_breakdown}
    assert by_id == {1: 1}


@pytest.mark.asyncio
async def test_resolution_mix_keys_on_resolved_source(session):
    session.add(_ticket("open1", category_id=1))
    session.add(_ticket("m1", category_id=1, resolved_source="manual", resolved_offset_hours=2))
    session.add(
        _ticket("ic1", category_id=1, resolved_source="intercom_closed", resolved_offset_hours=5)
    )
    session.add(
        _ticket("na1", category_id=1, resolved_source="non_actionable", resolved_offset_hours=1)
    )
    session.add(
        _ticket("ai1", category_id=1, resolved_source="ai_resolved", resolved_offset_hours=3)
    )
    await session.commit()

    out = await svc.get_stats(session, window_days=30)
    mix = out.resolution_mix
    assert mix.open == 1
    assert mix.manual == 1
    assert mix.intercom_closed == 1
    assert mix.non_actionable == 1
    assert mix.ai_resolved == 1


@pytest.mark.asyncio
async def test_volume_trend_gap_filled_and_dated(session):
    # One ticket today, one 3 days ago.
    session.add(_ticket("today", category_id=1, created_offset_days=0))
    session.add(_ticket("old", category_id=1, created_offset_days=3))
    await session.commit()

    out = await svc.get_stats(session, window_days=7)

    # Continuous daily points, no gaps.
    total_from_trend = sum(p.count for p in out.volume_trend)
    assert total_from_trend == 2
    # Every point has an ISO date and a non-negative count.
    assert all(len(p.date) == 10 and p.count >= 0 for p in out.volume_trend)
    # Most recent point is today.
    assert out.volume_trend[-1].date == naive_utcnow().date().isoformat()


@pytest.mark.asyncio
async def test_resolve_time_buckets_and_median(session):
    # Resolve times measured from the first customer part (offset 0h):
    #   30 min  → "< 1h"
    #   2 h     → "1–4h"
    #   10 h    → "4–24h"
    session.add(_ticket("fast", category_id=1, resolved_source="manual", resolved_offset_hours=0.5))
    session.add(_ticket("mid", category_id=1, resolved_source="manual", resolved_offset_hours=2.0))
    session.add(
        _ticket("slow", category_id=1, resolved_source="manual", resolved_offset_hours=10.0)
    )
    await session.commit()

    out = await svc.get_stats(session, window_days=30)
    by_label = {b.label: b.count for b in out.resolve_time_buckets}
    assert by_label["< 1h"] == 1
    assert by_label["1–4h"] == 1
    assert by_label["4–24h"] == 1
    # Median of {0.5, 2.0, 10.0} hours == 2.0.
    assert out.median_resolve_hours == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_resolve_time_uses_first_customer_message_not_created(session):
    # Created now; first customer part 4h after creation; resolved 5h after
    # creation → elapsed since first customer message is 1h, not 5h.
    session.add(
        _ticket(
            "t",
            category_id=1,
            resolved_source="manual",
            resolved_offset_hours=5.0,
            first_part_offset_hours=4.0,
        )
    )
    await session.commit()

    out = await svc.get_stats(session, window_days=30)
    by_label = {b.label: b.count for b in out.resolve_time_buckets}
    assert by_label["1–4h"] == 1
    assert by_label["4–24h"] == 0


@pytest.mark.asyncio
async def test_window_excludes_older_tickets(session):
    session.add(_ticket("inside", category_id=1, created_offset_days=2))
    session.add(_ticket("outside", category_id=1, created_offset_days=40))
    await session.commit()

    out = await svc.get_stats(session, window_days=30)
    assert out.total_tickets == 1
    assert {c.category_id for c in out.category_breakdown} == {1}


@pytest.mark.asyncio
async def test_stats_endpoint_smoke(client, session):
    session.add(_ticket("a", category_id=1, resolved_source="manual", resolved_offset_hours=2))
    await session.commit()

    resp = await client.get("/stats")
    assert resp.status_code == 200
    body = resp.json()
    assert body["window_days"] == 30
    assert body["total_tickets"] == 1
    assert body["resolution_mix"]["manual"] == 1
    assert len(body["resolve_time_buckets"]) == 6
    assert "median_resolve_hours" in body


@pytest.mark.asyncio
async def test_stats_endpoint_window_param(client):
    resp = await client.get("/stats", params={"window_days": 7})
    assert resp.status_code == 200
    assert resp.json()["window_days"] == 7

    bad = await client.get("/stats", params={"window_days": 0})
    assert bad.status_code == 422

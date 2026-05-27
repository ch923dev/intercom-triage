"""Cluster content-gap ranking (roadmap 3.2 — "what should I build a playbook for").

Exercises `app.services.clusters.rank_gaps` + the `GET /clusters/gaps` endpoint
directly over hand-built `ticket_clusters` / `ticket_cluster_members` rows so the
ranking logic is asserted in isolation from the clustering job. The autouse
`fake_encoder` fixture keeps everything offline.

Covers:
- A cluster whose dominant category HAS an active playbook is excluded.
- A cluster whose dominant category has NO playbook is included + ranked by size.
- Effective category respects a manual override (override beats AI, invariant #13).
- An archived playbook does NOT count as coverage (the gap stays a gap).
- A cluster of only-uncategorized tickets is skipped (no category to scope to).
- Empty / no-clusters is graceful.
- The endpoint serves the ranked list.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.models import (
    AICacheEntry,
    Override,
    Ticket,
    TicketCluster,
    TicketClusterMember,
)
from app.services import clusters as svc
from app.services import playbooks as playbooks_svc
from app.util import naive_utcnow

# Seeded categories (see DEFAULT_CATEGORIES): 1=Urgent, 2=Bug, 5=Billing, 7=Other.


def _make_ticket(ticket_id: str, category_id: int | None, updated_at) -> Ticket:
    return Ticket(
        id=ticket_id,
        title="t",
        state="open",
        author={},
        parts=[],
        internal_notes=[],
        created_at=updated_at,
        updated_at=updated_at,
        category_id=category_id,
        summary="",
        ai_confidence=0.0,
    )


async def _add_cluster(
    session: AsyncSession,
    cluster_id: int,
    *,
    label: str,
    size: int,
    ticket_ids: list[str],
    top_terms: list[str] | None = None,
) -> None:
    session.add(
        TicketCluster(
            id=cluster_id,
            label=label,
            top_terms=top_terms or [label],
            size=size,
        )
    )
    for tid in ticket_ids:
        session.add(TicketClusterMember(cluster_id=cluster_id, ticket_id=tid))
    await session.commit()


@pytest.mark.asyncio
async def test_cluster_with_playbook_excluded_one_without_included(
    session: AsyncSession,
) -> None:
    now = naive_utcnow()
    # Cluster 1 → all Billing (cat 5); Cluster 2 → all Urgent (cat 1).
    for i in range(3):
        session.add(_make_ticket(f"bill{i}", category_id=5, updated_at=now))
    for i in range(2):
        session.add(_make_ticket(f"urg{i}", category_id=1, updated_at=now))
    await session.commit()
    await _add_cluster(
        session, 1, label="billing refund", size=3, ticket_ids=["bill0", "bill1", "bill2"]
    )
    await _add_cluster(session, 2, label="login outage", size=2, ticket_ids=["urg0", "urg1"])

    # Billing has a playbook → its cluster is covered. Urgent has none → gap.
    await playbooks_svc.create(session, category_id=5, label="refund flow", body="steps")

    gaps = await svc.rank_gaps(session)
    assert [g.category_id for g in gaps] == [1]
    assert gaps[0].label == "login outage"
    assert gaps[0].size == 2
    assert gaps[0].category_name == "Urgent"
    assert gaps[0].member_count == 2


@pytest.mark.asyncio
async def test_gaps_ranked_by_size_descending(session: AsyncSession) -> None:
    now = naive_utcnow()
    # Two uncovered clusters of different sizes — bigger one ranks first.
    for i in range(2):
        session.add(_make_ticket(f"small{i}", category_id=1, updated_at=now))  # Urgent
    for i in range(4):
        session.add(_make_ticket(f"big{i}", category_id=2, updated_at=now))  # Bug
    await session.commit()
    await _add_cluster(session, 10, label="small one", size=2, ticket_ids=["small0", "small1"])
    await _add_cluster(
        session, 11, label="big one", size=4, ticket_ids=["big0", "big1", "big2", "big3"]
    )

    gaps = await svc.rank_gaps(session)
    assert [g.cluster_id for g in gaps] == [11, 10]
    assert [g.size for g in gaps] == [4, 2]


@pytest.mark.asyncio
async def test_effective_category_override_beats_ai(session: AsyncSession) -> None:
    """Invariant #13: a manual override (newer than the ticket) decides the
    member's effective category, which can flip the dominant category."""
    now = naive_utcnow()
    # AI says Billing (cat 5) for all members, but each is overridden to Bug (cat 2).
    for i in range(3):
        session.add(_make_ticket(f"ov{i}", category_id=5, updated_at=now))
        session.add(Override(ticket_id=f"ov{i}", category_id=2, set_at=now + timedelta(minutes=5)))
    await session.commit()
    await _add_cluster(session, 20, label="mislabelled", size=3, ticket_ids=["ov0", "ov1", "ov2"])

    # Billing HAS a playbook, Bug does NOT. Without override the cluster would be
    # covered; with override its dominant category is Bug → it IS a gap.
    await playbooks_svc.create(session, category_id=5, label="billing", body="steps")

    gaps = await svc.rank_gaps(session)
    assert len(gaps) == 1
    assert gaps[0].category_id == 2  # Bug, via override
    assert gaps[0].member_count == 3


@pytest.mark.asyncio
async def test_archived_playbook_does_not_cover(session: AsyncSession) -> None:
    now = naive_utcnow()
    for i in range(2):
        session.add(_make_ticket(f"t{i}", category_id=5, updated_at=now))  # Billing
    await session.commit()
    await _add_cluster(session, 30, label="billing again", size=2, ticket_ids=["t0", "t1"])

    pb = await playbooks_svc.create(session, category_id=5, label="old", body="steps")
    await playbooks_svc.archive(session, pb.id)

    gaps = await svc.rank_gaps(session)
    # Only an archived playbook exists → Billing is still an uncovered gap.
    assert [g.category_id for g in gaps] == [5]


@pytest.mark.asyncio
async def test_uncategorized_cluster_skipped(session: AsyncSession) -> None:
    now = naive_utcnow()
    # All members uncategorized (no AI category, no override) → no dominant
    # category → cannot suggest a playbook → skipped.
    for i in range(3):
        session.add(_make_ticket(f"u{i}", category_id=None, updated_at=now))
    await session.commit()
    await _add_cluster(session, 40, label="mystery", size=3, ticket_ids=["u0", "u1", "u2"])

    gaps = await svc.rank_gaps(session)
    assert gaps == []


@pytest.mark.asyncio
async def test_dominant_category_is_most_common(session: AsyncSession) -> None:
    """A mixed-category cluster picks the most common effective category."""
    now = naive_utcnow()
    # Two Bug (2), one Urgent (1) → dominant is Bug.
    session.add(_make_ticket("m0", category_id=2, updated_at=now))
    session.add(_make_ticket("m1", category_id=2, updated_at=now))
    session.add(_make_ticket("m2", category_id=1, updated_at=now))
    await session.commit()
    await _add_cluster(session, 50, label="mixed", size=3, ticket_ids=["m0", "m1", "m2"])

    gaps = await svc.rank_gaps(session)
    assert len(gaps) == 1
    assert gaps[0].category_id == 2
    assert gaps[0].member_count == 2  # the two Bug tickets


@pytest.mark.asyncio
async def test_no_clusters_is_graceful(session: AsyncSession) -> None:
    assert await svc.rank_gaps(session) == []


@pytest.mark.asyncio
async def test_ai_cache_untouched(session: AsyncSession) -> None:
    """Invariant #6: gap ranking is read-only and never writes `ai_cache`."""
    now = naive_utcnow()
    session.add(_make_ticket("c0", category_id=1, updated_at=now))
    await session.commit()
    await _add_cluster(session, 60, label="x", size=1, ticket_ids=["c0"])

    await svc.rank_gaps(session)

    cache_count = await session.scalar(text("SELECT count(*) FROM ai_cache"))
    assert cache_count == 0
    assert (await session.scalars(select(AICacheEntry))).all() == []


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_gaps_endpoint(client, session: AsyncSession, test_config: AppConfig) -> None:
    now = naive_utcnow()
    for i in range(3):
        session.add(_make_ticket(f"e{i}", category_id=1, updated_at=now))  # Urgent, no playbook
    await session.commit()
    await _add_cluster(session, 70, label="endpoint gap", size=3, ticket_ids=["e0", "e1", "e2"])

    resp = await client.get("/clusters/gaps")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["cluster_id"] == 70
    assert body[0]["category_id"] == 1
    assert body[0]["category_name"] == "Urgent"
    assert body[0]["size"] == 3
    assert body[0]["label"] == "endpoint gap"


@pytest.mark.asyncio
async def test_gaps_endpoint_empty(client) -> None:
    resp = await client.get("/clusters/gaps")
    assert resp.status_code == 200
    assert resp.json() == []

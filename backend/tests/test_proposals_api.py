"""T021–T024 — proposal list / approve / merge / reject."""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AICacheEntry, Category, CategoryProposal, RejectedProposalSignature
from app.services.proposals import list_pending


async def _make_proposal(session: AsyncSession, name: str = "Refund Delay") -> int:
    proposal = CategoryProposal(name=name, description="desc", status="pending")
    session.add(proposal)
    await session.flush()
    session.add(
        AICacheEntry(
            ticket_id=f"T-{name}",
            category_id=None,
            proposal_id=proposal.id,
            summary="s",
            confidence=0.6,
            ticket_updated_at=datetime(2026, 1, 1),
        ),
    )
    await session.commit()
    return proposal.id


@pytest.mark.asyncio
async def test_list_empty_on_fresh_db(client: AsyncClient) -> None:
    resp = await client.get("/proposals")
    assert resp.status_code == 200 and resp.json()["proposals"] == []


@pytest.mark.asyncio
async def test_list_includes_example_ticket_ids(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    await _make_proposal(session)
    resp = await client.get("/proposals")
    proposals = resp.json()["proposals"]
    assert len(proposals) == 1
    assert "T-Refund Delay" in proposals[0]["example_ticket_ids"]


@pytest.mark.asyncio
async def test_approve_creates_category_and_repoints_cache(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    pid = await _make_proposal(session)
    resp = await client.post(f"/proposals/{pid}/approve")
    assert resp.status_code == 200
    new_cat = resp.json()
    assert new_cat["source"] == "ai_proposed"

    session.expire_all()
    cache = await session.get(AICacheEntry, "T-Refund Delay")
    assert cache is not None
    assert cache.category_id == new_cat["id"] and cache.proposal_id is None


@pytest.mark.asyncio
async def test_merge_proposal_repoints_to_target(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    pid = await _make_proposal(session)
    resp = await client.post(f"/proposals/{pid}/merge-into/2")
    assert resp.status_code == 200 and resp.json()["moved_count"] == 1

    session.expire_all()
    cache = await session.get(AICacheEntry, "T-Refund Delay")
    assert cache is not None and cache.category_id == 2


@pytest.mark.asyncio
async def test_reject_records_signature_and_falls_back(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    pid = await _make_proposal(session)
    resp = await client.post(f"/proposals/{pid}/reject")
    assert resp.status_code == 200

    session.expire_all()
    fb = await session.scalar(select(Category.id).where(Category.is_fallback.is_(True)))
    cache = await session.get(AICacheEntry, "T-Refund Delay")
    assert cache is not None and cache.category_id == fb

    sig = await session.get(RejectedProposalSignature, "refund delay")
    assert sig is not None and sig.rejected_name == "Refund Delay"


@pytest.mark.asyncio
async def test_double_resolution_conflicts(
    client: AsyncClient,
    session: AsyncSession,
) -> None:
    pid = await _make_proposal(session)
    assert (await client.post(f"/proposals/{pid}/reject")).status_code == 200
    assert (await client.post(f"/proposals/{pid}/approve")).status_code == 409


def _query_counter(session: AsyncSession):
    """Count SQL statements issued on the session's engine. Returns (counter,
    stop) — call stop() to detach the listener."""
    sync_engine = session.bind.sync_engine
    counter = {"n": 0}

    def _before(*_args, **_kwargs):
        counter["n"] += 1

    event.listen(sync_engine, "before_cursor_execute", _before)
    return counter, lambda: event.remove(sync_engine, "before_cursor_execute", _before)


@pytest.mark.asyncio
async def test_list_pending_is_not_n_plus_one(session: AsyncSession) -> None:
    """Listing N pending proposals must issue a constant number of queries
    (1 for the proposals + 1 for all examples), not 1 + N."""
    for i in range(4):
        proposal = CategoryProposal(name=f"Prop {i}", description="d", status="pending")
        session.add(proposal)
        await session.flush()
        for j in range(6):  # 6 cache rows each, > _EXAMPLE_LIMIT (5)
            session.add(
                AICacheEntry(
                    ticket_id=f"T-{i}-{j}",
                    category_id=None,
                    proposal_id=proposal.id,
                    summary="s",
                    confidence=0.6,
                    ticket_updated_at=datetime(2026, 1, 1),
                )
            )
    await session.commit()

    counter, stop = _query_counter(session)
    try:
        out = await list_pending(session)
    finally:
        stop()

    assert len(out) == 4
    assert all(len(example_ids) == 5 for _proposal, example_ids in out)
    assert counter["n"] <= 2, f"expected <= 2 queries, got {counter['n']} (N+1 regression)"

"""T021–T024 — proposal list / approve / merge / reject."""

from __future__ import annotations

from datetime import datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AICacheEntry, Category, CategoryProposal, RejectedProposalSignature


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

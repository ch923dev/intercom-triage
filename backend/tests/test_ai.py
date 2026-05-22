"""T013–T016 — prompt builder, parser, resolver, parallel categorization."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import categorize_many, normalize_signature, parse_response
from app.ai.prompt import build_messages
from app.models import Category, CategoryProposal, RejectedProposalSignature
from tests.helpers import (
    FakeOpenRouter,
    existing_assignment,
    make_hydrated,
    new_proposal_assignment,
)

# ── T014 — parser ─────────────────────────────────────────────────────────────


def test_parse_existing() -> None:
    p = parse_response(existing_assignment(3))
    assert p.kind == "existing" and p.category_id == 3
    assert 0.0 <= p.confidence <= 1.0


def test_parse_pending_proposal() -> None:
    p = parse_response(
        '{"assignment":"pending_proposal","proposal_id":7,"summary":"s","confidence":0.5}',
    )
    assert p.kind == "pending_proposal" and p.proposal_id == 7


def test_parse_new_proposal() -> None:
    p = parse_response(new_proposal_assignment("Refund Delay"))
    assert p.kind == "new_proposal" and p.proposed_name == "Refund Delay"


def test_parse_strips_markdown_fences() -> None:
    raw = "```json\n" + existing_assignment(1) + "\n```"
    assert parse_response(raw).category_id == 1


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_response("this is not json at all")


def test_normalize_signature_deterministic() -> None:
    assert normalize_signature("  Refund   Delay ") == normalize_signature("refund delay")
    assert normalize_signature("Refund Delay") == "refund delay"


# ── T013 — prompt builder ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_includes_categories_and_rejected(session: AsyncSession) -> None:
    cats = (await session.scalars(select(Category))).all()
    messages = build_messages(make_hydrated("X"), cats, [], ["Outage"])
    user = messages[1]["content"]
    assert "Urgent" in user and "Outage" in user and "Sample ticket" in user


# ── T015 / T016 — resolver via categorize_many ────────────────────────────────


async def _fallback_id(session: AsyncSession) -> int:
    cid = await session.scalar(select(Category.id).where(Category.is_fallback.is_(True)))
    assert cid is not None
    return cid


@pytest.mark.asyncio
async def test_categorize_existing(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter({"X1": existing_assignment(1)})
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert out["X1"].category_id == 1 and out["X1"].proposal_id is None


@pytest.mark.asyncio
async def test_categorize_creates_proposal(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter({"X1": new_proposal_assignment("Refund Delay")})
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    pid = out["X1"].proposal_id
    assert pid is not None
    proposal = await session.get(CategoryProposal, pid)
    assert proposal is not None and proposal.name == "Refund Delay"


@pytest.mark.asyncio
async def test_categorize_dedups_proposal_within_batch(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter(
        {
            "X1": new_proposal_assignment("Refund Delay"),
            "X2": new_proposal_assignment("refund  delay"),  # same signature
        },
    )
    out = await categorize_many(
        [make_hydrated("X1"), make_hydrated("X2")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert out["X1"].proposal_id == out["X2"].proposal_id


@pytest.mark.asyncio
async def test_categorize_rejected_signature_falls_back(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    session.add(
        RejectedProposalSignature(signature="refund delay", rejected_name="Refund Delay"),
    )
    await session.commit()
    fake = FakeOpenRouter({"X1": new_proposal_assignment("Refund Delay")})
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert out["X1"].category_id == fb and out["X1"].confidence == 0.0


@pytest.mark.asyncio
async def test_categorize_one_failure_does_not_break_batch(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter({"X1": existing_assignment(1), "X2": "GARBAGE NOT JSON"})
    out = await categorize_many(
        [make_hydrated("X1"), make_hydrated("X2")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert len(out) == 2
    assert out["X1"].category_id == 1
    assert out["X2"].category_id == fb and out["X2"].confidence == 0.0


@pytest.mark.asyncio
async def test_categorize_no_client_all_fallback(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    out = await categorize_many(
        [make_hydrated("X1"), make_hydrated("X2")],
        session=session,
        client=None,
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert all(r.category_id == fb and r.confidence == 0.0 for r in out.values())

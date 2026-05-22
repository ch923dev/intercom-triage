"""Proposal endpoints. Reference: plan.md §4, tasks.md T021–T024."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import (
    CategoryProposalRead,
    CategoryRead,
    MergeResponse,
    OkResponse,
    ProposalApprove,
    ProposalsResponse,
)
from app.services import proposals as svc

router = APIRouter(prefix="/proposals", tags=["proposals"])


@router.get("", response_model=ProposalsResponse)
async def list_proposals(session: AsyncSession = Depends(get_session)) -> ProposalsResponse:
    """T021 — pending proposals, each with up to 5 example ticket ids."""
    rows = await svc.list_pending(session)
    out: list[CategoryProposalRead] = []
    for proposal, example_ids in rows:
        read = CategoryProposalRead.model_validate(proposal)
        read.example_ticket_ids = example_ids
        out.append(read)
    return ProposalsResponse(proposals=out)


@router.post("/{proposal_id}/approve", response_model=CategoryRead)
async def approve_proposal(
    proposal_id: int,
    body: ProposalApprove | None = None,
    session: AsyncSession = Depends(get_session),
) -> CategoryRead:
    """T022 — promote a proposal to a new active category."""
    body = body or ProposalApprove()
    category = await svc.approve_proposal(
        session,
        proposal_id,
        color=body.color,
        sort_order=body.sort_order,
    )
    return CategoryRead.model_validate(category)


@router.post("/{proposal_id}/merge-into/{category_id}", response_model=MergeResponse)
async def merge_proposal(
    proposal_id: int,
    category_id: int,
    session: AsyncSession = Depends(get_session),
) -> MergeResponse:
    """T023 — reassign the proposal's tickets to an existing category."""
    moved = await svc.merge_proposal(session, proposal_id, category_id)
    return MergeResponse(moved_count=moved)


@router.post("/{proposal_id}/reject", response_model=OkResponse)
async def reject_proposal(
    proposal_id: int,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """T024 — reject; tickets go to fallback, the name is remembered."""
    await svc.reject_proposal(session, proposal_id)
    return OkResponse()

"""Follow-up endpoints. Reference: plan.md §4 §8a, tasks.md T046."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import FollowupRead, FollowupSet, OkResponse, SnoozeRequest
from app.services import followups as svc

router = APIRouter(prefix="/followups", tags=["followups"])


@router.get("", response_model=list[FollowupRead])
async def list_followups(session: AsyncSession = Depends(get_session)) -> list[FollowupRead]:
    """T046 — every active follow-up, one row per ticket."""
    rows = await svc.list_followups(session)
    return [FollowupRead.model_validate(row) for row in rows]


@router.put("/{ticket_id}", response_model=FollowupRead)
async def set_followup(
    ticket_id: str,
    body: FollowupSet,
    session: AsyncSession = Depends(get_session),
) -> FollowupRead:
    """T046 — upsert a follow-up reminder for a ticket."""
    row = await svc.set_followup(session, ticket_id, body.due_at, body.reason)
    return FollowupRead.model_validate(row)


@router.post("/{ticket_id}/snooze", response_model=FollowupRead)
async def snooze_followup(
    ticket_id: str,
    body: SnoozeRequest,
    session: AsyncSession = Depends(get_session),
) -> FollowupRead:
    """T046 — reschedule the follow-up by `minutes` and clear `fired`."""
    row = await svc.snooze_followup(session, ticket_id, body.minutes)
    return FollowupRead.model_validate(row)


@router.post("/{ticket_id}/mark-fired", response_model=OkResponse)
async def mark_fired(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """T046 — flag the alarm as rung so reloads don't re-ring it."""
    await svc.mark_fired(session, ticket_id)
    return OkResponse()


@router.delete("/{ticket_id}", response_model=OkResponse)
async def delete_followup(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    """T046 — clear a follow-up. Idempotent."""
    await svc.delete_followup(session, ticket_id)
    return OkResponse()

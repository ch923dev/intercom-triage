"""Playbooks endpoints. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig
from app.db import get_session
from app.deps import get_app_config, get_openrouter
from app.schemas import (
    DraftReplyResponse,
    OkResponse,
    PlaybookCreate,
    PlaybookDraftRequest,
    PlaybookDraftResponse,
    PlaybookRead,
    PlaybookUpdate,
    SuggestedPlaybook,
)
from app.services import playbooks as svc

router = APIRouter(prefix="/playbooks", tags=["playbooks"])


@router.get("", response_model=list[PlaybookRead])
async def list_playbooks(
    ticket_id: str | None = None,
    category_id: int | None = None,
    include_archived: bool = False,
    session: AsyncSession = Depends(get_session),
) -> list[PlaybookRead]:
    """Playbooks for a ticket's effective category (`ticket_id`), a category
    (`category_id`), or all of them (no filter). `ticket_id` wins if both given."""
    if ticket_id is not None:
        rows = await svc.list_for_ticket(session, ticket_id)
    elif category_id is not None:
        rows = await svc.list_for_category(session, category_id, include_archived)
    else:
        rows = await svc.list_all(session, include_archived)
    return [PlaybookRead.model_validate(r) for r in rows]


@router.get("/suggested", response_model=list[SuggestedPlaybook])
async def suggested_playbooks(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[SuggestedPlaybook]:
    """Semantic playbook suggestions for a ticket on open (roadmap 3.3).

    Read-only: ranks the ticket's effective-category playbooks (invariant #13)
    by embedding similarity to its customer-visible text (invariant #4); never
    touches `ai_cache` (invariant #6). Ephemeral — nothing is persisted. Returns
    the top matches ordered most-relevant-first (empty if there are no
    in-category playbooks or no customer-visible text)."""
    suggestions = await svc.suggest_playbooks(session, ticket_id)
    return [
        SuggestedPlaybook(playbook=PlaybookRead.model_validate(s.playbook), score=s.score)
        for s in suggestions
    ]


@router.post("", response_model=PlaybookRead)
async def create_playbook(
    body: PlaybookCreate,
    session: AsyncSession = Depends(get_session),
) -> PlaybookRead:
    row = await svc.create(
        session,
        category_id=body.category_id,
        label=body.label,
        body=body.body,
        source_ticket_id=body.source_ticket_id,
    )
    return PlaybookRead.model_validate(row)


@router.post("/draft", response_model=PlaybookDraftResponse)
async def draft_playbook(
    body: PlaybookDraftRequest,
    session: AsyncSession = Depends(get_session),
    client: OpenRouterClient | None = Depends(get_openrouter),
    config: AppConfig = Depends(get_app_config),
) -> PlaybookDraftResponse:
    text = await svc.draft_from_ticket(
        session, body.ticket_id, client=client, model=config.openrouter_model
    )
    return PlaybookDraftResponse(body=text)


@router.post("/draft-reply", response_model=DraftReplyResponse)
async def draft_reply(
    body: PlaybookDraftRequest,
    session: AsyncSession = Depends(get_session),
    client: OpenRouterClient | None = Depends(get_openrouter),
    config: AppConfig = Depends(get_app_config),
) -> DraftReplyResponse:
    """RAG draft reply: grounds an ephemeral customer reply in the k nearest
    RESOLVED tickets (customer-visible parts only) + effective-category
    playbooks. Not persisted."""
    draft = await svc.draft_reply_from_ticket(
        session, body.ticket_id, client=client, model=config.openrouter_model
    )
    return DraftReplyResponse(
        body=draft.body,
        grounding_ticket_ids=draft.grounding_ticket_ids,
        playbook_ids=draft.playbook_ids,
    )


@router.patch("/{playbook_id}", response_model=PlaybookRead)
async def update_playbook(
    playbook_id: int,
    body: PlaybookUpdate,
    session: AsyncSession = Depends(get_session),
) -> PlaybookRead:
    row = await svc.update(session, playbook_id, label=body.label, body=body.body)
    return PlaybookRead.model_validate(row)


@router.post("/{playbook_id}/archive", response_model=OkResponse)
async def archive_playbook(
    playbook_id: int,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    await svc.archive(session, playbook_id)
    return OkResponse()


@router.post("/{playbook_id}/restore", response_model=OkResponse)
async def restore_playbook(
    playbook_id: int,
    session: AsyncSession = Depends(get_session),
) -> OkResponse:
    await svc.restore(session, playbook_id)
    return OkResponse()

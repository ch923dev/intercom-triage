"""Playbooks — reusable next-steps recipes scoped to a category.

Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md

Read-only lens over existing tables plus its own `playbooks` rows. Durable
operator-owned data — never keyed by content signature, never auto-busted.
The AI drafter reuses the OpenRouter client and excludes `internal_notes`
(invariant #4); only customer-visible `parts` + operator notes feed the prompt.
"""

from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.openrouter import OpenRouterClient
from app.metrics import metrics
from app.models import NoteEntry, Override, Playbook, Ticket, TicketNote
from app.services import note_entries as note_entries_svc
from app.util import naive_utcnow


async def list_for_category(
    session: AsyncSession,
    category_id: int,
    include_archived: bool = False,
) -> list[Playbook]:
    stmt = select(Playbook).where(Playbook.category_id == category_id)
    if not include_archived:
        stmt = stmt.where(Playbook.archived_at.is_(None))
    stmt = stmt.order_by(Playbook.created_at.asc(), Playbook.id.asc())
    return list((await session.scalars(stmt)).all())


async def list_for_ticket(session: AsyncSession, ticket_id: str) -> list[Playbook]:
    """Active playbooks for the ticket's *effective* category.

    Effective category = ticket.category_id, unless a manual override is newer
    than the ticket's last update (override beats AI — mirrors the board's
    composition rule). Uncategorized tickets return an empty list.
    """
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"no ticket {ticket_id}")
    category_id = ticket.category_id
    override = await session.get(Override, ticket_id)
    if override is not None and ticket.updated_at <= override.set_at:
        category_id = override.category_id
    if category_id is None:
        return []
    return await list_for_category(session, category_id)


async def create(
    session: AsyncSession,
    category_id: int,
    label: str,
    body: str,
    source_ticket_id: str | None = None,
) -> Playbook:
    now = naive_utcnow()
    row = Playbook(
        category_id=category_id,
        label=label,
        body=body,
        source_ticket_id=source_ticket_id,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    metrics.incr("playbooks_created_total")
    return row


async def archive(session: AsyncSession, playbook_id: int) -> Playbook:
    row = await session.get(Playbook, playbook_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no playbook {playbook_id}")
    if row.archived_at is None:
        row.archived_at = naive_utcnow()
        await session.commit()
        await session.refresh(row)
        metrics.incr("playbooks_archived_total")
    return row


async def update(
    session: AsyncSession,
    playbook_id: int,
    label: str | None,
    body: str | None,
) -> Playbook:
    row = await session.get(Playbook, playbook_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no playbook {playbook_id}")
    if label is not None:
        row.label = label
    if body is not None:
        row.body = body
    row.updated_at = naive_utcnow()
    await session.commit()
    await session.refresh(row)
    metrics.incr("playbooks_updated_total")
    return row


async def restore(session: AsyncSession, playbook_id: int) -> Playbook:
    row = await session.get(Playbook, playbook_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no playbook {playbook_id}")
    if row.archived_at is not None:
        row.archived_at = None
        await session.commit()
        await session.refresh(row)
    return row


async def list_all(session: AsyncSession, include_archived: bool = False) -> list[Playbook]:
    stmt = select(Playbook)
    if not include_archived:
        stmt = stmt.where(Playbook.archived_at.is_(None))
    stmt = stmt.order_by(Playbook.category_id.asc(), Playbook.created_at.asc(), Playbook.id.asc())
    return list((await session.scalars(stmt)).all())


_DRAFT_SYSTEM_PROMPT = """\
You are a support-operator assistant. Given one resolved support conversation
and the operator's private investigation notes, write a concise, reusable
"playbook" — the next steps an operator should take when this same issue
appears on another ticket.

Rules:
- Output 3 to 6 short imperative steps, one per line, numbered "1.", "2.", …
- Ground every step in what actually resolved THIS ticket.
- No greetings, no preamble, no closing remarks — only the numbered steps.
"""


def _render_notes(entries: list[NoteEntry], note: TicketNote | None) -> str:
    lines: list[str] = []
    if note is not None and note.body.strip():
        lines.append(note.body.strip())
    lines.extend(e.body.strip() for e in entries if e.body.strip())
    return "\n".join(f"- {line}" for line in lines) if lines else "(none)"


def build_draft_messages(
    ticket: Ticket,
    entries: list[NoteEntry],
    note: TicketNote | None,
) -> list[dict[str, str]]:
    """Build the chat messages for the drafter.

    Reads customer-visible `parts` + operator notes ONLY. `ticket.internal_notes`
    is deliberately never read here (invariant #4 — internal notes are never fed
    to the AI).
    """
    transcript_lines: list[str] = []
    for part in ticket.parts:
        body = str(part.get("body", "")).strip()
        if not body:
            continue
        author = part.get("author") or {}
        who = author.get("name") or author.get("type") or "user"
        transcript_lines.append(f"[{who}] {body}")
    transcript = "\n".join(transcript_lines) if transcript_lines else "(empty)"

    user_prompt = (
        f'TICKET TITLE: "{ticket.title or ""}"\n\n'
        "CUSTOMER-VISIBLE CONVERSATION:\n"
        f"{transcript}\n\n"
        "OPERATOR NOTES:\n"
        f"{_render_notes(entries, note)}\n"
    )
    return [
        {"role": "system", "content": _DRAFT_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


async def draft_from_ticket(
    session: AsyncSession,
    ticket_id: str,
    client: OpenRouterClient | None,
    model: str,
) -> str:
    """Generate an ephemeral playbook draft from a ticket. Not persisted."""
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"no ticket {ticket_id}")
    if client is None:
        raise HTTPException(status_code=503, detail="AI is not configured")

    entries = await note_entries_svc.list_for_ticket(session, ticket_id)
    note = await session.get(TicketNote, ticket_id)
    messages = build_draft_messages(ticket, entries, note)
    text = await client.complete(model=model, messages=messages, ticket_id=ticket_id)
    metrics.incr("playbook_drafts_total")
    return text.strip()

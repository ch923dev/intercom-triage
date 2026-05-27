"""Playbooks — reusable next-steps recipes scoped to a category.

Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md

Read-only lens over existing tables plus its own `playbooks` rows. Durable
operator-owned data — never keyed by content signature, never auto-busted.
The AI drafter reuses the OpenRouter client and excludes `internal_notes`
(invariant #4); only customer-visible `parts` + operator notes feed the prompt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embeddings
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


def _customer_visible_transcript(ticket: Ticket) -> str:
    """Render a ticket's customer-visible `parts` as an authored transcript.

    Reads `ticket.parts` ONLY — `ticket.internal_notes` is the team-only side
    channel and is deliberately never read here (invariant #4). Shared by the
    playbook drafter, the RAG query text, and the RAG grounding context so all
    three see the exact same customer-visible content and nothing else.
    """
    lines: list[str] = []
    for part in ticket.parts:
        body = str(part.get("body", "")).strip()
        if not body:
            continue
        author = part.get("author") or {}
        who = author.get("name") or author.get("type") or "user"
        lines.append(f"[{who}] {body}")
    return "\n".join(lines)


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
    transcript = _customer_visible_transcript(ticket) or "(empty)"

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


# ── RAG draft reply (roadmap 2.6) ─────────────────────────────────────────────
#
# A different drafter from the playbook one above: instead of distilling THIS
# ticket into a reusable recipe, it writes a reply to send to the customer,
# grounded in (a) the current conversation, (b) the customer-visible `parts` of
# the k nearest RESOLVED tickets (retrieved over the read-only `ticket_embeddings`
# store — never the `ai_cache`, invariant #6), and (c) the effective-category
# playbooks (override beats AI, invariant #13). All grounding is customer-visible
# only — retrieved tickets contribute `parts` and NEVER `internal_notes`
# (invariant #4). Ephemeral, like the playbook drafter — nothing is persisted.

_DEFAULT_RAG_K = 3
# Over-fetch from the vector index so that after dropping the current ticket and
# any unresolved neighbours we still have enough resolved precedents to ground in.
_RAG_FETCH_MULTIPLIER = 4

_DRAFT_REPLY_SYSTEM_PROMPT = """\
You are a support operator drafting a reply to send to a customer. You are given
the current conversation, excerpts from PAST RESOLVED tickets about similar
issues, and reusable playbooks for this ticket's category.

Rules:
- Write a single, ready-to-send reply addressed to the customer.
- Ground the reply in the supplied precedents and playbooks: when a past ticket
  or a playbook informs a step, reflect that resolution in the reply.
- Reference the relevant precedent inline as "(see TICKET-ID)" so the operator
  can trace where guidance came from. Cite only ticket ids that were supplied.
- Be concise and concrete. No internal jargon, no speculation beyond the context.
- Output ONLY the reply body — no subject line, no preamble, no sign-off block.
"""


@dataclass(frozen=True)
class DraftReply:
    """An ephemeral RAG draft reply plus the precedent it was grounded in.

    `grounding_ticket_ids` and `playbook_ids` are surfaced for transparency so
    the operator can see what informed the draft. Only customer-visible content
    ever reaches `body` (invariant #4)."""

    body: str
    grounding_ticket_ids: list[str]
    playbook_ids: list[int]


def _query_text(ticket: Ticket) -> str:
    """Compose the retrieval query text for a ticket: title + customer-visible
    transcript. Mirrors `embeddings.build_embedding_text`'s composition (title
    then `parts` block) so the query lands in the same vector space the stored
    ticket embeddings were built in. `internal_notes` are never included
    (invariant #4)."""
    segments: list[str] = []
    title = (ticket.title or "").strip()
    if title:
        segments.append(title)
    transcript = _customer_visible_transcript(ticket)
    if transcript:
        segments.append(transcript)
    return "\n\n".join(segments).strip()


def _render_precedents(precedents: list[tuple[str, str]]) -> str:
    """Render retrieved resolved tickets as labelled, customer-visible blocks.

    Each precedent is `(ticket_id, transcript)` where `transcript` is built from
    that ticket's `parts` ONLY (invariant #4)."""
    if not precedents:
        return "(no similar resolved tickets found)"
    blocks: list[str] = []
    for ticket_id, transcript in precedents:
        blocks.append(f"--- RESOLVED TICKET {ticket_id} ---\n{transcript or '(empty)'}")
    return "\n\n".join(blocks)


def _render_playbooks(rows: list[Playbook]) -> str:
    if not rows:
        return "(no playbooks for this category)"
    return "\n\n".join(f"PLAYBOOK: {p.label}\n{p.body}" for p in rows)


def build_draft_reply_messages(
    ticket: Ticket,
    precedents: list[tuple[str, str]],
    playbooks: list[Playbook],
) -> list[dict[str, str]]:
    """Build the chat messages for the RAG draft-reply prompt.

    Grounding is customer-visible only: `ticket.parts` for the current
    conversation, the retrieved resolved tickets' `parts` (passed in as
    `precedents`), and the operator-owned `playbooks`. `internal_notes` of the
    current ticket OR of any precedent never enter here (invariant #4)."""
    transcript = _customer_visible_transcript(ticket) or "(empty)"
    user_prompt = (
        f'CURRENT TICKET: {ticket.id} — "{ticket.title or ""}"\n\n'
        "CURRENT CONVERSATION (customer-visible):\n"
        f"{transcript}\n\n"
        "SIMILAR PAST RESOLVED TICKETS (customer-visible excerpts):\n"
        f"{_render_precedents(precedents)}\n\n"
        "PLAYBOOKS FOR THIS CATEGORY:\n"
        f"{_render_playbooks(playbooks)}\n"
    )
    return [
        {"role": "system", "content": _DRAFT_REPLY_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


async def _retrieve_resolved_precedents(
    session: AsyncSession,
    ticket: Ticket,
    k: int,
) -> list[tuple[str, str]]:
    """Find the k nearest RESOLVED tickets to `ticket`, excluding itself.

    Read-only over the `ticket_embeddings` store (invariant #6 — never touches
    `ai_cache`). Returns `(ticket_id, customer_visible_transcript)` ordered
    closest-first. Each precedent's transcript is built from its `parts` ONLY
    (invariant #4). Unresolved neighbours and the current ticket are dropped; we
    over-fetch from the index to compensate."""
    query_text = _query_text(ticket)
    if not query_text:
        return []
    fetch_k = max(k * _RAG_FETCH_MULTIPLIER, k + 1)
    neighbours = await embeddings.nearest_to_text(session, query_text, k=fetch_k)

    precedents: list[tuple[str, str]] = []
    for neighbour_id, _distance in neighbours:
        if neighbour_id == ticket.id:
            continue
        candidate = await session.get(Ticket, neighbour_id)
        if candidate is None or candidate.resolved_at is None:
            continue
        precedents.append((candidate.id, _customer_visible_transcript(candidate)))
        if len(precedents) >= k:
            break
    return precedents


async def draft_reply_from_ticket(
    session: AsyncSession,
    ticket_id: str,
    client: OpenRouterClient | None,
    model: str,
    k: int = _DEFAULT_RAG_K,
) -> DraftReply:
    """Generate an ephemeral RAG draft reply for a ticket. Not persisted.

    Grounds the model in the current conversation, the k nearest RESOLVED
    precedents' customer-visible `parts`, and the effective-category playbooks.
    Internal notes never enter the prompt (invariant #4); retrieval is read-only
    over the embeddings store (invariant #6); playbooks follow the effective
    category, override beating AI (invariant #13)."""
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"no ticket {ticket_id}")
    if client is None:
        raise HTTPException(status_code=503, detail="AI is not configured")

    precedents = await _retrieve_resolved_precedents(session, ticket, k)
    playbooks = await list_for_ticket(session, ticket_id)
    messages = build_draft_reply_messages(ticket, precedents, playbooks)
    text = await client.complete(
        model=model,
        messages=messages,
        ticket_id=ticket_id,
        response_format={"type": "text"},
    )
    metrics.incr("draft_replies_total")
    return DraftReply(
        body=text.strip(),
        grounding_ticket_ids=[tid for tid, _ in precedents],
        playbook_ids=[p.id for p in playbooks],
    )


# ── Semantic auto-match (roadmap 3.3) ─────────────────────────────────────────
#
# On ticket open, suggest the most-relevant playbook by embedding similarity.
# Candidates are restricted to the ticket's EFFECTIVE-category playbooks (reuse
# `list_for_ticket`, override beating AI — invariant #13), then ranked by cosine
# similarity between the ticket's customer-visible text (`_query_text`, mirroring
# `embeddings.build_embedding_text`, parts + title ONLY — invariant #4) and each
# candidate playbook's durable text (label + body — #13).
#
# STORAGE: computed on-demand in-memory, NOT a persisted vec0 table. At
# single-operator scale a category has only a handful of playbooks, so embedding
# the few candidates plus the ticket per request is cheap, and there is no
# migration / recompute-on-edit hook / backfill to keep durable playbook rows and
# their vectors in sync. Embedding is read-only w.r.t. `ai_cache` (invariant #6) —
# it never reads or writes the cache or the content signature. Ephemeral: the
# suggestion is a computed view, never stored as ticket state.

_DEFAULT_SUGGEST_TOP_N = 3


@dataclass(frozen=True)
class PlaybookSuggestion:
    """One ranked playbook candidate plus its similarity score in [-1, 1].

    `score` is the cosine similarity between the ticket query embedding and the
    playbook's (label + body) embedding; higher is closer. Ephemeral — computed,
    never persisted."""

    playbook: Playbook
    score: float


def _playbook_embedding_text(playbook: Playbook) -> str:
    """Durable text to embed for a playbook: its label + body (invariant #13).

    Operator-owned knowledge only — no ticket content, no `internal_notes`
    (invariant #4 is trivially satisfied; a playbook has neither)."""
    return f"{playbook.label}\n\n{playbook.body}".strip()


def _cosine(a: list[float], b: list[float]) -> float:
    """Cosine similarity of two equal-length vectors. Returns 0.0 if either is a
    zero vector (degenerate, no direction to compare)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


async def suggest_playbooks(
    session: AsyncSession,
    ticket_id: str,
    top_n: int = _DEFAULT_SUGGEST_TOP_N,
) -> list[PlaybookSuggestion]:
    """Rank the ticket's effective-category playbooks by semantic similarity.

    Candidates come from `list_for_ticket` (effective category, override beats
    AI — invariant #13). Each candidate is scored by cosine similarity between
    the ticket's customer-visible query text (`_query_text`, parts + title only —
    invariant #4) and the playbook's durable (label + body) text. Returns up to
    `top_n` candidates ordered most-relevant-first.

    Graceful degradation: an empty list if the ticket has no effective-category
    playbooks OR no customer-visible text to embed (nothing to rank against).
    Read-only over `ai_cache` (invariant #6) — embedding never touches the cache.
    """
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"no ticket {ticket_id}")

    candidates = await list_for_ticket(session, ticket_id)
    if not candidates:
        return []

    query_text = _query_text(ticket)
    if not query_text:
        # No customer-visible content to rank against — nothing to suggest.
        return []

    query_vec = embeddings.embed_text(query_text)
    scored: list[PlaybookSuggestion] = []
    for playbook in candidates:
        text_to_embed = _playbook_embedding_text(playbook)
        if not text_to_embed:
            continue
        playbook_vec = embeddings.embed_text(text_to_embed)
        scored.append(PlaybookSuggestion(playbook, _cosine(query_vec, playbook_vec)))

    # Highest similarity first; ties fall back to insertion order (stable sort).
    scored.sort(key=lambda s: s.score, reverse=True)
    metrics.incr("playbook_suggestions_total")
    return scored[:top_n]

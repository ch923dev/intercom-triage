"""Few-shot example retrieval for categorization. Reference: roadmap 2.5.

For each uncached ticket being categorized, retrieve its nearest stored
neighbours (roadmap 2.4 embeddings) and keep only those the operator has
*confirmed* with an `Override` row — a confirmed gold-standard label. Those
become in-context examples appended to the categorization prompt so the model
learns the operator's taxonomy from their own past decisions.

Invariants enforced here:
  - #4: an example's text is built from the neighbour ticket's customer-visible
    `title` + `parts[]` ONLY. Intercom `internal_notes[]` are team-only and
    NEVER enter an example. (The neighbour `Ticket.internal_notes` column is
    never even read in this module.)
  - #6: retrieval reads the SEPARATE `ticket_embeddings` store + the
    `overrides`/`categories`/`tickets` rows. It never reads or writes
    `ai_cache` or the content signature, so it cannot affect the cache key.
    Few-shot injection changes the PROMPT for uncached tickets only.

Efficiency: the embedding query is per-ticket (cheap, k small), but the
category-name and ticket-text lookups are BATCHED across the whole candidate
set — no N+1 over neighbours.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embeddings
from app.models import Category, Override, Ticket
from app.schemas import HydratedTicket

# Pull a few extra neighbours before filtering to confirmed overrides, since
# many of the closest neighbours may be unconfirmed tickets. The filtered set
# is then capped at the configured example count.
_OVERSAMPLE = 4
# Keep an example transcript compact — examples are context, not the ticket
# under review. A handful of short turns is plenty of signal.
_MAX_EXAMPLE_CHARS = 800


@dataclass(frozen=True)
class FewShotExample:
    """One confirmed-override neighbour rendered for the prompt.

    `text` is customer-visible only (title + parts, invariant #4);
    `category_name` is the operator's confirmed category for that ticket.
    """

    category_name: str
    text: str


def _example_text_from_ticket(ticket: Ticket) -> str:
    """Render a stored neighbour's customer-visible text: title + parts ONLY.

    NEVER reads `ticket.internal_notes` (invariant #4). Mirrors the embedding /
    transcript shape (`[author] body`) so the example reads like the ticket the
    model is judging. Bounded to keep the prompt small.
    """
    segments: list[str] = []
    title = (ticket.title or "").strip()
    if title:
        segments.append(title)

    rendered: list[str] = []
    for part in ticket.parts or []:
        body = str(part.get("body") or "").strip()
        if not body:
            continue
        author = part.get("author") or {}
        who = author.get("name") or author.get("email") or author.get("type") or "user"
        rendered.append(f"[{who}] {body}")
    if rendered:
        segments.append("\n\n".join(rendered))

    text = "\n\n".join(segments).strip()
    if len(text) > _MAX_EXAMPLE_CHARS:
        text = text[:_MAX_EXAMPLE_CHARS].rstrip() + " …"
    return text


async def gather_fewshot_examples(
    session: AsyncSession,
    tickets: Sequence[HydratedTicket],
    *,
    max_examples: int,
    operator_notes: dict[str, str] | None = None,
) -> dict[str, list[FewShotExample]]:
    """Return, per ticket id, up to `max_examples` confirmed-override neighbours.

    For each ticket: embed its customer-visible text, fetch nearest neighbours,
    keep only neighbours with an `Override` row (confirmed labels), drop the
    ticket itself, and take the closest `max_examples`. Category names + example
    text are resolved in BATCH across every candidate.

    `max_examples <= 0` short-circuits to an empty mapping so the caller's
    cold-corpus path is untouched.
    """
    if max_examples <= 0 or not tickets:
        return {}

    notes = operator_notes or {}

    # Phase 1: per-ticket nearest-neighbour query → ordered candidate ids,
    # excluding self. Oversample so the override filter still leaves enough.
    k = max_examples + _OVERSAMPLE
    candidates_by_ticket: dict[str, list[str]] = {}
    all_candidate_ids: set[str] = set()
    for ticket in tickets:
        query_text = embeddings.build_embedding_text(ticket, notes.get(ticket.id))
        if not query_text:
            continue
        vector = embeddings.embed_text(query_text)
        neighbours = await embeddings.nearest_neighbours(session, vector, k=k)
        ordered = [nid for (nid, _dist) in neighbours if nid != ticket.id]
        if ordered:
            candidates_by_ticket[ticket.id] = ordered
            all_candidate_ids.update(ordered)

    if not all_candidate_ids:
        return {}

    # Phase 2: batch-resolve which candidates are confirmed (have an Override)
    # and their confirmed category name — one query each, no N+1.
    override_rows = (
        await session.execute(
            select(Override.ticket_id, Override.category_id).where(
                Override.ticket_id.in_(all_candidate_ids)
            )
        )
    ).all()
    override_category: dict[str, int] = {row[0]: row[1] for row in override_rows}
    if not override_category:
        return {}

    category_names = _resolve_category_names(
        (await session.execute(select(Category.id, Category.name))).all()
    )

    # Batch-load the candidate tickets' customer-visible text. Only confirmed
    # candidates are fetched.
    confirmed_ids = set(override_category)
    ticket_rows = (await session.scalars(select(Ticket).where(Ticket.id.in_(confirmed_ids)))).all()
    text_by_ticket = {row.id: _example_text_from_ticket(row) for row in ticket_rows}

    # Phase 3: per ticket, walk its ordered candidates, keep confirmed ones with
    # a resolvable category + non-empty text, cap at max_examples.
    out: dict[str, list[FewShotExample]] = {}
    for ticket_id, ordered in candidates_by_ticket.items():
        examples: list[FewShotExample] = []
        for nid in ordered:
            cat_id = override_category.get(nid)
            if cat_id is None:
                continue
            cat_name = category_names.get(cat_id)
            example_text = text_by_ticket.get(nid)
            if not cat_name or not example_text:
                continue
            examples.append(FewShotExample(category_name=cat_name, text=example_text))
            if len(examples) >= max_examples:
                break
        if examples:
            out[ticket_id] = examples
    return out


def _resolve_category_names(rows: Iterable[Any]) -> dict[int, str]:
    return {int(row[0]): str(row[1]) for row in rows}

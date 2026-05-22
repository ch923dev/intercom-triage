"""AI prompt builder. Reference: plan.md §7, tasks.md T013.

Production port of `snippets/prompt_builder.py` — ids are integers (plan §12),
inputs are the real SQLAlchemy rows + the hydrated-ticket schema.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.models import Category, CategoryProposal
from app.schemas import HydratedTicket

MAX_TRANSCRIPT_CHARS = 6_000
TRUNCATION_MARKER = "\n\n…[truncated]…\n\n"

SYSTEM_PROMPT = """\
You are a support-ticket triage assistant.

You will receive the operator's current ticket categories, any AI-proposed
categories still pending review, names previously rejected by the operator,
and one customer conversation.

Output ONE JSON object choosing exactly one of three assignment options:

A) Assign to an EXISTING active category:
   {
     "assignment":  "existing",
     "category_id": <integer id of one of the ACTIVE CATEGORIES below>,
     "summary":     "<=280 chars; capture intent and any named entity",
     "confidence":  <float 0..1>
   }

B) Reuse an already-PENDING proposal:
   {
     "assignment":  "pending_proposal",
     "proposal_id": <integer id of one of the PENDING PROPOSALS below>,
     "summary":     "<=280 chars",
     "confidence":  <float 0..1>
   }

C) Propose a NEW category (only when no existing category fits with reasonable
   confidence AND no pending proposal fits either):
   {
     "assignment":           "new_proposal",
     "proposed_name":        "<short, title case, <=32 chars>",
     "proposed_description": "<one sentence describing what belongs here>",
     "summary":              "<=280 chars",
     "confidence":           <float 0..1>
   }

Rules:
- Prefer existing categories. Propose new only when the existing set genuinely
  cannot accommodate the ticket.
- NEVER propose a name that appears under PREVIOUSLY REJECTED.
- Output strictly the JSON object — no prose, no markdown fences.
"""


def _format_categories(categories: Iterable[Category]) -> str:
    lines = [f'- id:{c.id} name:"{c.name}" description:"{c.description}"' for c in categories]
    return "\n".join(lines) if lines else "(none)"


def _format_proposals(proposals: Iterable[CategoryProposal]) -> str:
    lines = [f'- id:{p.id} name:"{p.name}" description:"{p.description}"' for p in proposals]
    return "\n".join(lines) if lines else "(none)"


def _format_rejected(names: Iterable[str]) -> str:
    listed = list(names)
    return "\n".join(f'- "{n}"' for n in listed) if listed else "(none)"


def build_transcript(ticket: HydratedTicket) -> str:
    """Join non-empty parts as `[type:name] body`; middle-truncate over budget."""
    rendered: list[str] = []
    for part in ticket.parts:
        body = part.body.strip()
        if not body:
            continue
        who_type = part.author.type or "user"
        who_name = part.author.name or part.author.email or who_type
        rendered.append(f"[{who_type}:{who_name}] {body}")
    text = "\n\n".join(rendered).strip()

    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text
    half = (MAX_TRANSCRIPT_CHARS - len(TRUNCATION_MARKER)) // 2
    return text[:half] + TRUNCATION_MARKER + text[-half:]


def build_messages(
    ticket: HydratedTicket,
    active_categories: Iterable[Category],
    pending_proposals: Iterable[CategoryProposal],
    rejected_names: Iterable[str],
) -> list[dict[str, str]]:
    """Return the `messages` array for OpenRouter chat.completions."""
    user_prompt = (
        "ACTIVE CATEGORIES:\n"
        f"{_format_categories(active_categories)}\n\n"
        "PENDING PROPOSALS (treat as candidate categories until resolved):\n"
        f"{_format_proposals(pending_proposals)}\n\n"
        "PREVIOUSLY REJECTED (do not propose these names again):\n"
        f"{_format_rejected(rejected_names)}\n\n"
        "TICKET:\n"
        f'title: "{ticket.title or ""}"\n'
        f"state: {ticket.state or 'unknown'}\n"
        "transcript:\n"
        f"{build_transcript(ticket)}\n"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

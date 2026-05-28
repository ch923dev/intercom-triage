"""AI prompt builder. Reference: plan.md §7, tasks.md T013.

Production port of `snippets/prompt_builder.py` — ids are integers (plan §12),
inputs are the real SQLAlchemy rows + the hydrated-ticket schema.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from app.models import Category, CategoryProposal
from app.schemas import HydratedTicket

if TYPE_CHECKING:
    from app.ai.fewshot import FewShotExample

MAX_TRANSCRIPT_CHARS = 6_000
TRUNCATION_MARKER = "\n\n…[truncated]…\n\n"

SYSTEM_PROMPT = """\
You are a support-ticket triage assistant.

You will receive the operator's current ticket categories, any AI-proposed
categories still pending review, names previously rejected by the operator,
and one customer conversation.

Output ONE JSON object choosing exactly one of three assignment options.

EVERY response, regardless of option, must also include a `subject` field —
see SUBJECT rules below.

A) Assign to an EXISTING active category:
   {
     "assignment":            "existing",
     "category_id":           <integer id of one of the ACTIVE CATEGORIES below>,
     "subject":               "<see SUBJECT rules>",
     "summary":               "<=600 chars, 2-3 sentences (see SUMMARY rules)",
     "confidence":            <float 0..1>,
     "priority":              "low" | "normal" | "high" | "urgent",
     "sentiment":             "negative" | "neutral" | "positive",
     "labels":                ["<secondary tag>", ...],
     "resolution_verdict":    "resolved" | "non_actionable" | "not_resolved",
     "resolution_confidence": <float 0..1>,
     "resolution_reason":     "<see RESOLUTION rules>",
     "non_actionable_kind":   "auto_reply" | "thanks" | "spam" | "out_of_office" | "other" | null
   }

B) Reuse an already-PENDING proposal:
   {
     "assignment":            "pending_proposal",
     "proposal_id":           <integer id of one of the PENDING PROPOSALS below>,
     "subject":               "<see SUBJECT rules>",
     "summary":               "<=600 chars, 2-3 sentences (see SUMMARY rules)",
     "confidence":            <float 0..1>,
     "priority":              "low" | "normal" | "high" | "urgent",
     "sentiment":             "negative" | "neutral" | "positive",
     "labels":                ["<secondary tag>", ...],
     "resolution_verdict":    "resolved" | "non_actionable" | "not_resolved",
     "resolution_confidence": <float 0..1>,
     "resolution_reason":     "<see RESOLUTION rules>",
     "non_actionable_kind":   "auto_reply" | "thanks" | "spam" | "out_of_office" | "other" | null
   }

C) Propose a NEW category (only when no existing category fits with reasonable
   confidence AND no pending proposal fits either):
   {
     "assignment":            "new_proposal",
     "proposed_name":         "<short, title case, <=32 chars>",
     "proposed_description":  "<one sentence describing what belongs here>",
     "subject":               "<see SUBJECT rules>",
     "summary":               "<=600 chars, 2-3 sentences (see SUMMARY rules)",
     "confidence":            <float 0..1>,
     "priority":              "low" | "normal" | "high" | "urgent",
     "sentiment":             "negative" | "neutral" | "positive",
     "labels":                ["<secondary tag>", ...],
     "resolution_verdict":    "resolved" | "non_actionable" | "not_resolved",
     "resolution_confidence": <float 0..1>,
     "resolution_reason":     "<see RESOLUTION rules>",
     "non_actionable_kind":   "auto_reply" | "thanks" | "spam" | "out_of_office" | "other" | null
   }

SUBJECT rules:
- A short, scannable headline for the ticket — what an operator should see on
  a Kanban card before opening it. <= 80 characters, sentence case.
- Lead with the concrete topic (e.g. "Refund request for invoice #44812",
  "Login fails after password reset", "Export to CSV missing custom fields").
- Include the named entity when one is in the thread (order/invoice id, plan
  name, error code, product area).
- No greetings, no quotes, no trailing punctuation, no emoji.
- Never just echo "Re: …" / "Fwd: …" — strip those and write what it's about.

SUMMARY rules (applies to all three options):
- 2 to 3 sentences, total length <= 600 characters.
- Sentence 1: what the customer is asking or reporting, with any named entity
  (order id, plan name, error code).
- Sentence 2: relevant context already gathered in the thread (what's been
  tried, what the admin has replied, what's still unknown).
- Sentence 3 (optional): the next concrete action the operator should take.
- Plain prose. No bullets, no markdown, no greetings, no closing phrases.

RESOLUTION rules (applies to every response):
- Decide whether the conversation appears resolved, non-actionable, or unresolved.
- "resolved": the customer's most recent message indicates the issue is fixed,
  they thanked the agent for a working solution, or the agent's last reply closed
  the loop and the customer has not replied since.
- "non_actionable": no operator response required. Examples — auto-reply
  (out-of-office, vacation responder, calendar notification), marketing or
  promotional email, spam, or a bare "thanks" after an agent reply with nothing
  left to do. Lead the reason with a short kind tag where it applies:
  "auto-reply: ...", "spam: ...", "thanks: ...".
- "not_resolved": the customer is waiting on the agent, has a new question,
  expressed dissatisfaction, the issue is still reproducing, or the thread ends
  mid-troubleshooting without confirmation.
- Add these THREE fields to EVERY response object:
    "resolution_verdict":    "resolved" | "non_actionable" | "not_resolved",
    "resolution_confidence": <float 0..1>,
    "resolution_reason":     "<one short clause, <=120 chars, plain text>"
- When (and only when) resolution_verdict is "non_actionable", also return
  non_actionable_kind: one of "auto_reply", "thanks", "spam", "out_of_office",
  "other". Use "other" when none fit. For any other verdict, set it to null.

TRIAGE rules (applies to every response; add these THREE fields to EVERY object):
- "priority": how urgently the operator should pick this up.
    "urgent"  — outage, data loss, security incident, blocking many users, or an
                angry customer threatening churn now.
    "high"    — broken for this customer, time-sensitive, or clearly frustrated.
    "normal"  — a routine question, request, or report (the default).
    "low"     — FYI, nice-to-have, or no real time pressure.
- "sentiment": the customer's emotional tone in their most recent messages.
    "negative" | "neutral" | "positive". Default "neutral" when tone is unclear.
- "labels": 0 to 3 short secondary tags (lowercase, <=24 chars each) that
    describe cross-cutting facets beyond the single category — e.g.
    "refund", "login", "mobile", "api", "billing". Plain strings, no '#'.
    Return an empty array when nothing extra applies.

Rules:
- Prefer existing categories. Propose new only when the existing set genuinely
  cannot accommodate the ticket.
- NEVER propose a name that appears under PREVIOUSLY REJECTED.
- Output strictly the JSON object — no prose, no markdown fences.
"""


# ── Strict structured-output schema (roadmap 2.1) ─────────────────────────────
#
# Mirrors the three-option union documented in SYSTEM_PROMPT. Passed to
# OpenRouter as `response_format={"type":"json_schema",...}` for the
# categorization call only, so the happy path never produces malformed JSON.
# OpenAI-compatible `strict` mode requires: every property listed in `required`
# and `additionalProperties: false` on every object. The three assignment
# variants therefore become a closed `oneOf` — each branch repeats the shared
# fields (subject/summary/confidence/resolution_*) plus its own discriminator and
# assignment-specific keys. `parse_response` remains the defensive fallback for
# refusals / non-supporting endpoints (see pipeline.py).

_RESOLUTION_VERDICT_VALUES = ["resolved", "non_actionable", "not_resolved"]
# Roadmap 0.2 — triage enums on the SAME categorization call (no extra AI call).
_PRIORITY_VALUES = ["low", "normal", "high", "urgent"]
_SENTIMENT_VALUES = ["negative", "neutral", "positive"]

_SHARED_PROPERTIES: dict[str, Any] = {
    "subject": {"type": "string", "description": "<=80 char scannable headline."},
    "summary": {"type": "string", "description": "2-3 sentences, <=600 chars."},
    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "priority": {"type": "string", "enum": _PRIORITY_VALUES},
    "sentiment": {"type": "string", "enum": _SENTIMENT_VALUES},
    "labels": {
        "type": "array",
        "items": {"type": "string", "maxLength": 24},
        "description": "0-3 secondary tags beyond the single category.",
    },
    "resolution_verdict": {"type": "string", "enum": _RESOLUTION_VERDICT_VALUES},
    "resolution_confidence": {"type": "number", "minimum": 0, "maximum": 1},
    "resolution_reason": {"type": "string", "description": "One clause, <=120 chars."},
}
_SHARED_REQUIRED = [
    "subject",
    "summary",
    "confidence",
    "priority",
    "sentiment",
    "labels",
    "resolution_verdict",
    "resolution_confidence",
    "resolution_reason",
]


def _branch(assignment: str, extra: dict[str, Any]) -> dict[str, Any]:
    """One closed `oneOf` branch: shared fields + discriminator + branch keys."""
    properties: dict[str, Any] = {
        "assignment": {"type": "string", "const": assignment},
        **_SHARED_PROPERTIES,
        **extra,
    }
    return {
        "type": "object",
        "properties": properties,
        "required": ["assignment", *_SHARED_REQUIRED, *extra.keys()],
        "additionalProperties": False,
    }


CATEGORIZATION_JSON_SCHEMA: dict[str, Any] = {
    "name": "ticket_categorization",
    "strict": True,
    "schema": {
        "oneOf": [
            _branch(
                "existing",
                {"category_id": {"type": "integer"}},
            ),
            _branch(
                "pending_proposal",
                {"proposal_id": {"type": "integer"}},
            ),
            _branch(
                "new_proposal",
                {
                    "proposed_name": {"type": "string", "maxLength": 32},
                    "proposed_description": {"type": "string"},
                },
            ),
        ],
    },
}

CATEGORIZATION_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": CATEGORIZATION_JSON_SCHEMA,
}


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


def _format_fewshot(examples: Sequence[FewShotExample]) -> str:
    """Render confirmed-override neighbours as a delimited examples block.

    Each example is the neighbour's customer-visible text (title + parts, built
    upstream — invariant #4, NEVER internal notes) plus the operator's confirmed
    category. Returns "" when there are no examples so the caller can omit the
    block entirely and match the cold-corpus prompt exactly.
    """
    if not examples:
        return ""
    blocks: list[str] = []
    for i, ex in enumerate(examples, start=1):
        blocks.append(
            f'Example {i} — operator confirmed category: "{ex.category_name}"\n' f"{ex.text}"
        )
    body = "\n\n".join(blocks)
    return (
        "EXAMPLES OF HOW SIMILAR TICKETS WERE CATEGORIZED\n"
        "(operator-confirmed labels on the nearest past tickets — strong "
        "guidance for an EXISTING-category assignment, but judge this ticket on "
        "its own content):\n"
        f"{body}\n\n"
    )


def build_messages(
    ticket: HydratedTicket,
    active_categories: Iterable[Category],
    pending_proposals: Iterable[CategoryProposal],
    rejected_names: Iterable[str],
    fewshot_examples: Sequence[FewShotExample] | None = None,
) -> list[dict[str, str]]:
    """Return the `messages` array for OpenRouter chat.completions.

    When `fewshot_examples` is non-empty, a clearly delimited examples block of
    operator-confirmed neighbours is inserted ahead of the ticket. With no
    examples (cold corpus) the prompt is byte-for-byte the prior behavior.
    """
    user_prompt = (
        "ACTIVE CATEGORIES:\n"
        f"{_format_categories(active_categories)}\n\n"
        "PENDING PROPOSALS (treat as candidate categories until resolved):\n"
        f"{_format_proposals(pending_proposals)}\n\n"
        "PREVIOUSLY REJECTED (do not propose these names again):\n"
        f"{_format_rejected(rejected_names)}\n\n"
        f"{_format_fewshot(fewshot_examples or [])}"
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

"""T024 — AI prompt builder for the dynamic per-tenant taxonomy.

Pseudocode-grade Python: structure and shape are production-ready; the imports for
ORM rows are stubbed with dataclasses so the file is runnable on its own. When you
wire this in for real, replace the dataclasses with your SQLAlchemy models and drop
the `__main__` block.

Reference: plan.md §7 (AI specification), tasks.md T024.

What this module does:
  build_messages(ticket, active_categories, pending_proposals, rejected_names)
      -> list[dict]  ready for the OpenRouter `messages` field

What it does NOT do (separate tasks):
  - Calling OpenRouter           → T023
  - Parsing the model response   → T025
  - Resolving to category/proposal id → T026
  - Concurrency + fallback       → T027
  - Caching                      → T028
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Literal


# ── Configuration ─────────────────────────────────────────────────────────────

MAX_TRANSCRIPT_CHARS = 6_000
TRUNCATION_MARKER = "\n\n…[truncated]…\n\n"


# ── Inputs (replace with ORM imports in production) ───────────────────────────

@dataclass
class _Author:
    type: str | None = None       # "user" | "admin" | "lead" | "contact"
    name: str | None = None
    email: str | None = None


@dataclass
class _Part:
    author: _Author
    body: str                     # already HTML-stripped (T021)


@dataclass
class _Ticket:
    id: str
    title: str | None
    state: Literal["open", "closed", "snoozed"] | None
    parts: list[_Part] = field(default_factory=list)


@dataclass
class _Category:
    id: str                       # uuid as str in the prompt
    name: str
    description: str


@dataclass
class _Proposal:
    id: str
    name: str
    description: str


# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a support-ticket triage assistant.

You will receive a list of the tenant's current ticket categories, any
AI-proposed categories still pending admin review, names previously rejected
by the admin, and one customer conversation.

Output ONE JSON object choosing exactly one of three assignment options:

A) Assign to an EXISTING active category:
   {
     "assignment":  "existing",
     "category_id": "<uuid of one of the ACTIVE CATEGORIES below>",
     "summary":     "<≤280 chars; capture intent and any named entity>",
     "confidence":  <float 0..1>
   }

B) Reuse an already-PENDING proposal:
   {
     "assignment":  "pending_proposal",
     "proposal_id": "<uuid of one of the PENDING PROPOSALS below>",
     "summary":     "<≤280 chars>",
     "confidence":  <float 0..1>
   }

C) Propose a NEW category (only when no existing category fits with
   reasonable confidence AND no pending proposal fits either):
   {
     "assignment":           "new_proposal",
     "proposed_name":        "<short, title case, ≤32 chars>",
     "proposed_description": "<one sentence describing what belongs here>",
     "summary":              "<≤280 chars>",
     "confidence":           <float 0..1>
   }

Rules:
- Prefer existing categories. Propose new only when the existing set
  genuinely cannot accommodate the ticket.
- NEVER propose a name that appears under PREVIOUSLY REJECTED.
- Output strictly the JSON object — no prose, no markdown fences.
"""


# ── Formatting helpers ────────────────────────────────────────────────────────

def _format_categories(cats: Iterable[_Category]) -> str:
    lines = [
        f'- id:{c.id} name:"{c.name}" description:"{c.description}"'
        for c in cats
    ]
    return "\n".join(lines) if lines else "(none)"


def _format_proposals(props: Iterable[_Proposal]) -> str:
    lines = [
        f'- id:{p.id} name:"{p.name}" description:"{p.description}"'
        for p in props
    ]
    return "\n".join(lines) if lines else "(none)"


def _format_rejected(names: Iterable[str]) -> str:
    names = list(names)
    return "\n".join(f'- "{n}"' for n in names) if names else "(none)"


def _format_transcript(parts: Iterable[_Part]) -> str:
    """Join non-empty parts with blank lines. If over budget, middle-truncate."""
    rendered: list[str] = []
    for p in parts:
        body = (p.body or "").strip()
        if not body:
            continue
        who_type = p.author.type or "user"
        who_name = p.author.name or p.author.email or who_type
        rendered.append(f"[{who_type}:{who_name}] {body}")
    text = "\n\n".join(rendered).strip()

    if len(text) <= MAX_TRANSCRIPT_CHARS:
        return text

    half = (MAX_TRANSCRIPT_CHARS - len(TRUNCATION_MARKER)) // 2
    return text[:half] + TRUNCATION_MARKER + text[-half:]


# ── Public entry point ────────────────────────────────────────────────────────

def build_messages(
    ticket: _Ticket,
    active_categories: Iterable[_Category],
    pending_proposals: Iterable[_Proposal],
    rejected_names: Iterable[str],
) -> list[dict]:
    """Return the `messages` array for OpenRouter chat.completions.

    The caller (T023 client) wraps this in:
        {
          "model": "<env-or-tenant>",
          "messages": build_messages(...),
          "temperature": 0.1,
          "max_tokens": 400,
          "response_format": {"type": "json_object"}
        }
    """
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
        f"{_format_transcript(ticket.parts)}\n"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


# ── Operator notes ────────────────────────────────────────────────────────────
#
# • Taxonomy size. If a tenant has 50+ active categories, the prompt gets large
#   and steers the model worse. Soft cap of ~30 should hold for v1; revisit if
#   real tenants blow past it.
#
# • Description quality matters more than name. The model picks based on the
#   description text — if a category is named "Bug" but described vaguely,
#   classifications drift. The category admin page (T048) should encourage a
#   1-sentence description on create.
#
# • Why include pending proposals as candidates. Without this, the AI would
#   re-propose the same novel category every fetch, burning admin attention
#   and creating duplicates. Including them lets the AI cluster matching
#   tickets under one pending row.
#
# • Rejected list growth. If a tenant aggressively rejects, this list grows
#   unbounded. Two mitigations: (a) only include rejections from the last 90
#   days; (b) cap the list at top-N by recency and inform the AI that
#   "additional rejected names exist." Trivial follow-up if it becomes a
#   problem.
#
# • Why not provide few-shot examples. Examples bias the model toward the
#   example shape. Anthropic models follow the schema reliably without them
#   given response_format=json_object. Add only if you observe drift in
#   production.


# ── Inline smoke test (delete when wiring in) ─────────────────────────────────

if __name__ == "__main__":
    ticket = _Ticket(
        id="conv_12345",
        title="Cannot send messages — campaign stuck on 'queued'",
        state="open",
        parts=[
            _Part(
                _Author(type="user", name="Maria"),
                "Hi — our 'Spring Promo' campaign has been stuck on Queued for "
                "two hours. We tried pausing and resuming, no change. Customers "
                "are waiting. This is urgent.",
            ),
            _Part(
                _Author(type="admin", name="Support"),
                "Thanks Maria — checking the workflow queue now.",
            ),
            _Part(
                _Author(type="user", name="Maria"),
                "Anything? We're losing the window for this promo.",
            ),
        ],
    )
    cats = [
        _Category("c-1", "Urgent", "Outage, blocking issue, customer threatening churn"),
        _Category("c-2", "Bug", "Something broken or behaving unexpectedly"),
        _Category("c-3", "Question", "How-to, clarification, docs gap"),
        _Category("c-7", "Other", "Doesn't fit elsewhere"),
    ]
    proposals = [
        _Proposal("p-1", "Campaign Send Failure", "Campaign stuck in queued/sending state"),
    ]
    rejected = ["Outage", "VIP Issue"]

    messages = build_messages(ticket, cats, proposals, rejected)
    for m in messages:
        print(f"--- role: {m['role']} ---")
        print(m["content"])
        print()

"""AI response parsing, output resolution, and parallel categorization.

Reference: plan.md §7, tasks.md T014 (parser), T015 (resolver), T016 (pipeline).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.prompt import build_messages
from app.clients.openrouter import OpenRouterClient
from app.metrics import metrics
from app.models import Category, CategoryProposal, RejectedProposalSignature
from app.schemas import HydratedTicket

AssignmentKind = Literal["existing", "pending_proposal", "new_proposal"]

_FENCE_OPEN_RE = re.compile(r"^```[a-zA-Z]*\n?")
_FENCE_CLOSE_RE = re.compile(r"\n?```$")


@dataclass
class ParsedAssignment:
    kind: AssignmentKind
    summary: str
    confidence: float
    subject: str  # <=80 chars; the AI's title for the ticket. Empty when omitted.
    category_id: int | None = None
    proposal_id: int | None = None
    proposed_name: str | None = None
    proposed_description: str | None = None
    resolution_verdict: Literal["resolved", "non_actionable", "not_resolved"] | None = None
    resolution_confidence: float | None = None
    resolution_reason: str | None = None


@dataclass
class CategorizationResult:
    category_id: int | None
    proposal_id: int | None
    summary: str
    confidence: float
    subject: str = ""  # <=80 chars; AI-generated title. Used when Intercom's
    # conversation title is empty. Operator can override via PATCH /tickets/{id}.
    fallback: bool = False  # True when this result is the degraded fallback (AI
    # call failed or unavailable). Callers must NOT cache a fallback result —
    # caching it would pin the ticket to the fallback category until a new
    # customer message arrives. A cached result read back is always a genuine
    # categorization, so this stays False on the cache-read path.
    ai_resolution_verdict: Literal["resolved", "non_actionable", "not_resolved"] | None = None
    ai_resolution_confidence: float | None = None
    ai_resolution_reason: str | None = None


# ── T014 — parser ─────────────────────────────────────────────────────────────


def normalize_signature(name: str) -> str:
    """Deterministic across whitespace + case differences (plan §7)."""
    return " ".join(name.strip().lower().split())


def _coerce_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    return None


def _clamp_confidence(value: Any) -> float:
    try:
        conf = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, conf))


def _extract_json_object(raw: str) -> dict[str, Any]:
    """Strip markdown fences, extract the outermost `{...}`, parse."""
    text = raw.strip()
    if text.startswith("```"):
        text = _FENCE_CLOSE_RE.sub("", _FENCE_OPEN_RE.sub("", text)).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("no JSON object in model output")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("model output was not a JSON object")
    return parsed


def _parse_resolution(
    obj: dict[str, Any],
) -> tuple[
    Literal["resolved", "non_actionable", "not_resolved"] | None,
    float | None,
    str | None,
]:
    verdict = obj.get("resolution_verdict")
    if verdict not in ("resolved", "non_actionable", "not_resolved"):
        return None, None, None
    typed_verdict: Literal["resolved", "non_actionable", "not_resolved"] = verdict
    confidence_raw = obj.get("resolution_confidence")
    confidence_f: float | None
    try:
        confidence_f = max(0.0, min(1.0, float(str(confidence_raw))))
    except (TypeError, ValueError):
        confidence_f = None
    reason_raw = obj.get("resolution_reason")
    reason = str(reason_raw)[:120] if isinstance(reason_raw, str) and reason_raw.strip() else None
    return typed_verdict, confidence_f, reason


def parse_response(raw: str) -> ParsedAssignment:
    """Parse a model response into a typed assignment. Raises `ValueError` on any
    malformed shape — the caller treats that as a fallback trigger (FR-007)."""
    obj = _extract_json_object(raw)
    assignment = obj.get("assignment")
    # 600-char cap matches the SUMMARY rules in the system prompt (2-3 sentences:
    # intent, context, next action). Card UI line-clamps; flyout shows in full.
    summary = str(obj.get("summary") or "")[:600]
    subject = str(obj.get("subject") or "").strip()[:80]
    confidence = _clamp_confidence(obj.get("confidence"))
    verdict, res_conf, res_reason = _parse_resolution(obj)

    if assignment == "existing":
        category_id = _coerce_int(obj.get("category_id"))
        if category_id is None:
            raise ValueError("existing assignment without a valid category_id")
        return ParsedAssignment(
            "existing",
            summary,
            confidence,
            subject,
            category_id=category_id,
            resolution_verdict=verdict,
            resolution_confidence=res_conf,
            resolution_reason=res_reason,
        )

    if assignment == "pending_proposal":
        proposal_id = _coerce_int(obj.get("proposal_id"))
        if proposal_id is None:
            raise ValueError("pending_proposal assignment without a valid proposal_id")
        return ParsedAssignment(
            "pending_proposal",
            summary,
            confidence,
            subject,
            proposal_id=proposal_id,
            resolution_verdict=verdict,
            resolution_confidence=res_conf,
            resolution_reason=res_reason,
        )

    if assignment == "new_proposal":
        name = str(obj.get("proposed_name") or "").strip()
        if not name:
            raise ValueError("new_proposal assignment without a proposed_name")
        description = str(obj.get("proposed_description") or "").strip() or name
        return ParsedAssignment(
            "new_proposal",
            summary,
            confidence,
            subject,
            proposed_name=name,
            proposed_description=description,
            resolution_verdict=verdict,
            resolution_confidence=res_conf,
            resolution_reason=res_reason,
        )

    raise ValueError(f"unknown assignment kind: {assignment!r}")


# ── T015 — resolver ───────────────────────────────────────────────────────────


@dataclass
class _ResolverState:
    active_category_ids: set[int]
    pending_proposal_ids: set[int]
    pending_by_signature: dict[str, int]
    rejected_signatures: set[str]


async def resolve(
    parsed: ParsedAssignment,
    *,
    session: AsyncSession,
    state: _ResolverState,
) -> CategorizationResult:
    """Resolve a parsed assignment to a final `(category_id | proposal_id)`.

    Raises `ValueError` on an invalid id or a rejected proposal name — the
    caller maps that to the fallback path.
    """
    if parsed.kind == "existing":
        if parsed.category_id not in state.active_category_ids:
            raise ValueError(f"category_id {parsed.category_id} is not active")
        return CategorizationResult(
            parsed.category_id,
            None,
            parsed.summary,
            parsed.confidence,
            parsed.subject,
            ai_resolution_verdict=parsed.resolution_verdict,
            ai_resolution_confidence=parsed.resolution_confidence,
            ai_resolution_reason=parsed.resolution_reason,
        )

    if parsed.kind == "pending_proposal":
        if parsed.proposal_id not in state.pending_proposal_ids:
            raise ValueError(f"proposal_id {parsed.proposal_id} is not pending")
        return CategorizationResult(
            None,
            parsed.proposal_id,
            parsed.summary,
            parsed.confidence,
            parsed.subject,
            ai_resolution_verdict=parsed.resolution_verdict,
            ai_resolution_confidence=parsed.resolution_confidence,
            ai_resolution_reason=parsed.resolution_reason,
        )

    # new_proposal
    assert parsed.proposed_name is not None  # guaranteed by parse_response
    signature = normalize_signature(parsed.proposed_name)

    if signature in state.rejected_signatures:
        raise ValueError(f"proposed name {signature!r} was previously rejected")

    existing = state.pending_by_signature.get(signature)
    if existing is not None:
        return CategorizationResult(
            None,
            existing,
            parsed.summary,
            parsed.confidence,
            parsed.subject,
            ai_resolution_verdict=parsed.resolution_verdict,
            ai_resolution_confidence=parsed.resolution_confidence,
            ai_resolution_reason=parsed.resolution_reason,
        )

    proposal = CategoryProposal(
        name=parsed.proposed_name,
        description=parsed.proposed_description or parsed.proposed_name,
        status="pending",
    )
    session.add(proposal)
    await session.flush()  # assigns proposal.id

    state.pending_by_signature[signature] = proposal.id
    state.pending_proposal_ids.add(proposal.id)
    metrics.incr("proposals_created_total")
    return CategorizationResult(
        None,
        proposal.id,
        parsed.summary,
        parsed.confidence,
        parsed.subject,
        ai_resolution_verdict=parsed.resolution_verdict,
        ai_resolution_confidence=parsed.resolution_confidence,
        ai_resolution_reason=parsed.resolution_reason,
    )


# ── T016 — parallel categorization ────────────────────────────────────────────


def _fallback(ticket: HydratedTicket, fallback_category_id: int) -> CategorizationResult:
    """FR-007 — degrade to the fallback category, title summary, zero confidence."""
    return CategorizationResult(
        category_id=fallback_category_id,
        proposal_id=None,
        summary=(ticket.title or "")[:600],
        confidence=0.0,
        # No AI subject available — leave empty so `_upsert_ticket` falls back to
        # Intercom's title (which may itself be empty; UI shows the placeholder).
        subject="",
        fallback=True,
    )


async def categorize_many(
    tickets: list[HydratedTicket],
    *,
    session: AsyncSession,
    client: OpenRouterClient | None,
    model: str,
    concurrency: int,
    fallback_category_id: int,
) -> dict[str, CategorizationResult]:
    """Categorize a batch. Network calls run in parallel under a semaphore;
    resolution runs sequentially on the shared session. Any failure on a single
    ticket degrades that ticket to the fallback — the batch always completes."""
    if not tickets:
        return {}

    # No AI configured → every ticket degrades to fallback (still a complete batch).
    if client is None:
        return {t.id: _fallback(t, fallback_category_id) for t in tickets}

    categories = (await session.scalars(select(Category).where(Category.is_active.is_(True)))).all()
    proposals = (
        await session.scalars(
            select(CategoryProposal).where(CategoryProposal.status == "pending"),
        )
    ).all()
    rejected_rows = (await session.scalars(select(RejectedProposalSignature))).all()

    state = _ResolverState(
        active_category_ids={c.id for c in categories},
        pending_proposal_ids={p.id for p in proposals},
        pending_by_signature={normalize_signature(p.name): p.id for p in proposals},
        rejected_signatures={r.signature for r in rejected_rows},
    )
    rejected_names = [r.rejected_name for r in rejected_rows]

    semaphore = asyncio.Semaphore(concurrency)

    async def _call(ticket: HydratedTicket) -> str:
        async with semaphore:
            messages = build_messages(ticket, categories, proposals, rejected_names)
            return await client.complete(
                model=model,
                messages=messages,
                ticket_id=ticket.id,
            )

    raw_results = await asyncio.gather(
        *(_call(t) for t in tickets),
        return_exceptions=True,
    )

    out: dict[str, CategorizationResult] = {}
    for ticket, raw in zip(tickets, raw_results, strict=True):
        try:
            if isinstance(raw, BaseException):
                raise raw
            parsed = parse_response(raw)
            out[ticket.id] = await resolve(parsed, session=session, state=state)
            metrics.incr("ai_calls_total.ok")
        except Exception:
            out[ticket.id] = _fallback(ticket, fallback_category_id)
            metrics.incr("ai_calls_total.error")
    return out

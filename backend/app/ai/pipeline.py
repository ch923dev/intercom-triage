"""AI response parsing, output resolution, and parallel categorization.

Reference: plan.md §7, tasks.md T014 (parser), T015 (resolver), T016 (pipeline).
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.fewshot import FewShotExample, gather_fewshot_examples
from app.ai.prompt import CATEGORIZATION_RESPONSE_FORMAT, build_messages
from app.clients.openrouter import OpenRouterClient
from app.metrics import metrics
from app.models import Category, CategoryProposal, RejectedProposalSignature
from app.schemas import HydratedTicket, NonActionableKind

AssignmentKind = Literal["existing", "pending_proposal", "new_proposal"]

# Roadmap 0.2 — triage facets emitted by the SAME categorization call.
Priority = Literal["low", "normal", "high", "urgent"]
Sentiment = Literal["negative", "neutral", "positive"]
_PRIORITY_VALUES: frozenset[str] = frozenset(("low", "normal", "high", "urgent"))
_SENTIMENT_VALUES: frozenset[str] = frozenset(("negative", "neutral", "positive"))

# T107 — structured sub-classification for non_actionable verdicts.
_NON_ACTIONABLE_KINDS: tuple[str, ...] = ("auto_reply", "thanks", "spam", "out_of_office", "other")

# US-044 — early bug detection. A fifth facet on the SAME categorization call:
# no extra AI spend, and the cache key (invariant #6) is untouched. `None` is the
# default at every layer, so a fallback result carries no verdict by construction
# (invariant #7) and a non-bug ticket is indistinguishable from an un-analyzed one.
BugSeverity = Literal["low", "medium", "high"]
_BUG_SEVERITIES: tuple[str, ...] = ("low", "medium", "high")
# Defaults applied to a fallback result and to any malformed/missing facet — a
# neutral baseline so a card never renders an empty / misleading badge.
_DEFAULT_PRIORITY: Priority = "normal"
_DEFAULT_SENTIMENT: Sentiment = "neutral"

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
    non_actionable_kind: NonActionableKind | None = None
    # Roadmap 0.2 — priority/sentiment/multi-label triage facets.
    priority: Priority = _DEFAULT_PRIORITY
    sentiment: Sentiment = _DEFAULT_SENTIMENT
    labels: list[str] = field(default_factory=list)
    # US-044 — bug verdict. All three move together: no severity means no bug,
    # so the confidence and the quote are meaningless without it.
    bug_severity: BugSeverity | None = None
    bug_confidence: float | None = None
    bug_evidence: str | None = None


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
    non_actionable_kind: NonActionableKind | None = None
    # Roadmap 0.2 — triage facets persisted on the ticket row + cache. A
    # fallback result carries the neutral defaults (normal / neutral / []).
    ai_priority: Priority = _DEFAULT_PRIORITY
    ai_sentiment: Sentiment = _DEFAULT_SENTIMENT
    ai_labels: list[str] = field(default_factory=list)
    # US-044 — bug verdict, carried to `services.bug_alerts` (which records it)
    # and to `ai_cache` (so a cache hit still yields a verdict). A fallback result
    # leaves these at None: a fallback is never cached (invariant #7) and must
    # never fabricate a bug report.
    bug_severity: BugSeverity | None = None
    bug_confidence: float | None = None
    bug_evidence: str | None = None


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


def _parse_triage(obj: dict[str, Any]) -> tuple[Priority, Sentiment, list[str]]:
    """Read the roadmap-0.2 triage facets, falling back to neutral defaults.

    Tolerant on purpose: a missing or out-of-enum priority/sentiment degrades
    to the neutral default rather than failing the whole parse (the assignment
    discriminator + summary are what gate the fallback path). `labels` is
    coerced to a clean list of <=3 short, non-empty strings.
    """
    # Guard the frozenset membership with isinstance: an unhashable non-string
    # (`[]` / `{}`) from the model would raise TypeError on `in` and sink the
    # whole categorization to an uncached fallback. Degrade to the neutral
    # default instead, as the docstring promises.
    priority_raw = obj.get("priority")
    priority: Priority = _DEFAULT_PRIORITY
    if isinstance(priority_raw, str) and priority_raw in _PRIORITY_VALUES:
        priority = priority_raw  # type: ignore[assignment]

    sentiment_raw = obj.get("sentiment")
    sentiment: Sentiment = _DEFAULT_SENTIMENT
    if isinstance(sentiment_raw, str) and sentiment_raw in _SENTIMENT_VALUES:
        sentiment = sentiment_raw  # type: ignore[assignment]

    labels_raw = obj.get("labels")
    labels: list[str] = []
    if isinstance(labels_raw, list):
        seen: set[str] = set()
        for item in labels_raw:
            if not isinstance(item, str):
                continue
            tag = item.strip().lstrip("#").strip()[:24]
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                labels.append(tag)
            if len(labels) >= 3:
                break
    return priority, sentiment, labels


def _parse_non_actionable_kind(verdict: str | None, raw_kind: object) -> NonActionableKind | None:
    # Kind is only meaningful for the non_actionable verdict.
    if verdict != "non_actionable":
        return None
    if isinstance(raw_kind, str) and raw_kind in _NON_ACTIONABLE_KINDS:
        return raw_kind  # type: ignore[return-value]
    # Missing or out-of-set kind on a non_actionable verdict → 'other'
    # (graceful: never abort the whole ticket over a soft sub-classification).
    return "other"


def _parse_bug_verdict(
    obj: dict[str, Any],
) -> tuple[BugSeverity | None, float | None, str | None]:
    """Read the US-044 bug facet. Never raises — an absent or malformed verdict
    degrades to "not a bug", exactly like the triage facets degrade to neutral.

    All three fields move as a unit: an out-of-vocabulary severity drops the
    confidence and the quote with it, so a caller can branch on `severity is
    not None` alone. The evidence is truncated to 200 chars to match the
    `bug_alerts.evidence` CHECK — a model that ignores the prompt's length rule
    must not fail the insert.
    """
    raw_severity = obj.get("bug_severity")
    severity: BugSeverity | None = None
    if isinstance(raw_severity, str) and raw_severity.strip().lower() in _BUG_SEVERITIES:
        severity = raw_severity.strip().lower()  # type: ignore[assignment]
    if severity is None:
        return None, None, None

    confidence: float | None
    try:
        confidence = max(0.0, min(1.0, float(str(obj.get("bug_confidence")))))
    except (TypeError, ValueError):
        confidence = None

    raw_evidence = obj.get("bug_evidence")
    evidence = (
        raw_evidence.strip()[:200]
        if isinstance(raw_evidence, str) and raw_evidence.strip()
        else None
    )
    return severity, confidence, evidence


# Typography a model routinely "tidies" while quoting: curly quotes, dashes,
# non-breaking / zero-width spaces. Folding these is what stops a genuinely
# verbatim quote from being rejected by the provenance check below — observed
# live on a quote whose only deviation was “…” → "…".
_QUOTE_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
        "​": "",
        "﻿": "",
    }
)


def _fold_for_match(text: str) -> str:
    """Casefolded, whitespace-collapsed, typography-normalized comparison form."""
    return " ".join(text.translate(_QUOTE_FOLD).casefold().split())


def verify_bug_evidence(parsed: ParsedAssignment, ticket: HydratedTicket) -> ParsedAssignment:
    """Drop `bug_evidence` unless it is verbatim from a CUSTOMER message.

    The prompt asks for the customer's own words, but `parts[]` legitimately
    carries admin replies too, and the model will quote our own agent describing
    the defect — "I noticed that your analytics aren't displaying properly" was
    the support rep, not the customer. In Slack that reads as a customer report
    when it is not one, which is exactly the trust the quote is there to buy.
    Measured on live traffic: 1 in 14.

    Prompt wording cannot survive a model swap, so the check is deterministic.
    Containment is tested per part, not against the concatenated thread: a
    "quote" stitched from two separate messages was never said in one breath.
    A failed check drops the quote and KEEPS the verdict — an evidence-less bug
    report is still a bug report, and silently discarding the detection would be
    the worse trade.
    """
    if parsed.bug_evidence is None:
        return parsed
    needle = _fold_for_match(parsed.bug_evidence)
    if needle and any(
        needle in _fold_for_match(part.body)
        for part in ticket.parts
        if not part.is_admin and part.body
    ):
        return parsed
    metrics.incr("bug_evidence_rejected_total")
    return replace(parsed, bug_evidence=None)


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
    priority, sentiment, labels = _parse_triage(obj)
    na_kind = _parse_non_actionable_kind(verdict, obj.get("non_actionable_kind"))
    bug_severity, bug_confidence, bug_evidence = _parse_bug_verdict(obj)

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
            non_actionable_kind=na_kind,
            priority=priority,
            sentiment=sentiment,
            labels=labels,
            bug_severity=bug_severity,
            bug_confidence=bug_confidence,
            bug_evidence=bug_evidence,
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
            non_actionable_kind=na_kind,
            priority=priority,
            sentiment=sentiment,
            labels=labels,
            bug_severity=bug_severity,
            bug_confidence=bug_confidence,
            bug_evidence=bug_evidence,
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
            non_actionable_kind=na_kind,
            priority=priority,
            sentiment=sentiment,
            labels=labels,
            bug_severity=bug_severity,
            bug_confidence=bug_confidence,
            bug_evidence=bug_evidence,
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
            non_actionable_kind=parsed.non_actionable_kind,
            ai_priority=parsed.priority,
            ai_sentiment=parsed.sentiment,
            ai_labels=parsed.labels,
            bug_severity=parsed.bug_severity,
            bug_confidence=parsed.bug_confidence,
            bug_evidence=parsed.bug_evidence,
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
            non_actionable_kind=parsed.non_actionable_kind,
            ai_priority=parsed.priority,
            ai_sentiment=parsed.sentiment,
            ai_labels=parsed.labels,
            bug_severity=parsed.bug_severity,
            bug_confidence=parsed.bug_confidence,
            bug_evidence=parsed.bug_evidence,
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
            non_actionable_kind=parsed.non_actionable_kind,
            ai_priority=parsed.priority,
            ai_sentiment=parsed.sentiment,
            ai_labels=parsed.labels,
            bug_severity=parsed.bug_severity,
            bug_confidence=parsed.bug_confidence,
            bug_evidence=parsed.bug_evidence,
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
        non_actionable_kind=parsed.non_actionable_kind,
        ai_priority=parsed.priority,
        ai_sentiment=parsed.sentiment,
        ai_labels=parsed.labels,
        bug_severity=parsed.bug_severity,
        bug_confidence=parsed.bug_confidence,
        bug_evidence=parsed.bug_evidence,
    )


# ── T016 — parallel categorization ────────────────────────────────────────────


def _fallback(ticket: HydratedTicket, fallback_category_id: int) -> CategorizationResult:
    """FR-007 — degrade to the fallback category, title summary, zero confidence.

    Triage facets (ai_priority / ai_sentiment / ai_labels) fall to the dataclass
    defaults (normal / neutral / []) — a neutral baseline, never cached (see
    `ingest_tickets`).
    """
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
    fewshot_examples: int = 0,
    operator_notes: dict[str, str] | None = None,
    cheap_model: str | None = None,
    escalate_below: float = 0.0,
) -> dict[str, CategorizationResult]:
    """Categorize a batch. Network calls run in parallel under a semaphore;
    resolution runs sequentially on the shared session. Any failure on a single
    ticket degrades that ticket to the fallback — the batch always completes.

    `fewshot_examples > 0` (roadmap 2.5) injects up to that many nearest
    confirmed-override neighbours into each ticket's prompt as in-context
    examples. With 0 (or a cold corpus) the prompt is unchanged. The retrieval
    reads the separate embedding store + override/category/ticket rows ONLY —
    never `ai_cache` / the content signature (invariant #6).

    Roadmap 2.2 — model cascade. When `cheap_model` is set (and differs from the
    strong `model`), each ticket is first categorized with the CHEAP model. If
    that parses cleanly AND the model's self-reported `confidence` is
    `>= escalate_below`, the cheap result is kept. Otherwise (low confidence, a
    failed cheap call, or malformed cheap output) the ticket ESCALATES: it is
    re-run with the strong `model` and that result is used. Routing only changes
    WHICH model runs — the prompt/input (invariant #4) and the eventual cache key
    (invariant #6, owned by the caller via the unchanged content signature) are
    untouched, and a malformed strong-model output still degrades to the
    per-ticket fallback (invariant #7). `cheap_model=None` (or equal to `model`)
    disables the cascade: behavior is exactly the single strong-model call."""
    if not tickets:
        return {}

    # No AI configured → every ticket degrades to fallback (still a complete batch).
    if client is None:
        return {t.id: _fallback(t, fallback_category_id) for t in tickets}

    # Cascade is active only when a distinct cheap model is configured. Equal ids
    # collapse to the single-call path so an accidental same-model config is a
    # no-op rather than a wasteful double call.
    cascade = cheap_model is not None and cheap_model != model

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

    # Roadmap 2.5 — gather nearest confirmed-override examples per ticket BEFORE
    # building messages (one cheap embedding query per ticket; the category-name
    # + example-text lookups are batched inside). Cold corpus / disabled → {}.
    examples_by_ticket: dict[str, list[FewShotExample]] = await gather_fewshot_examples(
        session,
        tickets,
        max_examples=fewshot_examples,
        operator_notes=operator_notes,
    )

    semaphore = asyncio.Semaphore(concurrency)

    async def _complete(ticket: HydratedTicket, use_model: str) -> str:
        messages = build_messages(
            ticket,
            categories,
            proposals,
            rejected_names,
            examples_by_ticket.get(ticket.id),
        )
        return await client.complete(
            model=use_model,
            messages=messages,
            ticket_id=ticket.id,
            # Plain json_object mode — strict json_schema was reverted (T151):
            # the default Anthropic model 400s on it via OpenRouter, sinking
            # EVERY ticket to fallback. SYSTEM_PROMPT is the response contract
            # and parse_response is the defensive net for refusals / drift.
            response_format=CATEGORIZATION_RESPONSE_FORMAT,
            # Above the 400 default: the response now carries a fifth facet (the
            # US-044 bug verdict, incl. a <=200-char quote) and a truncated
            # object fails the parse, costing the whole categorization. Raised
            # HERE and not on the client default so playbook drafting — which
            # shares `complete()` — is neither lengthened nor re-priced.
            max_tokens=550,
        )

    async def _call(ticket: HydratedTicket) -> str:
        async with semaphore:
            if not cascade:
                return await _complete(ticket, model)

            # Cascade: try the cheap model first. A clean parse with high enough
            # self-reported confidence is kept; anything else escalates to the
            # strong model. The escalation RATE is the key risk metric (roadmap
            # 2.2: a >40% rate makes the double call cost more than it saves).
            assert cheap_model is not None  # cascade ⇒ cheap_model set
            metrics.incr("cascade_cheap_total")
            try:
                cheap_raw = await _complete(ticket, cheap_model)
                cheap_confidence = parse_response(cheap_raw).confidence
            except Exception:
                # Failed/malformed cheap call → escalate (do not fabricate a
                # result; the strong model gets a clean shot).
                cheap_raw = None
                cheap_confidence = -1.0

            if cheap_raw is not None and cheap_confidence >= escalate_below:
                return cheap_raw

            metrics.incr("cascade_escalated_total")
            return await _complete(ticket, model)

    raw_results = await asyncio.gather(
        *(_call(t) for t in tickets),
        return_exceptions=True,
    )

    out: dict[str, CategorizationResult] = {}
    for ticket, raw in zip(tickets, raw_results, strict=True):
        try:
            if isinstance(raw, BaseException):
                raise raw
            parsed = verify_bug_evidence(parse_response(raw), ticket)
            out[ticket.id] = await resolve(parsed, session=session, state=state)
            metrics.incr("ai_calls_total.ok")
        except Exception:
            out[ticket.id] = _fallback(ticket, fallback_category_id)
            metrics.incr("ai_calls_total.error")
    return out

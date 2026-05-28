"""T013–T016 — prompt builder, parser, resolver, parallel categorization."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import categorize_many, normalize_signature, parse_response
from app.ai.prompt import (
    CATEGORIZATION_RESPONSE_FORMAT,
    build_messages,
)
from app.metrics import metrics
from app.models import Category, CategoryProposal, RejectedProposalSignature
from tests.helpers import (
    FakeCascadeOpenRouter,
    FakeOpenRouter,
    existing_assignment,
    make_hydrated,
    new_proposal_assignment,
)

# ── T014 — parser ─────────────────────────────────────────────────────────────


def test_parse_existing() -> None:
    p = parse_response(existing_assignment(3))
    assert p.kind == "existing" and p.category_id == 3
    assert 0.0 <= p.confidence <= 1.0


def test_parse_pending_proposal() -> None:
    p = parse_response(
        '{"assignment":"pending_proposal","proposal_id":7,"summary":"s","confidence":0.5}',
    )
    assert p.kind == "pending_proposal" and p.proposal_id == 7


def test_parse_new_proposal() -> None:
    p = parse_response(new_proposal_assignment("Refund Delay"))
    assert p.kind == "new_proposal" and p.proposed_name == "Refund Delay"


def test_parse_strips_markdown_fences() -> None:
    raw = "```json\n" + existing_assignment(1) + "\n```"
    assert parse_response(raw).category_id == 1


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_response("this is not json at all")


def test_normalize_signature_deterministic() -> None:
    assert normalize_signature("  Refund   Delay ") == normalize_signature("refund delay")
    assert normalize_signature("Refund Delay") == "refund delay"


# ── T013 — prompt builder ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_prompt_includes_categories_and_rejected(session: AsyncSession) -> None:
    cats = (await session.scalars(select(Category))).all()
    messages = build_messages(make_hydrated("X"), cats, [], ["Outage"])
    user = messages[1]["content"]
    assert "Urgent" in user and "Outage" in user and "Sample ticket" in user


# ── T015 / T016 — resolver via categorize_many ────────────────────────────────


async def _fallback_id(session: AsyncSession) -> int:
    cid = await session.scalar(select(Category.id).where(Category.is_fallback.is_(True)))
    assert cid is not None
    return cid


@pytest.mark.asyncio
async def test_categorize_existing(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter({"X1": existing_assignment(1)})
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert out["X1"].category_id == 1 and out["X1"].proposal_id is None


@pytest.mark.asyncio
async def test_categorize_creates_proposal(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter({"X1": new_proposal_assignment("Refund Delay")})
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    pid = out["X1"].proposal_id
    assert pid is not None
    proposal = await session.get(CategoryProposal, pid)
    assert proposal is not None and proposal.name == "Refund Delay"


@pytest.mark.asyncio
async def test_categorize_dedups_proposal_within_batch(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter(
        {
            "X1": new_proposal_assignment("Refund Delay"),
            "X2": new_proposal_assignment("refund  delay"),  # same signature
        },
    )
    out = await categorize_many(
        [make_hydrated("X1"), make_hydrated("X2")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert out["X1"].proposal_id == out["X2"].proposal_id


@pytest.mark.asyncio
async def test_categorize_rejected_signature_falls_back(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    session.add(
        RejectedProposalSignature(signature="refund delay", rejected_name="Refund Delay"),
    )
    await session.commit()
    fake = FakeOpenRouter({"X1": new_proposal_assignment("Refund Delay")})
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert out["X1"].category_id == fb and out["X1"].confidence == 0.0


@pytest.mark.asyncio
async def test_categorize_one_failure_does_not_break_batch(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    fake = FakeOpenRouter({"X1": existing_assignment(1), "X2": "GARBAGE NOT JSON"})
    out = await categorize_many(
        [make_hydrated("X1"), make_hydrated("X2")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert len(out) == 2
    assert out["X1"].category_id == 1
    assert out["X2"].category_id == fb and out["X2"].confidence == 0.0


@pytest.mark.asyncio
async def test_categorize_no_client_all_fallback(session: AsyncSession) -> None:
    fb = await _fallback_id(session)
    out = await categorize_many(
        [make_hydrated("X1"), make_hydrated("X2")],
        session=session,
        client=None,
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert all(r.category_id == fb and r.confidence == 0.0 for r in out.values())


@pytest.mark.asyncio
async def test_resolver_propagates_resolution_fields(session: AsyncSession) -> None:
    """resolve() carries verdict + confidence + reason through to CategorizationResult."""
    from app.ai.pipeline import ParsedAssignment, _ResolverState, resolve

    fb = await _fallback_id(session)
    state = _ResolverState(
        active_category_ids={fb, 99},
        pending_proposal_ids=set(),
        pending_by_signature={},
        rejected_signatures=set(),
    )
    parsed = ParsedAssignment(
        "existing",
        "summary",
        0.8,
        "subj",
        category_id=99,
        resolution_verdict="resolved",
        resolution_confidence=0.82,
        resolution_reason="customer confirmed working",
    )
    result = await resolve(parsed, session=session, state=state)
    assert result.ai_resolution_verdict == "resolved"
    assert result.ai_resolution_confidence == 0.82
    assert result.ai_resolution_reason == "customer confirmed working"


def test_fallback_result_has_null_resolution_fields() -> None:
    from datetime import datetime

    from app.ai.pipeline import _fallback
    from app.schemas import HydratedTicket, TicketAuthorSchema

    hydrated = HydratedTicket(
        id="x",
        title="t",
        state="open",
        priority=None,
        created_at=datetime(2026, 5, 23),
        updated_at=datetime(2026, 5, 23),
        author=TicketAuthorSchema(),
        url=None,
        parts=[],
    )
    result = _fallback(hydrated, fallback_category_id=1)
    assert result.ai_resolution_verdict is None
    assert result.ai_resolution_confidence is None
    assert result.ai_resolution_reason is None


# ── 2.1 — strict structured outputs ────────────────────────────────────────────


def test_categorization_response_format_is_strict_json_schema() -> None:
    """The shared schema constant follows OpenRouter's strict json_schema convention."""
    assert CATEGORIZATION_RESPONSE_FORMAT["type"] == "json_schema"
    js = CATEGORIZATION_RESPONSE_FORMAT["json_schema"]
    assert js["strict"] is True
    assert js["name"] == "ticket_categorization"
    branches = js["schema"]["oneOf"]
    assert len(branches) == 3
    for branch in branches:
        # strict mode: every object closed + every property required.
        assert branch["additionalProperties"] is False
        assert set(branch["required"]) == set(branch["properties"].keys())
    assignments = {b["properties"]["assignment"]["const"] for b in branches}
    assert assignments == {"existing", "pending_proposal", "new_proposal"}


def test_parse_schema_conforming_response() -> None:
    """A response matching the strict schema parses into a full assignment."""
    raw = (
        '{"assignment":"existing","category_id":2,'
        '"subject":"Refund request for invoice #44812",'
        '"summary":"Customer wants a refund.","confidence":0.91,'
        '"resolution_verdict":"not_resolved","resolution_confidence":0.7,'
        '"resolution_reason":"awaiting refund confirmation"}'
    )
    p = parse_response(raw)
    assert p.kind == "existing"
    assert p.category_id == 2
    assert p.subject == "Refund request for invoice #44812"
    assert p.confidence == 0.91
    assert p.resolution_verdict == "not_resolved"
    assert p.resolution_confidence == 0.7
    assert p.resolution_reason == "awaiting refund confirmation"


@pytest.mark.asyncio
async def test_categorize_sends_strict_schema(session: AsyncSession) -> None:
    """The categorization call injects the strict json_schema response_format."""
    fb = await _fallback_id(session)
    fake = FakeOpenRouter({"X1": existing_assignment(1)})
    await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert fake.last_response_format == CATEGORIZATION_RESPONSE_FORMAT


# ── 0.2 — priority / sentiment / multi-label triage facets ─────────────────────


def test_parse_triage_facets() -> None:
    """parse_response reads priority/sentiment/labels from the model JSON."""
    raw = (
        '{"assignment":"existing","category_id":2,"subject":"x","summary":"y",'
        '"confidence":0.8,"priority":"urgent","sentiment":"negative",'
        '"labels":["refund","billing"]}'
    )
    p = parse_response(raw)
    assert p.priority == "urgent"
    assert p.sentiment == "negative"
    assert p.labels == ["refund", "billing"]


def test_parse_triage_defaults_when_missing() -> None:
    """Missing facets degrade to neutral defaults without failing the parse."""
    raw = '{"assignment":"existing","category_id":1,"subject":"x","summary":"y","confidence":0.5}'
    p = parse_response(raw)
    assert p.priority == "normal"
    assert p.sentiment == "neutral"
    assert p.labels == []


def test_parse_triage_clamps_invalid_enums() -> None:
    """Out-of-set priority/sentiment fall back to the neutral default."""
    raw = (
        '{"assignment":"existing","category_id":1,"subject":"x","summary":"y",'
        '"confidence":0.5,"priority":"catastrophic","sentiment":"furious"}'
    )
    p = parse_response(raw)
    assert p.priority == "normal"
    assert p.sentiment == "neutral"


def test_parse_triage_labels_dedupe_and_cap() -> None:
    """Labels are trimmed, '#'-stripped, deduped (case-insensitive), capped at 3."""
    raw = (
        '{"assignment":"existing","category_id":1,"subject":"x","summary":"y",'
        '"confidence":0.5,"labels":["#Refund"," refund ","login","mobile","api"]}'
    )
    p = parse_response(raw)
    assert p.labels == ["Refund", "login", "mobile"]


def test_fallback_result_has_neutral_triage_facets() -> None:
    from datetime import datetime

    from app.ai.pipeline import _fallback
    from app.schemas import HydratedTicket, TicketAuthorSchema

    hydrated = HydratedTicket(
        id="x",
        title="t",
        state="open",
        priority=None,
        created_at=datetime(2026, 5, 23),
        updated_at=datetime(2026, 5, 23),
        author=TicketAuthorSchema(),
        url=None,
        parts=[],
    )
    result = _fallback(hydrated, fallback_category_id=1)
    assert result.ai_priority == "normal"
    assert result.ai_sentiment == "neutral"
    assert result.ai_labels == []


def test_categorization_schema_includes_triage_fields() -> None:
    """The strict json_schema requires priority/sentiment/labels on every branch."""
    js = CATEGORIZATION_RESPONSE_FORMAT["json_schema"]
    for branch in js["schema"]["oneOf"]:
        props = branch["properties"]
        assert props["priority"]["enum"] == ["low", "normal", "high", "urgent"]
        assert props["sentiment"]["enum"] == ["negative", "neutral", "positive"]
        assert props["labels"]["type"] == "array"
        for facet in ("priority", "sentiment", "labels"):
            assert facet in branch["required"]


@pytest.mark.asyncio
async def test_resolver_propagates_triage_facets(session: AsyncSession) -> None:
    """resolve() carries priority/sentiment/labels into CategorizationResult."""
    from app.ai.pipeline import ParsedAssignment, _ResolverState, resolve

    fb = await _fallback_id(session)
    state = _ResolverState(
        active_category_ids={fb, 99},
        pending_proposal_ids=set(),
        pending_by_signature={},
        rejected_signatures=set(),
    )
    parsed = ParsedAssignment(
        "existing",
        "summary",
        0.8,
        "subj",
        category_id=99,
        priority="high",
        sentiment="negative",
        labels=["refund"],
    )
    result = await resolve(parsed, session=session, state=state)
    assert result.ai_priority == "high"
    assert result.ai_sentiment == "negative"
    assert result.ai_labels == ["refund"]


@pytest.mark.asyncio
async def test_categorize_nonconforming_response_falls_back(session: AsyncSession) -> None:
    """A schema-violating response (valid JSON, unknown assignment) degrades that
    ticket to fallback without aborting the batch — the defensive parse path holds
    even if a non-supporting endpoint ignores the strict schema."""
    fb = await _fallback_id(session)
    fake = FakeOpenRouter(
        {
            "X1": existing_assignment(1),
            "X2": '{"assignment":"banana","summary":"x","confidence":0.5}',
        },
    )
    out = await categorize_many(
        [make_hydrated("X1"), make_hydrated("X2")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model="m",
        concurrency=2,
        fallback_category_id=fb,
    )
    assert len(out) == 2
    assert out["X1"].category_id == 1
    assert out["X2"].category_id == fb
    assert out["X2"].fallback is True


# ── 2.2 — model cascade (cheap → escalate-on-low-confidence) ───────────────────

CHEAP = "anthropic/claude-3.5-haiku"
STRONG = "anthropic/claude-sonnet-4.5"


@pytest.mark.asyncio
async def test_cascade_easy_ticket_stays_on_cheap(session: AsyncSession) -> None:
    """A confident cheap-model answer (>= threshold) is kept — no escalation, the
    strong model is never called."""
    metrics.reset()
    fb = await _fallback_id(session)
    fake = FakeCascadeOpenRouter(
        {(CHEAP, "X1"): existing_assignment(1, confidence=0.9)},
    )
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model=STRONG,
        concurrency=2,
        fallback_category_id=fb,
        cheap_model=CHEAP,
        escalate_below=0.7,
    )
    assert out["X1"].category_id == 1
    assert fake.calls_by_model.get(CHEAP) == 1
    assert fake.calls_by_model.get(STRONG) is None
    counters = metrics.snapshot()
    assert counters.get("cascade_cheap_total") == 1
    assert counters.get("cascade_escalated_total", 0) == 0


@pytest.mark.asyncio
async def test_cascade_low_confidence_escalates_to_strong(session: AsyncSession) -> None:
    """A low-confidence cheap answer escalates: the STRONG model's result is used
    and the escalation counter increments."""
    metrics.reset()
    fb = await _fallback_id(session)
    fake = FakeCascadeOpenRouter(
        {
            (CHEAP, "X1"): existing_assignment(1, confidence=0.3),  # below 0.7
            (STRONG, "X1"): existing_assignment(2, confidence=0.95),
        },
    )
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model=STRONG,
        concurrency=2,
        fallback_category_id=fb,
        cheap_model=CHEAP,
        escalate_below=0.7,
    )
    # Strong model's category (2) wins, not the cheap one (1).
    assert out["X1"].category_id == 2
    assert fake.calls_by_model.get(CHEAP) == 1
    assert fake.calls_by_model.get(STRONG) == 1
    counters = metrics.snapshot()
    assert counters.get("cascade_cheap_total") == 1
    assert counters.get("cascade_escalated_total") == 1


@pytest.mark.asyncio
async def test_cascade_failed_cheap_call_escalates(session: AsyncSession) -> None:
    """A failed/malformed cheap call (no canned cheap response) escalates to the
    strong model rather than degrading straight to fallback."""
    metrics.reset()
    fb = await _fallback_id(session)
    # No (CHEAP, X1) entry → cheap call raises OpenRouterError → escalate.
    fake = FakeCascadeOpenRouter(
        {(STRONG, "X1"): existing_assignment(2, confidence=0.95)},
    )
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model=STRONG,
        concurrency=2,
        fallback_category_id=fb,
        cheap_model=CHEAP,
        escalate_below=0.7,
    )
    assert out["X1"].category_id == 2
    assert out["X1"].fallback is False
    counters = metrics.snapshot()
    assert counters.get("cascade_escalated_total") == 1


@pytest.mark.asyncio
async def test_cascade_disabled_single_strong_call(session: AsyncSession) -> None:
    """cheap_model=None → single strong-model call, no cascade telemetry."""
    metrics.reset()
    fb = await _fallback_id(session)
    fake = FakeCascadeOpenRouter(
        {(STRONG, "X1"): existing_assignment(1, confidence=0.95)},
    )
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model=STRONG,
        concurrency=2,
        fallback_category_id=fb,
        cheap_model=None,
    )
    assert out["X1"].category_id == 1
    assert fake.calls_by_model.get(STRONG) == 1
    assert fake.calls_by_model.get(CHEAP) is None
    counters = metrics.snapshot()
    assert counters.get("cascade_cheap_total", 0) == 0


@pytest.mark.asyncio
async def test_cascade_same_model_collapses_to_single_call(session: AsyncSession) -> None:
    """cheap_model == model is a no-op cascade: one call, no cascade counters."""
    metrics.reset()
    fb = await _fallback_id(session)
    fake = FakeCascadeOpenRouter(
        {(STRONG, "X1"): existing_assignment(1, confidence=0.4)},  # low conf, but no cheap split
    )
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model=STRONG,
        concurrency=2,
        fallback_category_id=fb,
        cheap_model=STRONG,
        escalate_below=0.7,
    )
    assert out["X1"].category_id == 1
    assert fake.calls_by_model.get(STRONG) == 1
    assert metrics.snapshot().get("cascade_cheap_total", 0) == 0


@pytest.mark.asyncio
async def test_cascade_strong_malformed_still_falls_back(session: AsyncSession) -> None:
    """Escalation does not save a malformed strong-model output — it still degrades
    to the per-ticket fallback (invariant #7), and the batch completes."""

    fb = await _fallback_id(session)
    fake = FakeCascadeOpenRouter(
        {
            (CHEAP, "X1"): existing_assignment(1, confidence=0.2),  # escalate
            (STRONG, "X1"): "GARBAGE NOT JSON",  # malformed → fallback
        },
    )
    out = await categorize_many(
        [make_hydrated("X1")],
        session=session,
        client=fake,  # type: ignore[arg-type]
        model=STRONG,
        concurrency=2,
        fallback_category_id=fb,
        cheap_model=CHEAP,
        escalate_below=0.7,
    )
    assert out["X1"].category_id == fb
    assert out["X1"].fallback is True


# ── T107 — structured non_actionable_kind ─────────────────────────────────────


def test_parse_response_reads_non_actionable_kind() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"out of office",'
        '"confidence":0.9,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.95,"resolution_reason":"auto-reply: OOO",'
        '"non_actionable_kind":"auto_reply"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind == "auto_reply"


def test_parse_response_defaults_kind_to_other_when_missing() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"thanks",'
        '"confidence":0.9,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.9,"resolution_reason":"thanks"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind == "other"


def test_parse_response_kind_null_when_verdict_not_non_actionable() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"needs reply",'
        '"confidence":0.9,"resolution_verdict":"not_resolved",'
        '"resolution_confidence":0.4,"resolution_reason":"awaiting fix",'
        '"non_actionable_kind":"spam"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind is None


def test_parse_response_invalid_kind_falls_back_to_other() -> None:
    raw = (
        '{"assignment":"existing","category_id":1,"summary":"weird",'
        '"confidence":0.9,"resolution_verdict":"non_actionable",'
        '"resolution_confidence":0.9,"resolution_reason":"?",'
        '"non_actionable_kind":"banana"}'
    )
    parsed = parse_response(raw)
    assert parsed.non_actionable_kind == "other"


@pytest.mark.asyncio
async def test_cascade_escalation_rate_accounting(session: AsyncSession) -> None:
    """MEASURE-FIRST harness: run a representative mixed-confidence batch through
    the cascade and assert the escalation accounting (rate = escalated / cheap).

    Mix: 7 confident (>=0.7) cheap answers kept, 3 low-confidence escalated →
    expected escalation rate 30% (< the 40% break-even the roadmap warns about)."""
    from app.metrics import metrics

    metrics.reset()
    fb = await _fallback_id(session)

    confident = {f"C{i}" for i in range(7)}  # kept on cheap
    weak = {f"W{i}" for i in range(3)}  # escalated to strong
    canned: dict[tuple[str, str], str] = {}
    for tid in confident:
        canned[(CHEAP, tid)] = existing_assignment(1, confidence=0.85)
    for tid in weak:
        canned[(CHEAP, tid)] = existing_assignment(1, confidence=0.4)
        canned[(STRONG, tid)] = existing_assignment(2, confidence=0.95)

    fake = FakeCascadeOpenRouter(canned)
    tickets = [make_hydrated(tid) for tid in (*confident, *weak)]
    out = await categorize_many(
        tickets,
        session=session,
        client=fake,  # type: ignore[arg-type]
        model=STRONG,
        concurrency=4,
        fallback_category_id=fb,
        cheap_model=CHEAP,
        escalate_below=0.7,
    )

    assert len(out) == 10
    counters = metrics.snapshot()
    cheap_total = counters["cascade_cheap_total"]
    escalated = counters["cascade_escalated_total"]
    assert cheap_total == 10
    assert escalated == 3
    # Escalation rate = escalated / cheap. 3/10 = 0.30 — below the 0.40 break-even.
    assert escalated / cheap_total == pytest.approx(0.30)
    # Confident tickets kept the cheap category (1); escalated ones got strong (2).
    for tid in confident:
        assert out[tid].category_id == 1
    for tid in weak:
        assert out[tid].category_id == 2

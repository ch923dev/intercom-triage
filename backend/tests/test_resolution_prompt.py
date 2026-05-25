"""T3 — SYSTEM_PROMPT documents resolution fields; parser extracts + validates them."""

from __future__ import annotations

from app.ai.pipeline import parse_response
from app.ai.prompt import SYSTEM_PROMPT


def test_system_prompt_documents_resolution_fields():
    assert "resolution_verdict" in SYSTEM_PROMPT
    assert "resolution_confidence" in SYSTEM_PROMPT
    assert "resolution_reason" in SYSTEM_PROMPT


def test_parser_extracts_resolution_fields():
    raw = """
    {
      "assignment": "existing",
      "category_id": 3,
      "subject": "Refund #44812",
      "summary": "Customer asks for refund on invoice 44812.",
      "confidence": 0.92,
      "resolution_verdict": "resolved",
      "resolution_confidence": 0.81,
      "resolution_reason": "customer thanked and closed"
    }
    """
    parsed = parse_response(raw)
    assert parsed.resolution_verdict == "resolved"
    assert parsed.resolution_confidence == 0.81
    assert parsed.resolution_reason == "customer thanked and closed"


def test_parser_treats_missing_resolution_as_null():
    raw = '{"assignment":"existing","category_id":1,"subject":"x","summary":"y","confidence":0.5}'
    parsed = parse_response(raw)
    assert parsed.resolution_verdict is None
    assert parsed.resolution_confidence is None
    assert parsed.resolution_reason is None


def test_parser_clamps_invalid_resolution_verdict_to_null():
    raw = (
        '{"assignment":"existing","category_id":1,"subject":"x","summary":"y","confidence":0.5,'
        '"resolution_verdict":"maybe","resolution_confidence":0.7}'
    )
    parsed = parse_response(raw)
    assert parsed.resolution_verdict is None


def test_parser_truncates_resolution_reason_to_120_chars():
    long = "x" * 200
    raw = (
        f'{{"assignment":"existing","category_id":1,"subject":"x","summary":"y","confidence":0.5,'
        f'"resolution_verdict":"resolved","resolution_confidence":0.7,"resolution_reason":"{long}"}}'
    )
    parsed = parse_response(raw)
    assert parsed.resolution_reason is not None
    assert len(parsed.resolution_reason) == 120


def test_system_prompt_includes_non_actionable_verdict():
    assert "non_actionable" in SYSTEM_PROMPT
    # All three verdicts present.
    for verdict in ("resolved", "non_actionable", "not_resolved"):
        assert verdict in SYSTEM_PROMPT


def test_system_prompt_documents_non_actionable_examples():
    # The prompt mentions the canonical non-actionable trigger kinds.
    body = SYSTEM_PROMPT.lower()
    for kind in ("auto-reply", "spam", "thanks"):
        assert kind in body

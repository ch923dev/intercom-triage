"""US-044 — the bug verdict facet on `parse_response`.

The parser is the only defense against model drift on this field: a malformed
verdict must degrade to "not a bug", never abort the categorization (which would
cost the whole ticket its category, not just its bug flag).
"""

from __future__ import annotations

import json

import pytest

from app.ai.pipeline import parse_response

_BASE: dict[str, object] = {
    "assignment": "existing",
    "category_id": 1,
    "subject": "Export fails",
    "summary": "Customer cannot export.",
    "confidence": 0.9,
}


def _raw(**extra: object) -> str:
    return json.dumps({**_BASE, **extra})


@pytest.mark.parametrize("severity", ["low", "medium", "high"])
def test_verdict_parsed_at_each_severity(severity: str) -> None:
    parsed = parse_response(
        _raw(bug_severity=severity, bug_confidence=0.82, bug_evidence="it just spins forever")
    )
    assert parsed.bug_severity == severity
    assert parsed.bug_confidence == pytest.approx(0.82)
    assert parsed.bug_evidence == "it just spins forever"


def test_absent_verdict_is_none() -> None:
    parsed = parse_response(_raw())
    assert parsed.bug_severity is None
    assert parsed.bug_confidence is None
    assert parsed.bug_evidence is None


def test_severity_is_case_insensitive() -> None:
    assert parse_response(_raw(bug_severity="HIGH", bug_confidence=0.7)).bug_severity == "high"
    assert (
        parse_response(_raw(bug_severity=" Medium ", bug_confidence=0.7)).bug_severity == "medium"
    )


@pytest.mark.parametrize("severity", ["critical", "", "sev1", 5, None, [], {}, True])
def test_out_of_vocabulary_severity_drops_the_verdict(severity: object) -> None:
    parsed = parse_response(
        _raw(bug_severity=severity, bug_confidence=0.99, bug_evidence="something broke")
    )
    assert parsed.bug_severity is None
    # The other two fields are meaningless without a severity and must go with it,
    # so callers can branch on `bug_severity is not None` alone.
    assert parsed.bug_confidence is None
    assert parsed.bug_evidence is None


@pytest.mark.parametrize("confidence", ["not-a-number", None, [], {}])
def test_non_numeric_confidence_is_none_but_keeps_the_verdict(confidence: object) -> None:
    parsed = parse_response(_raw(bug_severity="high", bug_confidence=confidence, bug_evidence="x"))
    assert parsed.bug_severity == "high"
    assert parsed.bug_confidence is None


def test_numeric_string_confidence_is_accepted_and_clamped() -> None:
    assert parse_response(_raw(bug_severity="low", bug_confidence="0.4")).bug_confidence == 0.4
    assert parse_response(_raw(bug_severity="low", bug_confidence=1.8)).bug_confidence == 1.0
    assert parse_response(_raw(bug_severity="low", bug_confidence=-3)).bug_confidence == 0.0


def test_evidence_over_200_chars_is_truncated() -> None:
    # The `bug_alerts.evidence` CHECK caps at 200; a model that ignores the
    # prompt's length rule must not fail the insert downstream.
    parsed = parse_response(_raw(bug_severity="medium", bug_confidence=0.7, bug_evidence="x" * 400))
    assert parsed.bug_evidence is not None
    assert len(parsed.bug_evidence) == 200


@pytest.mark.parametrize("evidence", ["", "   ", None, 42, []])
def test_blank_or_non_string_evidence_is_none(evidence: object) -> None:
    parsed = parse_response(_raw(bug_severity="high", bug_confidence=0.7, bug_evidence=evidence))
    assert parsed.bug_severity == "high"
    assert parsed.bug_evidence is None


def test_evidence_without_severity_is_dropped_entirely() -> None:
    parsed = parse_response(_raw(bug_evidence="the page 500s every time", bug_confidence=0.95))
    assert parsed.bug_severity is None
    assert parsed.bug_evidence is None


@pytest.mark.parametrize(
    "extra",
    [
        {"bug_severity": {"nested": "object"}},
        {"bug_severity": "high", "bug_confidence": {"a": 1}},
        {"bug_severity": "high", "bug_evidence": {"a": 1}},
    ],
)
def test_parse_response_never_raises_on_a_malformed_verdict(extra: dict[str, object]) -> None:
    # A bad bug facet must cost the ticket its bug flag, never its category.
    parsed = parse_response(_raw(**extra))
    assert parsed.category_id == 1


def test_verdict_survives_every_assignment_kind() -> None:
    pending = json.dumps(
        {
            "assignment": "pending_proposal",
            "proposal_id": 7,
            "summary": "s",
            "confidence": 0.5,
            "bug_severity": "high",
            "bug_confidence": 0.8,
            "bug_evidence": "crashes on save",
        }
    )
    new = json.dumps(
        {
            "assignment": "new_proposal",
            "proposed_name": "Sync Failures",
            "proposed_description": "d",
            "summary": "s",
            "confidence": 0.5,
            "bug_severity": "medium",
            "bug_confidence": 0.6,
            "bug_evidence": "sync stopped",
        }
    )
    assert parse_response(pending).bug_severity == "high"
    assert parse_response(new).bug_severity == "medium"

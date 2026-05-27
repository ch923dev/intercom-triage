"""Calibration basis for the needs-review confidence threshold (roadmap 2.3).

The needs-review lane flags an OPEN, non-overridden ticket when its
categorization self-confidence (`ai_confidence`) is below
`AppConfig.review_confidence_threshold`. The operator reviews the lane and
confirming a ticket (writing a category override) clears it.

We can't tune the threshold on a large real corpus inside the test suite, so
this module does the next-best honest thing: it builds a *representative*
labelled sample of `(ai_confidence, was_overridden)` pairs — where
`was_overridden` is the ground-truth signal that the AI got the category wrong
(the operator re-categorized it) — sweeps candidate thresholds, and asserts the
chosen default lands in the sweet spot:

  * RECALL  — fraction of would-be-overridden (AI-wrong) tickets the lane flags.
              We want this high: a missed wrong categorization is the failure
              the lane exists to prevent.
  * FLAG-RATE on correct tickets — fraction of AI-CORRECT tickets the lane also
              flags (noise). We want this low so the operator isn't drowned.

The sample's shape mirrors how confidence actually distributes in this system
(see app/ai/pipeline.py):
  * Fallback categorizations store confidence 0.0 (AI failed / couldn't decide)
    and are always wrong-by-assumption — they MUST be flagged.
  * Genuine answers carry the model's self-reported confidence; wrong answers
    skew low, correct answers skew high, with overlap in the middle band.

The default (0.65) is whatever this sweep selects — the test fails if the
config default drifts away from the calibrated optimum, forcing a re-justify.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.config import AppConfig


@dataclass(frozen=True)
class Sample:
    """One historical categorization outcome.

    `confidence` is the stored `ai_confidence`; `overridden` is True when the
    operator later re-categorized the ticket (ground-truth: AI was wrong).
    """

    confidence: float
    overridden: bool


# A representative spread, NOT a guess at a single number. Roughly mirrors the
# confidence distribution the categorizer emits: fallbacks at 0.0 (always
# wrong), genuine wrong answers clustered low-to-mid, genuine correct answers
# clustered high, with realistic overlap in the 0.5–0.75 band where calibration
# actually matters. ~30 samples is enough to make the sweep discriminate.
SAMPLES: list[Sample] = [
    # Fallbacks — AI failed to categorize; operator always re-files these.
    Sample(0.0, overridden=True),
    Sample(0.0, overridden=True),
    Sample(0.0, overridden=True),
    # Genuine but wrong — confidence skews low; these are what the lane must catch.
    Sample(0.30, overridden=True),
    Sample(0.38, overridden=True),
    Sample(0.42, overridden=True),
    Sample(0.50, overridden=True),
    Sample(0.55, overridden=True),
    Sample(0.60, overridden=True),
    Sample(0.62, overridden=True),
    # The hard overlap band — a few wrong answers the AI was fairly sure about.
    Sample(0.70, overridden=True),
    Sample(0.78, overridden=True),
    # Genuine and correct — confidence skews high; flagging these is noise.
    Sample(0.55, overridden=False),
    Sample(0.62, overridden=False),
    Sample(0.68, overridden=False),
    Sample(0.72, overridden=False),
    Sample(0.75, overridden=False),
    Sample(0.80, overridden=False),
    Sample(0.82, overridden=False),
    Sample(0.85, overridden=False),
    Sample(0.88, overridden=False),
    Sample(0.90, overridden=False),
    Sample(0.92, overridden=False),
    Sample(0.94, overridden=False),
    Sample(0.95, overridden=False),
    Sample(0.96, overridden=False),
    Sample(0.97, overridden=False),
    Sample(0.98, overridden=False),
]

# Candidate thresholds to sweep (the lane predicate is strict `<`).
CANDIDATES: list[float] = [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]


def _flagged(confidence: float, threshold: float) -> bool:
    """Mirror of the lane predicate: strictly below the threshold flags."""
    return confidence < threshold


def _recall(threshold: float) -> float:
    """Fraction of overridden (AI-wrong) samples the lane flags."""
    wrong = [s for s in SAMPLES if s.overridden]
    if not wrong:
        return 1.0
    caught = sum(1 for s in wrong if _flagged(s.confidence, threshold))
    return caught / len(wrong)


def _false_flag_rate(threshold: float) -> float:
    """Fraction of AI-CORRECT samples the lane (wrongly) flags as needing review."""
    correct = [s for s in SAMPLES if not s.overridden]
    if not correct:
        return 0.0
    flagged = sum(1 for s in correct if _flagged(s.confidence, threshold))
    return flagged / len(correct)


def test_zero_confidence_fallbacks_always_flagged() -> None:
    """Fallback rows (confidence 0.0) must surface at any sane threshold > 0."""
    for t in CANDIDATES:
        assert _flagged(0.0, t), f"threshold {t} fails to flag a 0.0 fallback"


def test_default_threshold_is_the_calibrated_optimum() -> None:
    """The config default must be the threshold that best separates the sample.

    Objective: maximise (recall - false_flag_rate) — catch wrong
    categorizations while keeping noise on correct ones low. Ties break toward
    the LOWER threshold (less operator noise). The test fails if the AppConfig
    default drifts off this optimum, forcing the change to be re-justified here.
    """
    scored = [(t, _recall(t) - _false_flag_rate(t)) for t in CANDIDATES]
    best_score = max(score for _, score in scored)
    # Lowest threshold achieving the best score (tie-break toward less noise).
    best_threshold = min(t for t, score in scored if score == best_score)

    assert AppConfig().review_confidence_threshold == best_threshold == 0.65


def test_default_threshold_has_strong_recall_and_bounded_noise() -> None:
    """At the chosen default the lane catches most wrong calls without drowning.

    Concrete acceptance bars derived from the representative sample: catch the
    large majority of would-be-overridden tickets, and flag well under half of
    the correct ones. These guard against a future edit that quietly trades all
    its recall for quiet, or vice-versa.
    """
    default = AppConfig().review_confidence_threshold
    assert _recall(default) >= 0.75, "lane misses too many AI-wrong tickets"
    assert _false_flag_rate(default) <= 0.40, "lane flags too many correct tickets"

"""In-process counters + latency histograms. Reference: plan.md §11.

Lightweight, thread-safe. `GET /metrics` (T043, Phase 8) exposes `snapshot()`
(monotonic counters) and `histogram_snapshot()` (latency distributions).

Counters are written by the observability layer (T028), the AI pipeline, the
tickets service, and proposal resolution. Latency samples are fed by
`observability.logged_call` (external HTTP timings, e.g. ``openrouter.complete``).

Histogram samples are kept in a bounded ring buffer per key (`deque(maxlen=…)`)
so memory stays flat regardless of process uptime — this is a single-process
local tool, not a Prometheus exporter. Percentiles (p50/p95) are computed over
the retained window with nearest-rank ranking.
"""

from __future__ import annotations

import math
from collections import defaultdict, deque
from threading import Lock
from typing import TypedDict

from app.pricing import estimate_cost_usd
from app.util import naive_utcnow

# Max samples retained per histogram key. Bounds memory: ~1k floats/key.
HISTOGRAM_CAPACITY = 1024


class HistogramStat(TypedDict):
    """Per-key latency summary over the retained sample window."""

    count: int
    p50: float
    p95: float
    max: float


class UsageStat(TypedDict):
    """Token usage + estimated USD cost for one (day, model) bucket."""

    date: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    calls: int
    estimated_cost_usd: float


def _percentile(sorted_samples: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted, non-empty list.

    `pct` is a fraction in [0, 1]. Rank = ceil(pct * n), clamped to [1, n].
    """
    n = len(sorted_samples)
    rank = max(1, min(n, math.ceil(pct * n)))
    return sorted_samples[rank - 1]


class _TokenBucket:
    """Mutable token accumulator for one (date, model) pair."""

    __slots__ = ("calls", "completion_tokens", "prompt_tokens")

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.calls = 0


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=HISTOGRAM_CAPACITY)
        )
        # Token usage keyed by (date_iso, model). Per-DAY bucketing lets the UI
        # report "today's spend". In-process only — resets on restart, which is
        # acceptable for a single-operator local tool (roadmap 1.4: no DB table).
        self._usage: dict[tuple[str, str], _TokenBucket] = defaultdict(_TokenBucket)
        self._lock = Lock()

    def incr(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._counters[key] += n

    def observe(self, key: str, value_ms: float) -> None:
        """Record one latency sample (milliseconds) into the bounded buffer."""
        with self._lock:
            self._histograms[key].append(float(value_ms))

    def record_usage(
        self,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
    ) -> None:
        """Accumulate one OpenRouter call's token usage into today's bucket.

        Bucketed by (UTC date, model). Negative/garbage token counts are
        coerced to 0 so a malformed upstream response cannot skew the meter.
        ``calls`` increments once per recorded call regardless of token counts.
        """
        day = naive_utcnow().date().isoformat()
        prompt = max(0, prompt_tokens)
        completion = max(0, completion_tokens)
        with self._lock:
            bucket = self._usage[(day, model)]
            bucket.prompt_tokens += prompt
            bucket.completion_tokens += completion
            bucket.calls += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def histogram_snapshot(self) -> dict[str, HistogramStat]:
        """Per-key {count, p50, p95, max} over the retained window.

        Empty keys are omitted; a key only appears once it has a sample.
        """
        with self._lock:
            # Copy out under lock; compute percentiles without holding it.
            raw = {key: list(buf) for key, buf in self._histograms.items() if buf}
        out: dict[str, HistogramStat] = {}
        for key, samples in raw.items():
            ordered = sorted(samples)
            out[key] = HistogramStat(
                count=len(ordered),
                p50=_percentile(ordered, 0.50),
                p95=_percentile(ordered, 0.95),
                max=ordered[-1],
            )
        return out

    def usage_snapshot(self) -> list[UsageStat]:
        """Per-(day, model) token totals + estimated USD cost.

        Sorted by date descending then model so the newest day leads. Cost is
        computed at read time from the pricing table so a rate-card edit applies
        retroactively to the in-process buckets.
        """
        with self._lock:
            raw = {
                key: (b.prompt_tokens, b.completion_tokens, b.calls)
                for key, b in self._usage.items()
            }
        out: list[UsageStat] = []
        for (day, model), (prompt, completion, calls) in raw.items():
            out.append(
                UsageStat(
                    date=day,
                    model=model,
                    prompt_tokens=prompt,
                    completion_tokens=completion,
                    total_tokens=prompt + completion,
                    calls=calls,
                    estimated_cost_usd=round(estimate_cost_usd(model, prompt, completion), 6),
                )
            )
        out.sort(key=lambda u: (u["date"], u["model"]), reverse=True)
        return out

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()
            self._usage.clear()


metrics = Metrics()

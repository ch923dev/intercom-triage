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

# Max samples retained per histogram key. Bounds memory: ~1k floats/key.
HISTOGRAM_CAPACITY = 1024


class HistogramStat(TypedDict):
    """Per-key latency summary over the retained sample window."""

    count: int
    p50: float
    p95: float
    max: float


def _percentile(sorted_samples: list[float], pct: float) -> float:
    """Nearest-rank percentile over an already-sorted, non-empty list.

    `pct` is a fraction in [0, 1]. Rank = ceil(pct * n), clamped to [1, n].
    """
    n = len(sorted_samples)
    rank = max(1, min(n, math.ceil(pct * n)))
    return sorted_samples[rank - 1]


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._histograms: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=HISTOGRAM_CAPACITY)
        )
        self._lock = Lock()

    def incr(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._counters[key] += n

    def observe(self, key: str, value_ms: float) -> None:
        """Record one latency sample (milliseconds) into the bounded buffer."""
        with self._lock:
            self._histograms[key].append(float(value_ms))

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

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._histograms.clear()


metrics = Metrics()

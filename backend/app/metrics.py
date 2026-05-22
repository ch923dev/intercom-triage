"""In-process counters. Reference: plan.md §11.

Lightweight, thread-safe. `GET /metrics` (T043, Phase 8) will expose `snapshot()`.
Used here by the observability layer (T028) and the AI pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from threading import Lock


class Metrics:
    def __init__(self) -> None:
        self._counters: dict[str, int] = defaultdict(int)
        self._lock = Lock()

    def incr(self, key: str, n: int = 1) -> None:
        with self._lock:
            self._counters[key] += n

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counters)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()


metrics = Metrics()

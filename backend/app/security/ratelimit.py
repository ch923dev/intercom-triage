"""In-process fixed-window rate limiter for /auth/login.

Single-process only (matches the single-backend deploy). Not distributed — a
multi-replica deploy would move this to Redis, out of scope for Phase 1.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class FixedWindowLimiter:
    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._now = now
        self._buckets: dict[str, tuple[float, int]] = {}  # key -> (window_start, count)

    def _evict(self, now: float) -> None:
        """Drop buckets whose window has fully elapsed — bounds memory so a
        spray of distinct keys can't grow the dict without limit."""
        stale = [k for k, (start, _) in self._buckets.items() if now - start >= self._window]
        for k in stale:
            del self._buckets[k]

    def allow(self, key: str) -> bool:
        """Record an attempt; return False once the window cap is exceeded."""
        now = self._now()
        self._evict(now)
        start, count = self._buckets.get(key, (now, 0))
        if now - start >= self._window:
            start, count = now, 0
        count += 1
        self._buckets[key] = (start, count)
        return count <= self._max

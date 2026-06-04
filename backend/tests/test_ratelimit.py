"""Phase 1 — fixed-window login limiter."""

from __future__ import annotations

from app.security.ratelimit import FixedWindowLimiter


def test_allows_up_to_max_then_blocks() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowLimiter(max_attempts=3, window_seconds=60, now=lambda: clock["t"])
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False  # 4th in the window


def test_window_resets() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowLimiter(max_attempts=1, window_seconds=60, now=lambda: clock["t"])
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    clock["t"] += 61
    assert limiter.allow("k") is True


def test_keys_are_independent() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowLimiter(max_attempts=1, window_seconds=60, now=lambda: clock["t"])
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True

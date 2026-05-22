"""Small shared helpers."""

from __future__ import annotations

from datetime import UTC, datetime


def naive_utcnow() -> datetime:
    """Naive UTC `now` — matches the naive `DateTime` columns used in the schema."""
    return datetime.now(UTC).replace(tzinfo=None)

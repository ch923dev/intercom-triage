from __future__ import annotations

from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.schemas import BulkParkRequest, ParkRequest
from app.util import naive_utcnow


def test_park_request_accepts_future_until() -> None:
    req = ParkRequest(until_at=naive_utcnow() + timedelta(hours=1), reason="waiting_on_customer")
    assert req.reason == "waiting_on_customer"


def test_park_request_rejects_past_until() -> None:
    with pytest.raises(ValidationError):
        ParkRequest(until_at=naive_utcnow() - timedelta(hours=1), reason="other")


def test_park_request_rejects_bad_reason() -> None:
    with pytest.raises(ValidationError):
        ParkRequest(until_at=naive_utcnow() + timedelta(hours=1), reason="nope")


def test_bulk_park_request_carries_ids_and_fields() -> None:
    req = BulkParkRequest(
        ticket_ids=["a", "b"],
        until_at=naive_utcnow() + timedelta(days=1),
        reason="waiting_internal",
    )
    assert req.ticket_ids == ["a", "b"]

"""Schema-level tests for the bulk request/response envelopes.

Tasks: T074. Schemas live in `app/schemas.py`; the cap constant lives in
`app/config.py` so endpoints and schemas share one source of truth.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from app.config import MAX_BULK_IDS
from app.schemas import (
    BulkCategoryUpdate,
    BulkFollowupSet,
    BulkResult,
    BulkTicketIds,
)


class TestBulkTicketIds:
    def test_accepts_single_id(self) -> None:
        body = BulkTicketIds(ticket_ids=["t1"])
        assert body.ticket_ids == ["t1"]

    def test_rejects_empty_array(self) -> None:
        with pytest.raises(ValidationError):
            BulkTicketIds(ticket_ids=[])

    def test_accepts_exactly_max(self) -> None:
        ids = [f"t{i}" for i in range(MAX_BULK_IDS)]
        body = BulkTicketIds(ticket_ids=ids)
        assert len(body.ticket_ids) == MAX_BULK_IDS

    def test_rejects_over_max(self) -> None:
        ids = [f"t{i}" for i in range(MAX_BULK_IDS + 1)]
        with pytest.raises(ValidationError):
            BulkTicketIds(ticket_ids=ids)


class TestBulkCategoryUpdate:
    def test_requires_category_id(self) -> None:
        with pytest.raises(ValidationError):
            BulkCategoryUpdate(ticket_ids=["t1"])  # type: ignore[call-arg]

    def test_happy_path(self) -> None:
        body = BulkCategoryUpdate(ticket_ids=["t1", "t2"], category_id=7)
        assert body.category_id == 7
        assert body.ticket_ids == ["t1", "t2"]

    def test_rejects_empty_ticket_ids(self) -> None:
        with pytest.raises(ValidationError):
            BulkCategoryUpdate(ticket_ids=[], category_id=7)

    def test_rejects_over_max(self) -> None:
        ids = [f"t{i}" for i in range(MAX_BULK_IDS + 1)]
        with pytest.raises(ValidationError):
            BulkCategoryUpdate(ticket_ids=ids, category_id=7)


class TestBulkFollowupSet:
    def test_happy_path(self) -> None:
        body = BulkFollowupSet(
            ticket_ids=["t1"],
            due_at=datetime(2026, 1, 1, 12, 0, 0),
            reason="check in",
        )
        assert body.reason == "check in"

    def test_reason_optional(self) -> None:
        body = BulkFollowupSet(
            ticket_ids=["t1"],
            due_at=datetime(2026, 1, 1, 12, 0, 0),
        )
        assert body.reason is None

    def test_reason_max_80_chars(self) -> None:
        with pytest.raises(ValidationError):
            BulkFollowupSet(
                ticket_ids=["t1"],
                due_at=datetime(2026, 1, 1, 12, 0, 0),
                reason="x" * 81,
            )


class TestBulkResult:
    def test_empty_failed(self) -> None:
        result = BulkResult(ok_ids=["t1", "t2"], failed=[])
        assert result.ok_ids == ["t1", "t2"]
        assert result.failed == []

    def test_mixed_ok_and_failed(self) -> None:
        result = BulkResult(
            ok_ids=["t1"],
            failed=[{"id": "t2", "reason": "already resolved"}],
        )
        assert result.failed[0].id == "t2"
        assert result.failed[0].reason == "already resolved"

    def test_empty_ok_ids_allowed(self) -> None:
        result = BulkResult(
            ok_ids=[],
            failed=[{"id": "t1", "reason": "unknown ticket"}],
        )
        assert result.ok_ids == []
        assert len(result.failed) == 1


def test_max_bulk_ids_default() -> None:
    """The default cap is 200 per plan §8d / FR-036."""
    assert MAX_BULK_IDS == 200

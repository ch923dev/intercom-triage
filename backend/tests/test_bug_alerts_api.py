"""US-044 — `GET /bug-alerts` + `POST /bug-alerts/{id}/dismiss`."""

from __future__ import annotations

from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import BugAlert, Ticket
from app.util import naive_utcnow


async def _seed(session: AsyncSession, ticket_id: str, severity: str, **overrides: Any) -> None:
    now = naive_utcnow()
    session.add(
        Ticket(
            id=ticket_id,
            title=f"Ticket {ticket_id}",
            url=f"https://app.intercom.com/a/apps/x/conversations/{ticket_id}",
            created_at=now,
            updated_at=now,
            category_id=1,
            summary="s",
        )
    )
    fields: dict[str, Any] = {
        "ticket_id": ticket_id,
        "severity": severity,
        "confidence": 0.9,
        "evidence": "it never finishes loading",
        "first_detected_at": now,
        "last_detected_at": now,
    }
    fields.update(overrides)
    session.add(BugAlert(**fields))
    await session.commit()


@pytest.mark.asyncio
async def test_unauthenticated_read_is_401(unauth_client: AsyncClient) -> None:
    assert (await unauth_client.get("/bug-alerts")).status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_dismiss_is_401(unauth_client: AsyncClient) -> None:
    assert (await unauth_client.post("/bug-alerts/T1/dismiss")).status_code == 401


@pytest.mark.asyncio
async def test_list_returns_alerts_with_ticket_context(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed(session, "T1", "high")

    resp = await client.get("/bug-alerts")
    assert resp.status_code == 200
    [row] = resp.json()
    assert row["ticket_id"] == "T1"
    assert row["severity"] == "high"
    assert row["evidence"] == "it never finishes loading"
    assert row["occurrences"] == 1
    assert row["posted_at"] is None
    assert row["title"] == "Ticket T1"
    assert "conversations/T1" in row["url"]
    # Naive UTC in the DB, Z-suffixed on the wire.
    assert row["first_detected_at"].endswith("Z")


@pytest.mark.asyncio
async def test_list_is_ordered_worst_first(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, "T-low", "low")
    await _seed(session, "T-high", "high")
    await _seed(session, "T-med", "medium")

    rows = (await client.get("/bug-alerts")).json()
    assert [r["ticket_id"] for r in rows] == ["T-high", "T-med", "T-low"]


@pytest.mark.asyncio
async def test_severity_filter(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, "T-low", "low")
    await _seed(session, "T-high", "high")

    rows = (await client.get("/bug-alerts", params={"severity": "high"})).json()
    assert [r["ticket_id"] for r in rows] == ["T-high"]


@pytest.mark.asyncio
async def test_an_unknown_severity_is_rejected(client: AsyncClient) -> None:
    assert (await client.get("/bug-alerts", params={"severity": "critical"})).status_code == 422


@pytest.mark.asyncio
async def test_delivered_filter(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, "T-new", "high")
    await _seed(
        session, "T-sent", "high", posted_at=naive_utcnow(), posted_severity="high", slack_ts="1.1"
    )

    undelivered = (await client.get("/bug-alerts", params={"delivered": "false"})).json()
    assert [r["ticket_id"] for r in undelivered] == ["T-new"]
    delivered = (await client.get("/bug-alerts", params={"delivered": "true"})).json()
    assert [r["ticket_id"] for r in delivered] == ["T-sent"]


@pytest.mark.asyncio
async def test_dismiss_sets_the_timestamp(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, "T1", "high")

    resp = await client.post("/bug-alerts/T1/dismiss")
    assert resp.status_code == 200
    assert resp.json()["dismissed_at"] is not None

    row = await session.get(BugAlert, "T1")
    assert row is not None
    await session.refresh(row)
    assert row.dismissed_at is not None


@pytest.mark.asyncio
async def test_dismiss_is_idempotent(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, "T1", "high")
    first = (await client.post("/bug-alerts/T1/dismiss")).json()["dismissed_at"]
    second = (await client.post("/bug-alerts/T1/dismiss")).json()["dismissed_at"]
    assert first == second


@pytest.mark.asyncio
async def test_dismiss_on_an_unknown_ticket_is_404(client: AsyncClient) -> None:
    assert (await client.post("/bug-alerts/nope/dismiss")).status_code == 404


@pytest.mark.asyncio
async def test_health_reports_slack_unconfigured_without_degrading(client: AsyncClient) -> None:
    """An unconfigured Slack is a disabled feature, not a degraded service — it
    must not appear in `missing_secrets` or flip `status`."""
    body = (await client.get("/health")).json()
    assert body["slack_configured"] is False
    assert "SLACK_BOT_TOKEN" not in body["missing_secrets"]

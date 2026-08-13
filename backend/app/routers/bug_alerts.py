"""Bug-alert endpoints (US-044). Reference: FR-076, FR-079.

Read-and-dismiss only. Alerts are produced by the ingest pipeline and consumed
by the Slack delivery loop; there is no create/update surface, because an
operator-authored "bug alert" would not be an AI detection.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.schemas import BugAlertRead, BugSeverity
from app.services import bug_alerts as svc

router = APIRouter(prefix="/bug-alerts", tags=["bug-alerts"])


@router.get("", response_model=list[BugAlertRead])
async def list_bug_alerts(
    severity: BugSeverity | None = Query(default=None),
    delivered: bool | None = Query(default=None),
    session: AsyncSession = Depends(get_session),
) -> list[BugAlertRead]:
    """Every recorded alert, worst first. This is the calibration surface — it
    includes `low` and dismissed rows on purpose."""
    return await svc.list_bug_alerts(session, severity=severity, delivered=delivered)


@router.post("/{ticket_id}/dismiss", response_model=BugAlertRead)
async def dismiss_bug_alert(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> BugAlertRead:
    """Mark an alert as not-a-bug / handled. Idempotent; survives re-detection."""
    return await svc.dismiss_bug_alert(session, ticket_id)

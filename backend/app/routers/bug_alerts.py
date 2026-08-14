"""Bug-alert endpoints (US-044, US-046). Reference: FR-076, FR-079, FR-084..088.

Read, dismiss, acknowledge. Alerts are produced by the ingest pipeline and
consumed by the Slack delivery loop; there is no create/update surface, because
an operator-authored "bug alert" would not be an AI detection.

Every route here is inbound from our own webapp and authenticated. Nothing on
this router accepts a request from Slack: acknowledgement travels outward via
`chat.update` (FR-088), so there is no interactivity endpoint to sign, and no
addition to the auth allowlist (invariant #15).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.slack import SlackClient
from app.config import AppConfig
from app.db import get_session
from app.deps import CurrentUser, get_app_config, get_current_user, get_slack
from app.schemas import BugAlertAckResult, BugAlertRead, BugNoteRequest, BugSeverity, SimilarBug
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


@router.post("/{ticket_id}/ack", response_model=BugAlertAckResult)
async def ack_bug_alert(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
    slack: SlackClient | None = Depends(get_slack),
    config: AppConfig = Depends(get_app_config),
) -> BugAlertAckResult:
    """Acknowledge an alert and mirror it into its Slack message.

    The acknowledger is the authenticated caller — never a client-supplied id,
    so "who owns this" cannot be forged. Idempotent.

    `slack_updated=False` alongside a set `acked_at` is a success, not an error:
    the alert was never announced, Slack is off, or the edit failed. The
    acknowledgement is committed either way (FR-087).
    """
    alert, slack_updated = await svc.ack_bug_alert(
        session, ticket_id, user_id=user.id, slack=slack, config=config
    )
    return BugAlertAckResult(alert=alert, slack_updated=slack_updated)


@router.put("/{ticket_id}/note", response_model=BugAlertRead)
async def set_bug_note(
    ticket_id: str,
    body: BugNoteRequest,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> BugAlertRead:
    """Write the incident record: root cause, workaround, what was done.

    An empty note clears it. The caller becomes the note's most recent author —
    the board is team-wide, so any operator may correct another's note.
    """
    return await svc.set_bug_note(session, ticket_id, note=body.note, user_id=user.id)


@router.get("/{ticket_id}/similar", response_model=list[SimilarBug])
async def similar_bugs(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
) -> list[SimilarBug]:
    """Earlier noted bugs whose symptom resembles this one's, best first.

    Recomputed per request, so a note written after this alert was announced
    still reaches whoever opens it (FR-092). Empty — not an error — when semantic
    matching is unavailable or nothing clears the similarity floor.
    """
    return await svc.similar_noted_bugs(session, ticket_id)

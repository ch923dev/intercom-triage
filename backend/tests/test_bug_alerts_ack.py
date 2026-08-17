"""US-046 — acknowledgement: state, idempotency, the Slack mirror, durability.

Reference: FR-084..FR-088, plan.md §22, tasks.md T183/T184/T185.

`AppConfig` here is always built explicitly rather than taken from the `app`
fixture: `test_config` pins Slack OFF on purpose, and a test that let Slack
settings leak in from the developer's `.env` would aim a fake at a real channel
on that machine only.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.pipeline import CategorizationResult
from app.config import AppConfig
from app.models import BugAlert, Ticket
from app.services.bug_alerts import ack_bug_alert, record_bug_alerts
from app.util import naive_utcnow


class FakeSlack:
    """Records `chat.update` calls. `post_message` is present but unused here —
    an acknowledgement must never post a NEW message (FR-086), and a test that
    could not tell the difference would not catch it if one did."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.updates: list[dict[str, Any]] = []
        self.posts: list[dict[str, Any]] = []
        self.fail_with = fail_with

    async def update_message(
        self,
        *,
        channel: str,
        ts: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        ticket_id: str | None = None,
    ) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        self.updates.append(
            {
                "channel": channel,
                "ts": ts,
                "text": text,
                "attachments": attachments,
                "ticket_id": ticket_id,
            }
        )
        return ts

    async def post_message(self, **kwargs: Any) -> str:
        self.posts.append(kwargs)
        return "ts-new"


def _config(**overrides: object) -> AppConfig:
    fields: dict[str, object] = {
        "database_url": "sqlite+aiosqlite:///:memory:",
        "session_jwt_secret": "test-session-secret",
        "bug_alerts_enabled": True,
        "slack_bot_token": "xoxb-test",
        "slack_bug_channel": "C-bugs",
        "bug_alert_min_severity": "medium",
    }
    fields.update(overrides)
    return AppConfig(**fields)  # type: ignore[arg-type]


_EVIDENCE = "the export button does nothing at all"


async def _seed(
    session: AsyncSession,
    ticket_id: str = "T1",
    *,
    announced: bool = True,
    **overrides: Any,
) -> BugAlert:
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
        "severity": "high",
        "confidence": 0.9,
        "evidence": _EVIDENCE,
        "first_detected_at": now,
        "last_detected_at": now,
    }
    if announced:
        fields |= {
            "posted_at": now,
            "posted_severity": "high",
            "slack_channel": "C-bugs",
            "slack_ts": "1786606832.587139",
        }
    fields.update(overrides)
    alert = BugAlert(**fields)
    session.add(alert)
    await session.commit()
    return alert


# ── State + API ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_ack_is_401(unauth_client: AsyncClient) -> None:
    assert (await unauth_client.post("/bug-alerts/T1/ack")).status_code == 401


@pytest.mark.asyncio
async def test_ack_on_unknown_alert_is_404(client: AsyncClient) -> None:
    assert (await client.post("/bug-alerts/nope/ack")).status_code == 404


@pytest.mark.asyncio
async def test_ack_records_the_authenticated_operator(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed(session)

    resp = await client.post("/bug-alerts/T1/ack")
    assert resp.status_code == 200
    body = resp.json()

    assert body["alert"]["acked_at"] is not None
    # Named, not a bare id the client would have to resolve (invariant #17).
    assert body["alert"]["acked_by"] == {"id": 1, "name": "Seed Operator"}
    # Slack is unconfigured in the app fixture, so the mirror is honestly false
    # while the acknowledgement itself succeeded.
    assert body["slack_updated"] is False


@pytest.mark.asyncio
async def test_ack_shows_up_on_the_list(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session)
    await client.post("/bug-alerts/T1/ack")

    [row] = (await client.get("/bug-alerts")).json()
    assert row["acked_at"] is not None
    assert row["acked_by"]["name"] == "Seed Operator"


@pytest.mark.asyncio
async def test_listing_an_unacked_alert_does_not_break_on_the_userref(
    client: AsyncClient, session: AsyncSession
) -> None:
    """The read path builds `BugAlertRead` explicitly because the column is an
    int and the field is a `UserRef`; attribute validation would raise here."""
    await _seed(session)
    [row] = (await client.get("/bug-alerts")).json()
    assert row["acked_by"] is None
    assert row["acked_at"] is None


@pytest.mark.asyncio
async def test_ack_and_dismiss_are_independent(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session)

    await client.post("/bug-alerts/T1/ack")
    dismissed = (await client.post("/bug-alerts/T1/dismiss")).json()

    # Closing it out must not erase who picked it up.
    assert dismissed["dismissed_at"] is not None
    assert dismissed["acked_at"] is not None
    assert dismissed["acked_by"]["id"] == 1


@pytest.mark.asyncio
async def test_the_ack_pair_cannot_be_half_set(session: AsyncSession) -> None:
    """`acked_at` without `acked_by` is unstorable (FR-085) — CHECK, not code."""
    await _seed(session, "T-pair", announced=False)
    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE bug_alerts SET acked_at = :now WHERE ticket_id = 'T-pair'"),
            {"now": naive_utcnow()},
        )
        await session.commit()
    await session.rollback()


# ── The Slack mirror ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ack_edits_the_original_message_rather_than_posting(
    session: AsyncSession,
) -> None:
    await _seed(session)
    slack = FakeSlack()

    _, updated = await ack_bug_alert(
        session,
        "T1",
        user_id=1,
        slack=slack,
        config=_config(),  # type: ignore[arg-type]
    )

    assert updated is True
    assert slack.posts == []  # a second message would double-notify the channel
    [call] = slack.updates
    # The coordinates come from the row we stored when we posted, so an edit can
    # only ever touch our own message.
    assert call["channel"] == "C-bugs"
    assert call["ts"] == "1786606832.587139"


@pytest.mark.asyncio
async def test_the_edited_card_names_the_acknowledger(session: AsyncSession) -> None:
    await _seed(session)
    slack = FakeSlack()

    await ack_bug_alert(
        session,
        "T1",
        user_id=1,
        slack=slack,
        config=_config(),  # type: ignore[arg-type]
    )

    card = json.dumps(slack.updates[0]["attachments"])
    assert "Acknowledged by Seed Operator" in card
    # The rest of the card survives the edit — it is rebuilt by the same builder.
    assert "HIGH bug" in card


@pytest.mark.asyncio
async def test_the_edit_keeps_the_evidence_quote_out_of_the_preview(
    session: AsyncSession,
) -> None:
    """NFR-016 on the edit path, not just the post path: `text` and the
    attachment `fallback` both surface in push notifications."""
    await _seed(session)
    slack = FakeSlack()

    await ack_bug_alert(
        session,
        "T1",
        user_id=1,
        slack=slack,
        config=_config(),  # type: ignore[arg-type]
    )

    call = slack.updates[0]
    assert _EVIDENCE not in call["text"]
    assert _EVIDENCE not in (call["attachments"][0]["fallback"])
    # It IS still on the card itself — that is the point of the alert.
    assert _EVIDENCE in json.dumps(call["attachments"][0]["blocks"])


@pytest.mark.asyncio
async def test_a_second_ack_changes_nothing_and_does_not_re_poke_slack(
    session: AsyncSession,
) -> None:
    await _seed(session)
    slack = FakeSlack()
    config = _config()

    first, _ = await ack_bug_alert(
        session,
        "T1",
        user_id=1,
        slack=slack,
        config=config,  # type: ignore[arg-type]
    )
    second, updated = await ack_bug_alert(
        session,
        "T1",
        user_id=2,
        slack=slack,
        config=config,  # type: ignore[arg-type]
    )

    assert second.acked_at == first.acked_at
    assert second.acked_by is not None and second.acked_by.id == 1  # not user 2
    assert updated is False
    assert len(slack.updates) == 1


@pytest.mark.asyncio
async def test_a_slack_failure_leaves_the_ack_standing(session: AsyncSession) -> None:
    """FR-087 — the board is the record; the channel is a projection of it."""
    await _seed(session)
    slack = FakeSlack(fail_with=RuntimeError("slack down"))

    alert, updated = await ack_bug_alert(
        session,
        "T1",
        user_id=1,
        slack=slack,
        config=_config(),  # type: ignore[arg-type]
    )

    assert updated is False
    assert alert.acked_at is not None
    stored = await session.get(BugAlert, "T1")
    assert stored is not None and stored.acked_at is not None


@pytest.mark.asyncio
async def test_a_never_announced_alert_acks_with_no_outward_call(
    session: AsyncSession,
) -> None:
    await _seed(session, "T-quiet", announced=False)
    slack = FakeSlack()

    alert, updated = await ack_bug_alert(
        session,
        "T-quiet",
        user_id=1,
        slack=slack,
        config=_config(),  # type: ignore[arg-type]
    )

    assert alert.acked_at is not None
    assert updated is False
    assert slack.updates == []


@pytest.mark.asyncio
async def test_no_slack_client_still_acks(session: AsyncSession) -> None:
    await _seed(session)
    alert, updated = await ack_bug_alert(session, "T1", user_id=1, slack=None, config=_config())
    assert alert.acked_at is not None
    assert updated is False


# ── Durability against the model ──────────────────────────────────────────────


def _verdict(severity: str) -> dict[str, CategorizationResult]:
    return {
        "T1": CategorizationResult(
            category_id=1,
            proposal_id=None,
            summary="Export is broken.",
            confidence=0.8,
            subject="Export broken",
            bug_severity=severity,  # type: ignore[arg-type]
            bug_confidence=0.9,
            bug_evidence=_EVIDENCE,
        )
    }


@pytest.mark.asyncio
async def test_re_detection_does_not_clear_the_ack(session: AsyncSession) -> None:
    """FR-085 — a model that keeps re-reporting cannot un-acknowledge."""
    await _seed(session)
    await ack_bug_alert(session, "T1", user_id=1, slack=None, config=_config())

    await record_bug_alerts(session, _verdict("high"), _config())

    # The upsert runs as SQL, so re-read rather than trusting the identity map.
    stored = await session.get(BugAlert, "T1")
    assert stored is not None
    await session.refresh(stored)
    assert stored.acked_at is not None
    assert stored.acked_by == 1
    assert stored.occurrences == 2  # the re-detection DID land


@pytest.mark.asyncio
async def test_escalation_does_not_clear_the_ack(session: AsyncSession) -> None:
    """Ownership is not revoked by the bug getting worse (plan §22)."""
    await _seed(session, severity="medium", posted_severity="medium")
    await ack_bug_alert(session, "T1", user_id=1, slack=None, config=_config())

    await record_bug_alerts(session, _verdict("high"), _config())

    stored = (
        await session.scalars(
            select(BugAlert)
            .where(BugAlert.ticket_id == "T1")
            .execution_options(populate_existing=True)
        )
    ).one()
    assert stored.severity == "high"  # the escalation DID land
    assert stored.acked_at is not None
    assert stored.acked_by == 1

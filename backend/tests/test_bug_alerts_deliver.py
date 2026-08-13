"""US-044 — delivery: ordering, dedup, escalation-as-thread, failure safety."""

from __future__ import annotations

import json
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.models import BugAlert, Ticket
from app.services.bug_alerts import deliver_pending_bug_alerts
from app.util import naive_utcnow


class FakeSlack:
    """Records what would have been posted; returns a distinct `ts` per call."""

    def __init__(self, fail_with: Exception | None = None) -> None:
        self.posts: list[dict[str, Any]] = []
        self.fail_with = fail_with

    async def post_message(
        self,
        *,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        attachments: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
        ticket_id: str | None = None,
    ) -> str:
        if self.fail_with is not None:
            raise self.fail_with
        self.posts.append(
            {
                "channel": channel,
                "text": text,
                "blocks": blocks,
                "attachments": attachments,
                "thread_ts": thread_ts,
                "ticket_id": ticket_id,
            }
        )
        return f"ts-{len(self.posts)}"


def rendered(post: dict[str, Any]) -> str:
    """Flatten a recorded post's card into one searchable string.

    The card lives inside a severity-coloured attachment, so a test asserting on
    what an operator SEES should not have to know that nesting.
    """
    return json.dumps(post.get("attachments") or post.get("blocks") or [])


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


async def _seed(
    session: AsyncSession,
    ticket_id: str,
    severity: str,
    **overrides: object,
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
        "severity": severity,
        "confidence": 0.9,
        "evidence": "it never finishes loading",
        "first_detected_at": now,
        "last_detected_at": now,
    }
    fields.update(overrides)
    alert = BugAlert(**fields)
    session.add(alert)
    await session.commit()
    return alert


@pytest.mark.asyncio
async def test_undelivered_alerts_post_worst_first(session: AsyncSession) -> None:
    await _seed(session, "T-med", "medium")
    await _seed(session, "T-high", "high")
    slack = FakeSlack()

    sent = await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    assert sent == 2
    assert [p["ticket_id"] for p in slack.posts] == ["T-high", "T-med"]


@pytest.mark.asyncio
async def test_a_successful_post_records_full_delivery_state(session: AsyncSession) -> None:
    alert = await _seed(session, "T1", "high")
    slack = FakeSlack()

    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    await session.refresh(alert)
    assert alert.slack_ts == "ts-1"
    assert alert.slack_channel == "C-bugs"
    assert alert.posted_severity == "high"
    assert alert.posted_at is not None


@pytest.mark.asyncio
async def test_a_delivered_alert_is_never_posted_again(session: AsyncSession) -> None:
    """The dedup guarantee, end to end: re-running delivery posts nothing."""
    await _seed(session, "T1", "high")
    slack = FakeSlack()

    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]
    second = await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    assert second == 0
    assert len(slack.posts) == 1


@pytest.mark.asyncio
async def test_a_failing_post_leaves_the_row_in_the_outbox(session: AsyncSession) -> None:
    """Nothing is lost on a Slack outage — the row is retried next pass."""
    alert = await _seed(session, "T1", "high")
    failing = FakeSlack(fail_with=RuntimeError("slack down"))

    assert await deliver_pending_bug_alerts(session, failing, _config()) == 0  # type: ignore[arg-type]

    await session.refresh(alert)
    assert alert.posted_at is None
    assert alert.slack_ts is None

    recovered = FakeSlack()
    assert await deliver_pending_bug_alerts(session, recovered, _config()) == 1  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_one_bad_row_does_not_stall_the_others(session: AsyncSession) -> None:
    class OneBadChannel(FakeSlack):
        async def post_message(self, **kwargs: Any) -> str:
            if kwargs.get("ticket_id") == "T-bad":
                raise RuntimeError("channel_not_found")
            return await super().post_message(**kwargs)

    await _seed(session, "T-bad", "high")
    await _seed(session, "T-good", "high")
    slack = OneBadChannel()

    sent = await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    assert sent == 1
    assert [p["ticket_id"] for p in slack.posts] == ["T-good"]


@pytest.mark.asyncio
async def test_escalation_replies_in_thread_without_a_new_top_level_post(
    session: AsyncSession,
) -> None:
    alert = await _seed(session, "T1", "medium")
    slack = FakeSlack()
    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]
    await session.refresh(alert)
    original_ts = alert.slack_ts

    # The model later re-reads the same ticket as worse.
    alert.severity = "high"
    await session.commit()

    sent = await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    assert sent == 1
    escalation = slack.posts[-1]
    assert escalation["thread_ts"] == original_ts
    # A short reply, not the whole card again.
    assert escalation["blocks"] is None
    assert escalation["attachments"] is None
    await session.refresh(alert)
    assert alert.posted_severity == "high"
    # Still one top-level message: the ts is unchanged.
    assert alert.slack_ts == original_ts


@pytest.mark.asyncio
async def test_a_downgrade_after_delivery_posts_nothing(session: AsyncSession) -> None:
    alert = await _seed(session, "T1", "high")
    slack = FakeSlack()
    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    alert.severity = "medium"
    await session.commit()

    assert await deliver_pending_bug_alerts(session, slack, _config()) == 0  # type: ignore[arg-type]
    assert len(slack.posts) == 1


@pytest.mark.asyncio
async def test_low_severity_never_reaches_slack(session: AsyncSession) -> None:
    """Locked decision 1 — `low` is recorded but stays below the floor."""
    alert = await _seed(session, "T1", "low")
    slack = FakeSlack()

    assert await deliver_pending_bug_alerts(session, slack, _config()) == 0  # type: ignore[arg-type]
    await session.refresh(alert)
    assert alert.posted_at is None


@pytest.mark.asyncio
async def test_lowering_the_floor_lets_low_through(session: AsyncSession) -> None:
    await _seed(session, "T1", "low")
    slack = FakeSlack()
    sent = await deliver_pending_bug_alerts(  # type: ignore[arg-type]
        session, slack, _config(bug_alert_min_severity="low")
    )
    assert sent == 1


@pytest.mark.asyncio
async def test_a_dismissed_alert_is_skipped(session: AsyncSession) -> None:
    await _seed(session, "T1", "high", dismissed_at=naive_utcnow())
    slack = FakeSlack()
    assert await deliver_pending_bug_alerts(session, slack, _config()) == 0  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_max_per_cycle_bounds_the_pass(session: AsyncSession) -> None:
    for i in range(5):
        await _seed(session, f"T{i}", "high")
    slack = FakeSlack()

    sent = await deliver_pending_bug_alerts(  # type: ignore[arg-type]
        session, slack, _config(bug_alert_max_per_cycle=2)
    )
    assert sent == 2
    # The remainder stays in the outbox and drains on the next pass.
    assert await deliver_pending_bug_alerts(session, slack, _config()) == 3  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_unconfigured_slack_is_a_no_op(session: AsyncSession) -> None:
    """Detection keeps working with no Slack; only delivery is disabled."""
    alert = await _seed(session, "T1", "high")
    slack = FakeSlack()

    assert await deliver_pending_bug_alerts(session, slack, _config(slack_bug_channel="")) == 0  # type: ignore[arg-type]
    await session.refresh(alert)
    assert alert.posted_at is None


@pytest.mark.asyncio
async def test_an_auth_error_stops_the_pass_and_keeps_the_outbox(session: AsyncSession) -> None:
    """A revoked token fails every row identically — stop rather than burn the
    whole cycle, and leave everything to self-heal once the token is fixed."""
    from app.clients.slack import SlackAuthError

    await _seed(session, "T1", "high")
    await _seed(session, "T2", "high")
    slack = FakeSlack(fail_with=SlackAuthError("invalid_auth"))

    assert await deliver_pending_bug_alerts(session, slack, _config()) == 0  # type: ignore[arg-type]

    rows = [await session.get(BugAlert, "T1"), await session.get(BugAlert, "T2")]
    assert all(r is not None and r.posted_at is None for r in rows)


@pytest.mark.asyncio
async def test_the_message_carries_the_evidence_quote_and_a_link(session: AsyncSession) -> None:
    await _seed(session, "T1", "high")
    slack = FakeSlack()
    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    post = slack.posts[0]
    card = rendered(post)
    assert "it never finishes loading" in card
    assert "conversations/T1" in card
    # The notification line stays quote-free — it surfaces in push previews.
    assert "it never finishes loading" not in post["text"]
    # …and so does the attachment fallback, for the same reason.
    assert "it never finishes loading" not in post["attachments"][0]["fallback"]


@pytest.mark.asyncio
async def test_an_alert_without_a_ticket_row_still_posts(session: AsyncSession) -> None:
    """`bug_alerts` has no FK to tickets (the id is Intercom-owned), so a
    missing ticket row is "no context", not an error."""
    now = naive_utcnow()
    session.add(
        BugAlert(
            ticket_id="T-orphan",
            severity="high",
            confidence=0.9,
            evidence="broken",
            first_detected_at=now,
            last_detected_at=now,
        )
    )
    await session.commit()

    slack = FakeSlack()
    assert await deliver_pending_bug_alerts(session, slack, _config()) == 1  # type: ignore[arg-type]
    assert "T-orphan" in slack.posts[0]["text"]


# ── Card composition ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_card_carries_reporter_identity(session: AsyncSession) -> None:
    """Who reported it, and how to reach them, without opening Intercom."""
    now = naive_utcnow()
    session.add(
        Ticket(
            id="T-rich",
            title="Analytics not displaying",
            url="https://app.intercom.com/a/apps/x/conversations/T-rich",
            state="open",
            created_at=now,
            updated_at=now,
            category_id=1,
            summary="Customer reports analytics showing nothing.",
            ai_sentiment="negative",
            ai_priority="high",
            ai_labels=["analytics", "workflows"],
            author={
                "id": "6431dc586c51b80f57c14b96",
                "name": "Michael Fina",
                "email": "michael@example.com",
                "location": "Pompano Beach, Florida",
                "type": "user",
            },
        )
    )
    session.add(
        BugAlert(
            ticket_id="T-rich",
            severity="high",
            confidence=0.88,
            evidence="im not seeing any of those responding",
            first_detected_at=now,
            last_detected_at=now,
        )
    )
    await session.commit()

    slack = FakeSlack()
    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]
    card = rendered(slack.posts[0])

    assert "Michael Fina" in card
    assert "michael@example.com" in card
    # The Intercom-facing user id — what the operator matches against the panel.
    assert "6431dc586c51b80f57c14b96" in card
    assert "Pompano Beach, Florida" in card
    assert "Customer reports analytics showing nothing." in card
    assert "negative" in card and "analytics" in card
    assert "unassigned" in card


@pytest.mark.asyncio
async def test_the_card_is_colour_coded_by_severity(session: AsyncSession) -> None:
    await _seed(session, "T-high", "high")
    await _seed(session, "T-med", "medium")
    slack = FakeSlack()
    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    colors = {p["attachments"][0]["color"] for p in slack.posts}
    assert len(colors) == 2  # the rail distinguishes them at a glance


@pytest.mark.asyncio
async def test_the_card_links_inline_and_not_via_a_button(session: AsyncSession) -> None:
    """Slack badges link buttons from non-Marketplace apps with a warning glyph;
    the linked title carries the same affordance without it."""
    await _seed(session, "T1", "high")
    slack = FakeSlack()
    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    card = rendered(slack.posts[0])
    assert "<https://app.intercom.com/a/apps/x/conversations/T1|Ticket T1>" in card
    assert '"type": "actions"' not in card


@pytest.mark.asyncio
async def test_a_missing_ticket_row_degrades_the_card_rather_than_failing(
    session: AsyncSession,
) -> None:
    now = naive_utcnow()
    session.add(
        BugAlert(
            ticket_id="T-orphan-2",
            severity="high",
            confidence=0.9,
            evidence="broken",
            first_detected_at=now,
            last_detected_at=now,
        )
    )
    await session.commit()

    slack = FakeSlack()
    assert await deliver_pending_bug_alerts(session, slack, _config()) == 1  # type: ignore[arg-type]
    card = rendered(slack.posts[0])
    assert "T-orphan-2" in card
    assert "Reported by" not in card  # no identity to show, so no empty field

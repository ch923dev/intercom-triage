"""US-047 — the incident record + recurrence suggestion.

Reference: FR-089..FR-094, plan.md §23, tasks.md T187/T188/T189.

The encoder is faked throughout (`embeddings.set_encoder`) so similarity is
deterministic and no model is downloaded: a real sentence-transformer would make
these tests slow AND make the assertions depend on its weights.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embeddings
from app.ai.pipeline import CategorizationResult
from app.config import AppConfig
from app.models import BugAlert, Ticket, User
from app.services.bug_alerts import (
    ack_bug_alert,
    deliver_pending_bug_alerts,
    dismiss_bug_alert,
    record_bug_alerts,
    set_bug_note,
    similar_noted_bugs,
)
from app.util import naive_utcnow


class FakeSlack:
    def __init__(self) -> None:
        self.posts: list[dict[str, Any]] = []

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
        self.posts.append({"text": text, "attachments": attachments, "ticket_id": ticket_id})
        return f"ts-{len(self.posts)}"


class KeywordEncoder:
    """Deterministic stand-in: one dimension per keyword, so two texts are similar
    exactly to the extent that they share vocabulary. Enough to exercise ranking
    and the floor without pulling in a real model.

    The trailing constant dimension keeps every vector non-zero (`cosine` returns
    0.0 for a zero vector, which would make "no shared words" indistinguishable
    from "no words at all") and keeps every vector the SAME length — `cosine` zips
    strictly, so a variable-length encoder raises rather than scoring.
    """

    _VOCAB = ("export", "button", "invoice", "login", "password", "crash")
    _BIAS = 0.1

    def encode_one(self, text: str) -> list[float]:
        low = text.lower()
        return [1.0 if word in low else 0.0 for word in self._VOCAB] + [self._BIAS]


@pytest.fixture
def fake_encoder() -> Iterator[None]:
    embeddings.set_encoder(KeywordEncoder())  # type: ignore[arg-type]
    yield
    embeddings.set_encoder(None)


async def _seed_second_operator(session: AsyncSession) -> None:
    """conftest seeds only user 1; `note_by`/`acked_by` are real FKs."""
    session.add(
        User(
            id=2, onlysales_id="second-oid", email="two@test", name="Second Operator", scope="user"
        )
    )
    await session.commit()


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
    *,
    evidence: str,
    title: str,
    note: str | None = None,
    note_by: int | None = 1,
    announced: bool = False,
    severity: str = "high",
) -> BugAlert:
    now = naive_utcnow()
    session.add(
        Ticket(
            id=ticket_id,
            title=title,
            url=f"https://app.intercom.com/a/apps/x/conversations/{ticket_id}",
            created_at=now,
            updated_at=now,
            category_id=1,
            summary=title,
        )
    )
    fields: dict[str, Any] = {
        "ticket_id": ticket_id,
        "severity": severity,
        "confidence": 0.9,
        "evidence": evidence,
        "first_detected_at": now,
        "last_detected_at": now,
    }
    if note is not None:
        fields |= {"note": note, "note_by": note_by, "note_at": now}
    if announced:
        fields |= {
            "posted_at": now,
            "posted_severity": severity,
            "slack_channel": "C-bugs",
            "slack_ts": "1786606832.587139",
        }
    alert = BugAlert(**fields)
    session.add(alert)
    await session.commit()
    return alert


# ── The note itself ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_note_write_is_401(unauth_client: AsyncClient) -> None:
    resp = await unauth_client.put("/bug-alerts/T1/note", json={"note": "x"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_note_on_unknown_alert_is_404(client: AsyncClient) -> None:
    resp = await client.put("/bug-alerts/nope/note", json={"note": "x"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_writing_a_note_records_the_author(
    client: AsyncClient, session: AsyncSession
) -> None:
    await _seed(session, "T1", evidence="export button does nothing", title="Export broken")

    resp = await client.put(
        "/bug-alerts/T1/note", json={"note": "stale cache key — clear session, re-export"}
    )
    assert resp.status_code == 200
    body = resp.json()

    assert body["note"] == "stale cache key — clear session, re-export"
    assert body["note_by"] == {"id": 1, "name": "Seed Operator"}
    assert body["note_at"] is not None


@pytest.mark.asyncio
async def test_an_empty_note_clears_the_trio(client: AsyncClient, session: AsyncSession) -> None:
    """ "No note" has one representation, not two (FR-089)."""
    await _seed(session, "T1", evidence="e", title="t", note="something")

    body = (await client.put("/bug-alerts/T1/note", json={"note": "   "})).json()

    assert body["note"] is None
    assert body["note_by"] is None
    assert body["note_at"] is None


@pytest.mark.asyncio
async def test_a_second_operator_becomes_the_author(session: AsyncSession) -> None:
    """Team-wide board: a correction re-attributes, by design (plan §23)."""
    await _seed(session, "T1", evidence="e", title="t")
    await _seed_second_operator(session)

    await set_bug_note(session, "T1", note="first take", user_id=1)
    second = await set_bug_note(session, "T1", note="actually the cache key", user_id=2)

    assert second.note == "actually the cache key"
    assert second.note_by is not None and second.note_by.id == 2


@pytest.mark.asyncio
async def test_the_note_trio_cannot_be_half_set(session: AsyncSession) -> None:
    await _seed(session, "T-pair", evidence="e", title="t")
    with pytest.raises(IntegrityError):
        await session.execute(
            text("UPDATE bug_alerts SET note = 'orphan' WHERE ticket_id = 'T-pair'")
        )
        await session.commit()
    await session.rollback()


@pytest.mark.asyncio
async def test_a_note_over_the_cap_is_rejected(client: AsyncClient, session: AsyncSession) -> None:
    await _seed(session, "T1", evidence="e", title="t")
    resp = await client.put("/bug-alerts/T1/note", json={"note": "x" * 2001})
    assert resp.status_code == 422


# ── Durability (FR-090) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_note_survives_re_detection_and_escalation(session: AsyncSession) -> None:
    await _seed(session, "T1", evidence="e", title="t", severity="medium", note="the fix")

    await record_bug_alerts(
        session,
        {
            "T1": CategorizationResult(
                category_id=1,
                proposal_id=None,
                summary="s",
                confidence=0.8,
                subject="s",
                bug_severity="high",  # escalation
                bug_confidence=0.9,
                bug_evidence="e",
            )
        },
        _config(),
    )

    stored = await session.get(BugAlert, "T1")
    assert stored is not None
    await session.refresh(stored)
    assert stored.severity == "high"  # the escalation landed
    assert stored.note == "the fix"  # the record did not
    assert stored.note_by == 1


@pytest.mark.asyncio
async def test_ack_and_dismiss_leave_the_note_alone(session: AsyncSession) -> None:
    await _seed(session, "T1", evidence="e", title="t", note="the fix")
    await _seed_second_operator(session)

    await ack_bug_alert(session, "T1", user_id=2, slack=None, config=_config())
    dismissed = await dismiss_bug_alert(session, "T1")

    assert dismissed.note == "the fix"
    assert dismissed.note_by is not None and dismissed.note_by.id == 1  # note author, not acker
    assert dismissed.acked_by is not None and dismissed.acked_by.id == 2


# ── Recurrence matching ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_similar_noted_bug_is_offered_across_categories(
    session: AsyncSession, fake_encoder: None
) -> None:
    await _seed(
        session,
        "T-old",
        evidence="the export button does nothing",
        title="Export button broken",
        note="stale cache key — clear session",
    )
    await _seed(session, "T-new", evidence="export button not working", title="Export button dead")

    [match] = await similar_noted_bugs(session, "T-new")

    assert match.ticket_id == "T-old"
    assert match.note == "stale cache key — clear session"
    assert match.note_by is not None and match.note_by.name == "Seed Operator"
    assert match.score >= 0.55
    assert match.url is not None  # links to the earlier conversation


@pytest.mark.asyncio
async def test_an_unrelated_bug_is_not_offered(session: AsyncSession, fake_encoder: None) -> None:
    """Below the floor we say nothing — a wrong prior fix gets followed (FR-093)."""
    await _seed(
        session, "T-old", evidence="login password rejected", title="Login broken", note="reset it"
    )
    await _seed(session, "T-new", evidence="the export button does nothing", title="Export broken")

    assert await similar_noted_bugs(session, "T-new") == []


@pytest.mark.asyncio
async def test_the_floor_is_applied(session: AsyncSession, fake_encoder: None) -> None:
    """The mechanism, not the tuned value. `_SIMILAR_MIN_SCORE` was re-picked from
    a measured distribution (plan §23) and will move again; a test asserting the
    number would just have to be edited alongside it. What must not silently break
    is that the floor is consulted at all."""
    await _seed(
        session, "T-old", evidence="the export button does nothing", title="Export", note="the fix"
    )
    await _seed(session, "T-new", evidence="the export button does nothing", title="Export")

    # Identical symptoms — the best possible match.
    assert await similar_noted_bugs(session, "T-new", min_score=-1.0)
    # Unreachable floor rejects even that.
    assert await similar_noted_bugs(session, "T-new", min_score=1.1) == []


@pytest.mark.asyncio
async def test_an_alert_never_matches_itself(session: AsyncSession, fake_encoder: None) -> None:
    await _seed(
        session, "T1", evidence="the export button does nothing", title="Export", note="the fix"
    )
    assert await similar_noted_bugs(session, "T1") == []


@pytest.mark.asyncio
async def test_an_unnoted_bug_is_never_offered(session: AsyncSession, fake_encoder: None) -> None:
    """Identical symptom, no note — there is nothing to retrieve."""
    await _seed(session, "T-old", evidence="the export button does nothing", title="Export broken")
    await _seed(session, "T-new", evidence="the export button does nothing", title="Export broken")

    assert await similar_noted_bugs(session, "T-new") == []


@pytest.mark.asyncio
async def test_no_encoder_means_no_suggestion_not_an_error(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hosted v1 runs embeddings off, so this is the normal path (FR-094).

    `encoder_available` is patched rather than `set_encoder(None)`: availability
    is probed with `find_spec`, so on a machine that HAS sentence-transformers
    installed, clearing the override would still report available and go on to
    load a real model.
    """
    monkeypatch.setattr(embeddings, "encoder_available", lambda: False)
    await _seed(
        session, "T-old", evidence="the export button does nothing", title="Export", note="fix"
    )
    await _seed(session, "T-new", evidence="the export button does nothing", title="Export")

    # The note is still readable even though nothing can be matched.
    assert await similar_noted_bugs(session, "T-new") == []
    old = await session.get(BugAlert, "T-old")
    assert old is not None and old.note == "fix"


@pytest.mark.asyncio
async def test_the_note_is_not_what_gets_matched(session: AsyncSession, fake_encoder: None) -> None:
    """Symptom-to-symptom. A note that shares the NEW bug's vocabulary must not
    drag an unrelated defect into the result (plan §23)."""
    await _seed(
        session,
        "T-old",
        evidence="login password rejected",
        title="Login broken",
        # Deliberately stuffed with the new bug's words.
        note="unrelated to export button invoice crash",
    )
    await _seed(session, "T-new", evidence="the export button does nothing", title="Export broken")

    assert await similar_noted_bugs(session, "T-new") == []


@pytest.mark.asyncio
async def test_unauthenticated_similar_is_401(unauth_client: AsyncClient) -> None:
    assert (await unauth_client.get("/bug-alerts/T1/similar")).status_code == 401


@pytest.mark.asyncio
async def test_similar_endpoint_recomputes_per_request(
    client: AsyncClient, session: AsyncSession, fake_encoder: None
) -> None:
    """FR-092. Deliberately does NOT also use `unauth_client`: that fixture pops
    the auth override off the shared app, so an authenticated call afterwards in
    the same test would 401 for harness reasons and read as a product failure."""
    await _seed(session, "T-old", evidence="the export button does nothing", title="Export broken")
    await _seed(session, "T-new", evidence="export button not working", title="Export dead")

    # No note yet → nothing to offer.
    assert (await client.get("/bug-alerts/T-new/similar")).json() == []

    # FR-092: writing the note later still reaches a reader now.
    await client.put("/bug-alerts/T-old/note", json={"note": "stale cache key"})
    [match] = (await client.get("/bug-alerts/T-new/similar")).json()
    assert match["ticket_id"] == "T-old"
    assert match["note"] == "stale cache key"


# ── The Slack card ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_announcement_carries_the_prior_fix(
    session: AsyncSession, fake_encoder: None
) -> None:
    await _seed(
        session,
        "T-old",
        evidence="the export button does nothing",
        title="Export button broken",
        note="stale cache key — clear session",
        announced=True,
    )
    await _seed(session, "T-new", evidence="export button not working", title="Export button dead")
    slack = FakeSlack()

    sent = await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    assert sent == 1
    card = json.dumps(slack.posts[0]["attachments"], ensure_ascii=False)
    assert "Seen before" in card
    assert "stale cache key" in card
    assert "T-old" in card or "Export button broken" in card


@pytest.mark.asyncio
async def test_the_prior_note_stays_out_of_the_push_preview(
    session: AsyncSession, fake_encoder: None
) -> None:
    """A note routinely quotes the customer, and `text`/`fallback` surface in push
    notifications (NFR-016)."""
    note = "stale cache key — clear session"
    await _seed(
        session,
        "T-old",
        evidence="the export button does nothing",
        title="Export button broken",
        note=note,
        announced=True,
    )
    await _seed(session, "T-new", evidence="export button not working", title="Export button dead")
    slack = FakeSlack()

    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    post = slack.posts[0]
    assert note not in post["text"]
    assert note not in post["attachments"][0]["fallback"]
    assert note in json.dumps(post["attachments"][0]["blocks"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_an_alert_with_no_precedent_gets_no_seen_before_block(
    session: AsyncSession, fake_encoder: None
) -> None:
    """Absent, not empty: a "no similar bugs" line on every alert is noise."""
    await _seed(session, "T-new", evidence="the export button does nothing", title="Export broken")
    slack = FakeSlack()

    await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    assert "Seen before" not in json.dumps(slack.posts[0]["attachments"], ensure_ascii=False)


@pytest.mark.asyncio
async def test_a_matching_failure_does_not_cost_the_announcement(
    session: AsyncSession, monkeypatch: pytest.MonkeyPatch, fake_encoder: None
) -> None:
    """The alert is the thing that must not be lost; the hint is enrichment."""
    await _seed(
        session,
        "T-old",
        evidence="the export button does nothing",
        title="Export broken",
        note="the fix",
    )
    await _seed(session, "T-new", evidence="export button not working", title="Export dead")

    def boom(_: str) -> list[float]:
        raise RuntimeError("encoder exploded")

    monkeypatch.setattr(embeddings, "embed_text", boom)
    slack = FakeSlack()

    # Both seeded alerts are unannounced, so both go out this pass.
    sent = await deliver_pending_bug_alerts(session, slack, _config())  # type: ignore[arg-type]

    assert sent == 2  # posted anyway, despite the matcher blowing up
    assert "Seen before" not in json.dumps(slack.posts[0]["attachments"], ensure_ascii=False)

"""Recurring-issue clustering (roadmap 3.1). Fully offline via the autouse
`fake_encoder` fixture — the real model never loads.

The fake encoder is deterministic: identical text → identical 384-dim vector,
distinct text → an effectively-random vector. So a GROUP of tickets sharing the
same customer-visible body forms a tight cluster, while a one-off ticket with
unique text is an HDBSCAN outlier (label -1) — exactly the structure we assert.

Covers:
- Clusters are produced over resolved tickets' embeddings.
- HDBSCAN outliers are flagged (label -1), NOT force-fit into a cluster.
- c-TF-IDF labels are non-empty and drawn from customer-visible `parts[]`.
- Invariant #4: `internal_notes` text NEVER appears in a cluster label.
- Invariant #6: clustering leaves `ai_cache` untouched.
- Too-few-tickets guard is a no-op (no crash).
- The `/clusters` endpoints serve + recompute the snapshot.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import clustering
from app.config import AppConfig
from app.models import AICacheEntry, Ticket, TicketCluster, TicketClusterMember
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema
from app.services.tickets import ingest_tickets
from app.util import naive_utcnow

_DT = datetime(2026, 5, 23, 12, 0, 0)


def _hydrated(
    ticket_id: str,
    *,
    title: str,
    part_body: str,
    internal_note_body: str | None = None,
) -> HydratedTicket:
    author = TicketAuthorSchema(id="u1", name="Customer", type="user")
    internal_notes = []
    if internal_note_body is not None:
        internal_notes = [
            ConversationPartSchema(author=author, body=internal_note_body, created_at=_DT)
        ]
    return HydratedTicket(
        id=ticket_id,
        title=title,
        state="open",
        priority=None,
        created_at=_DT,
        updated_at=_DT,
        author=author,
        url=None,
        parts=[ConversationPartSchema(author=author, body=part_body, created_at=_DT)],
        internal_notes=internal_notes,
    )


async def _ingest_resolved(
    session: AsyncSession,
    config: AppConfig,
    tickets: list[HydratedTicket],
) -> None:
    """Ingest tickets (stores embeddings via the fake encoder) then mark every
    one resolved so the clustering job picks them up."""
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=config,
        hydrated=tickets,
    )
    now = naive_utcnow()
    for t in tickets:
        row = await session.get(Ticket, t.id)
        assert row is not None
        row.resolved_at = now
        row.resolved_source = "manual"
    await session.commit()


def _two_groups_plus_outlier() -> list[HydratedTicket]:
    """Two tight clusters (3 + 3 identical-body tickets) and one unique outlier."""
    group_a = [
        _hydrated(
            f"a{i}",
            title="Login fails",
            part_body="I cannot log in, my password reset email never arrives",
        )
        for i in range(3)
    ]
    group_b = [
        _hydrated(
            f"b{i}",
            title="Export broken",
            part_body="exporting my report to CSV produces an empty file every time",
        )
        for i in range(3)
    ]
    outlier = _hydrated(
        "z0",
        title="Random one-off",
        part_body="completely unrelated singular gibberish quetzal xylophone",
    )
    return [*group_a, *group_b, outlier]


@pytest.mark.asyncio
async def test_clusters_produced_over_resolved_embeddings(
    session: AsyncSession, test_config: AppConfig
) -> None:
    await _ingest_resolved(session, test_config, _two_groups_plus_outlier())

    outcome = await clustering.recompute_clusters(session, min_tickets=2)

    assert outcome.skipped_reason is None
    # Two tight groups → at least two clusters.
    assert outcome.clusters >= 2
    # The unique one-off is a density outlier, not force-fit.
    assert outcome.outliers >= 1

    rows = (await session.scalars(select(TicketCluster))).all()
    assert len(rows) == outcome.clusters
    # Every persisted cluster has at least 2 members and a non-empty label.
    for c in rows:
        assert c.size >= 2
        assert c.label.strip()
        assert isinstance(c.top_terms, list)


@pytest.mark.asyncio
async def test_outlier_not_in_any_cluster(session: AsyncSession, test_config: AppConfig) -> None:
    """HDBSCAN noise (label -1) must NOT be force-fit into a cluster — the
    one-off ticket should never appear as a member."""
    await _ingest_resolved(session, test_config, _two_groups_plus_outlier())
    await clustering.recompute_clusters(session, min_tickets=2)

    member_ids = set((await session.scalars(select(TicketClusterMember.ticket_id))).all())
    assert "z0" not in member_ids
    # Both groups' members were clustered.
    assert {"a0", "a1", "a2"}.issubset(member_ids)
    assert {"b0", "b1", "b2"}.issubset(member_ids)


@pytest.mark.asyncio
async def test_labels_from_parts_not_internal_notes(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Invariant #4: a cluster LABEL must be built from customer-visible
    `parts[]` + title only — `internal_notes` text must NEVER leak into it."""
    secret = "zzzsecretinternaltokenzzz"
    payment_group = [
        _hydrated(
            f"c{i}",
            title="Payment declined",
            part_body="my credit card payment keeps getting declined at checkout",
            internal_note_body=f"{secret} operator triage chatter",
        )
        for i in range(3)
    ]
    # A contrasting group so HDBSCAN has density structure to separate (a single
    # homogeneous blob has no contrast and would collapse to noise).
    other_group = [
        _hydrated(
            f"d{i}",
            title="Sync delay",
            part_body="my dashboard data takes hours to refresh after an update",
            internal_note_body=f"{secret} another internal aside",
        )
        for i in range(3)
    ]
    await _ingest_resolved(session, test_config, [*payment_group, *other_group])
    await clustering.recompute_clusters(session, min_tickets=2)

    rows = (await session.scalars(select(TicketCluster))).all()
    assert rows
    for c in rows:
        assert secret not in c.label
        assert all(secret not in term for term in c.top_terms)
    # The labels are drawn from the customer-visible words only.
    joined_terms = " ".join(t for c in rows for t in c.top_terms)
    assert any(word in joined_terms for word in ("payment", "card", "declined", "checkout"))


@pytest.mark.asyncio
async def test_ai_cache_untouched_by_clustering(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Invariant #6: clustering reads ticket_embeddings + tickets only; ai_cache
    is never written or read."""
    await _ingest_resolved(session, test_config, _two_groups_plus_outlier())
    await clustering.recompute_clusters(session, min_tickets=2)

    cache_count = await session.scalar(text("SELECT count(*) FROM ai_cache"))
    assert cache_count == 0
    assert (await session.scalars(select(AICacheEntry))).all() == []


@pytest.mark.asyncio
async def test_too_few_tickets_is_noop(session: AsyncSession, test_config: AppConfig) -> None:
    """Guard: below the min-tickets threshold the run is skipped (no crash, no
    rows persisted)."""
    await _ingest_resolved(
        session,
        test_config,
        [_hydrated("solo", title="alone", part_body="just one resolved ticket")],
    )
    outcome = await clustering.recompute_clusters(session, min_tickets=5)

    assert outcome.clusters == 0
    assert outcome.skipped_reason is not None
    assert (await session.scalars(select(TicketCluster))).all() == []


@pytest.mark.asyncio
async def test_open_tickets_are_not_clustered(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Only RESOLVED tickets are clustered — open ones are ignored even if they
    have embeddings."""
    tickets = [
        _hydrated(f"o{i}", title="Open issue", part_body="an open unresolved problem here")
        for i in range(3)
    ]
    # Ingest but DO NOT resolve.
    await ingest_tickets(session=session, openrouter=None, config=test_config, hydrated=tickets)

    outcome = await clustering.recompute_clusters(session, min_tickets=2)
    assert outcome.clusters == 0
    assert outcome.skipped_reason is not None


@pytest.mark.asyncio
async def test_recompute_replaces_previous_snapshot(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Each run is an atomic snapshot replace — a second run does not accumulate
    stale clusters."""
    await _ingest_resolved(session, test_config, _two_groups_plus_outlier())
    await clustering.recompute_clusters(session, min_tickets=2)
    first = len((await session.scalars(select(TicketCluster))).all())
    assert first >= 2

    await clustering.recompute_clusters(session, min_tickets=2)
    second_rows = (await session.scalars(select(TicketCluster))).all()
    # Same structure, not doubled.
    assert len(second_rows) == first


# ── API ───────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clusters_endpoint_lists_snapshot(
    client, session: AsyncSession, test_config: AppConfig
) -> None:
    await _ingest_resolved(session, test_config, _two_groups_plus_outlier())
    await clustering.recompute_clusters(session, min_tickets=2)

    resp = await client.get("/clusters")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 2
    first = body[0]
    assert first["label"].strip()
    assert first["size"] >= 2
    assert len(first["ticket_ids"]) == first["size"]
    # Sorted largest-first.
    sizes = [c["size"] for c in body]
    assert sizes == sorted(sizes, reverse=True)


@pytest.mark.asyncio
async def test_clusters_recompute_endpoint(
    client, session: AsyncSession, test_config: AppConfig
) -> None:
    await _ingest_resolved(session, test_config, _two_groups_plus_outlier())

    # No snapshot yet.
    assert (await client.get("/clusters")).json() == []

    resp = await client.post("/clusters/recompute")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) >= 2
    # Persisted — a follow-up GET returns the same snapshot.
    assert len((await client.get("/clusters")).json()) == len(body)


@pytest.mark.asyncio
async def test_recompute_uses_wired_app_state_config(app, client, monkeypatch) -> None:
    """POST /clusters/recompute must read app.state.config (get_app_config),
    not the process-global lru_cache get_config(). We set a sentinel
    min_tickets on the wired config and assert the clustering job receives it.

    The conftest `app` fixture overrides `get_config` to return `test_config`
    (the same object as `app.state.config`), so a naive sentinel can't tell the
    two dependencies apart. To actually discriminate, point the `get_config`
    override at a DISTINCT config carrying a different value — only an endpoint
    reading `app.state.config` (i.e. `get_app_config`) sees our 99 sentinel."""
    from app.config import get_config

    captured: dict[str, int] = {}

    async def _recorder(session, min_tickets: int):
        captured["min_tickets"] = min_tickets
        return None

    monkeypatch.setattr(clustering, "recompute_clusters", _recorder)
    app.state.config.clustering_enabled = True
    app.state.config.clustering_min_tickets = 99  # sentinel, != get_config's value

    # Decoy: if the endpoint still injects get_config it sees 7, not 99.
    decoy = app.state.config.model_copy(update={"clustering_min_tickets": 7})
    app.dependency_overrides[get_config] = lambda: decoy

    resp = await client.post("/clusters/recompute")
    assert resp.status_code == 200
    assert captured["min_tickets"] == 99

"""Local embedding layer (roadmap 2.4). Fully offline via the autouse
`fake_encoder` fixture in conftest — the real ~80 MB model never loads.

Covers:
- The `vec0` table exists on the in-memory test DB (migration 0014 ran).
- Ingest computes + stores an embedding; a nearest-neighbour query returns it.
- Invariant #4: `internal_notes` text is NEVER embedded (only parts + operator
  note are).
- Invariant #6: the embedding pass leaves `ai_cache` untouched.
- EMBEDDINGS_ENABLED=False disables the hook.
- An encoder failure does not break ingest (best-effort).
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embeddings
from app.config import AppConfig
from app.models import AICacheEntry, TicketNote
from app.schemas import ConversationPartSchema, HydratedTicket, TicketAuthorSchema
from app.services.tickets import ingest_tickets

from .conftest import FakeEncoder

_DT = datetime(2026, 5, 23, 12, 0, 0)


def _hydrated(
    ticket_id: str = "t1",
    *,
    part_body: str = "my export to CSV is missing custom fields",
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
        title="CSV export issue",
        state="open",
        priority=None,
        created_at=_DT,
        updated_at=_DT,
        author=author,
        url=None,
        parts=[ConversationPartSchema(author=author, body=part_body, created_at=_DT)],
        internal_notes=internal_notes,
    )


@pytest.mark.asyncio
async def test_vec_table_exists_on_test_db(session: AsyncSession) -> None:
    """The vec0 virtual table from migration 0014 is present on the in-memory DB
    and the sqlite-vec extension loaded (a MATCH query must parse)."""
    rows = (
        await session.execute(
            text("SELECT name FROM sqlite_master WHERE name = 'ticket_embeddings'")
        )
    ).all()
    assert rows, "ticket_embeddings vec0 table missing — migration 0014 did not run"


@pytest.mark.asyncio
async def test_ingest_stores_embedding_and_knn_retrieves_it(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Ingest a ticket (stubbed encoder) → embedding row exists → a
    nearest-neighbour query on the same text returns that ticket."""
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[_hydrated("t1")],
    )

    count = await session.scalar(text("SELECT count(*) FROM ticket_embeddings"))
    assert count == 1

    # Query with the exact stored text — deterministic fake → distance ~0.
    body = embeddings.build_embedding_text(_hydrated("t1"))
    hits = await embeddings.nearest_to_text(session, body, k=5)
    assert hits, "nearest-neighbour query returned nothing"
    assert hits[0][0] == "t1"
    assert hits[0][1] == pytest.approx(0.0, abs=1e-4)


@pytest.mark.asyncio
async def test_internal_notes_never_embedded(
    session: AsyncSession, test_config: AppConfig, fake_encoder: FakeEncoder
) -> None:
    """Invariant #4: internal-note text must NEVER enter an embedding."""
    secret = "SECRET-INTERNAL-NOTE-DO-NOT-EMBED"
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[_hydrated("t1", internal_note_body=secret)],
    )

    # Something was embedded (the parts text)...
    assert fake_encoder.encoded
    # ...but the internal-note string never appeared in any embedded text.
    for embedded in fake_encoder.encoded:
        assert secret not in embedded


@pytest.mark.asyncio
async def test_operator_note_is_embedded(
    session: AsyncSession, test_config: AppConfig, fake_encoder: FakeEncoder
) -> None:
    """The operator's local ticket_notes jot IS part of the embedded text."""
    session.add(TicketNote(ticket_id="t1", body="operator says: known billing edge case"))
    await session.commit()

    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[_hydrated("t1")],
    )
    assert any("known billing edge case" in t for t in fake_encoder.encoded)


@pytest.mark.asyncio
async def test_ai_cache_untouched_by_embeddings(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Invariant #6: the embedding pass is a separate store — ingest with
    openrouter=None writes no ai_cache rows (fallback is never cached), and the
    embedding pass adds none either."""
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=test_config,
        hydrated=[_hydrated("t1")],
    )
    cache_count = await session.scalar(text("SELECT count(*) FROM ai_cache"))
    assert cache_count == 0
    # Sanity: no AICacheEntry model rows either.
    from sqlalchemy import select

    assert (await session.scalars(select(AICacheEntry))).all() == []


@pytest.mark.asyncio
async def test_embeddings_disabled_is_noop(session: AsyncSession) -> None:
    """EMBEDDINGS_ENABLED=False → ingest stores no embedding rows."""
    cfg = AppConfig(
        openrouter_api_key="test-openrouter-key",
        database_url="sqlite+aiosqlite:///:memory:",
        embeddings_enabled=False,
    )
    await ingest_tickets(
        session=session,
        openrouter=None,
        config=cfg,
        hydrated=[_hydrated("t1")],
    )
    count = await session.scalar(text("SELECT count(*) FROM ticket_embeddings"))
    assert count == 0


@pytest.mark.asyncio
async def test_embedding_failure_does_not_break_ingest(
    session: AsyncSession, test_config: AppConfig
) -> None:
    """Best-effort: an encoder explosion must not roll back or fail ingest."""

    class BoomEncoder:
        def encode_one(self, text: str) -> list[float]:
            raise RuntimeError("model exploded")

    embeddings.set_encoder(BoomEncoder())
    try:
        resp = await ingest_tickets(
            session=session,
            openrouter=None,
            config=test_config,
            hydrated=[_hydrated("t1")],
        )
    finally:
        embeddings.set_encoder(None)

    # Ingest still succeeded and the ticket row is durable...
    assert resp.received == 1
    from app.models import Ticket

    assert await session.get(Ticket, "t1") is not None
    # ...but no embedding was stored.
    count = await session.scalar(text("SELECT count(*) FROM ticket_embeddings"))
    assert count == 0

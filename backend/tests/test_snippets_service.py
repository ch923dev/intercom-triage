"""Snippets service tests. Roadmap 1.5."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import AppConfig
from app.models import Snippet
from app.schemas import HydratedTicket, TicketAuthorSchema
from app.services import snippets as svc
from app.services.tickets import ingest_tickets
from app.util import naive_utcnow


@pytest.mark.asyncio
async def test_snippet_row_round_trips(session: AsyncSession) -> None:
    session.add(Snippet(title="greeting", body="Hi {{customer_name}}, thanks for reaching out."))
    await session.commit()
    rows = list((await session.scalars(select(Snippet))).all())
    assert len(rows) == 1
    assert rows[0].title == "greeting"
    assert "{{customer_name}}" in rows[0].body
    assert rows[0].archived_at is None


@pytest.mark.asyncio
async def test_create_then_list(session: AsyncSession) -> None:
    a = await svc.create(session, title="greeting", body="Hi {{customer_name}}")
    await svc.create(session, title="closer", body="Let me know if anything else comes up.")

    rows = await svc.list_all(session)
    assert [r.title for r in rows] == ["greeting", "closer"]
    assert a.id is not None


@pytest.mark.asyncio
async def test_list_hides_archived_by_default(session: AsyncSession) -> None:
    s = await svc.create(session, title="greeting", body="Hi")
    await svc.archive(session, s.id)

    assert await svc.list_all(session) == []
    archived = await svc.list_all(session, include_archived=True)
    assert [r.title for r in archived] == ["greeting"]


@pytest.mark.asyncio
async def test_update_changes_fields_and_bumps_updated_at(session: AsyncSession) -> None:
    s = await svc.create(session, title="old", body="old body")
    before = s.updated_at
    updated = await svc.update(session, s.id, title="new", body=None)
    assert updated.title == "new"
    assert updated.body == "old body"
    assert updated.updated_at >= before


@pytest.mark.asyncio
async def test_restore_clears_archived_at(session: AsyncSession) -> None:
    s = await svc.create(session, title="x", body="y")
    await svc.archive(session, s.id)
    restored = await svc.restore(session, s.id)
    assert restored.archived_at is None
    assert [r.title for r in await svc.list_all(session)] == ["x"]


@pytest.mark.asyncio
async def test_update_404_when_missing(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await svc.update(session, 999, title="x", body=None)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_archive_404_when_missing(session: AsyncSession) -> None:
    with pytest.raises(HTTPException) as exc:
        await svc.archive(session, 999)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_snippet_survives_ticket_resync(
    session: AsyncSession,
    test_config: AppConfig,
) -> None:
    """Invariant #13 — a full ingest / re-sync must not touch snippet rows."""
    saved = await svc.create(session, title="keepme", body="Hi {{customer_name}}")

    hydrated = HydratedTicket(
        id="TCKRESYNC",
        title="Refund please",
        state="open",
        priority=None,
        created_at=naive_utcnow(),
        updated_at=naive_utcnow(),
        author=TicketAuthorSchema(type="user", name="Cust"),
        url=None,
        parts=[],
        internal_notes=[],
    )
    await ingest_tickets(session=session, openrouter=None, config=test_config, hydrated=[hydrated])

    refreshed = await session.get(Snippet, saved.id)
    assert refreshed is not None
    assert refreshed.body == "Hi {{customer_name}}"
    assert refreshed.archived_at is None
    assert [r.title for r in await svc.list_all(session)] == ["keepme"]

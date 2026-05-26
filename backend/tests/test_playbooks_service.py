"""Playbooks service tests. Spec: docs/superpowers/specs/2026-05-26-playbooks-design.md"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Playbook


@pytest.mark.asyncio
async def test_playbook_row_round_trips(session: AsyncSession) -> None:
    session.add(
        Playbook(
            category_id=1,
            label="double-charge after upgrade",
            body="1. Confirm the duplicate invoice. 2. Issue refund. 3. Reply.",
        )
    )
    await session.commit()
    rows = list((await session.scalars(select(Playbook))).all())
    assert len(rows) == 1
    assert rows[0].label == "double-charge after upgrade"
    assert rows[0].archived_at is None
    assert rows[0].source_ticket_id is None


from app.services import playbooks as svc


@pytest.mark.asyncio
async def test_create_then_list_for_category(session: AsyncSession) -> None:
    a = await svc.create(session, category_id=1, label="issue A", body="steps A")
    await svc.create(session, category_id=1, label="issue B", body="steps B")
    await svc.create(session, category_id=2, label="other", body="steps C")

    rows = await svc.list_for_category(session, 1)
    labels = [r.label for r in rows]
    assert labels == ["issue A", "issue B"]
    assert a.id is not None


@pytest.mark.asyncio
async def test_list_for_category_hides_archived_by_default(session: AsyncSession) -> None:
    p = await svc.create(session, category_id=1, label="issue A", body="steps A")
    await svc.archive(session, p.id)

    assert await svc.list_for_category(session, 1) == []
    archived = await svc.list_for_category(session, 1, include_archived=True)
    assert [r.label for r in archived] == ["issue A"]

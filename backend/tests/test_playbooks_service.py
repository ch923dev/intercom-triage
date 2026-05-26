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

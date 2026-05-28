"""Recurring-issue cluster endpoints. Roadmap 3.1.

Read-only view over the `ticket_clusters` snapshot produced by the offline
periodic clustering job (`app/ai/clustering.py` + the background loop in
`app/main.py`). A manual `POST /clusters/recompute` lets the operator force a
refresh between scheduled runs. The standout consumer is roadmap 3.2, which
ranks clusters that have no playbook yet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import clustering
from app.config import AppConfig
from app.db import get_session
from app.deps import get_app_config
from app.models import TicketCluster, TicketClusterMember
from app.schemas import ClusterGapRead, ClusterRead
from app.services import clusters as clusters_svc

router = APIRouter(prefix="/clusters", tags=["clusters"])


async def _serialize(session: AsyncSession) -> list[ClusterRead]:
    """Read the persisted cluster snapshot + their member ids, largest first."""
    clusters = list(
        (
            await session.scalars(
                select(TicketCluster).order_by(TicketCluster.size.desc(), TicketCluster.id.asc())
            )
        ).all()
    )
    member_rows = (await session.execute(select(TicketClusterMember))).scalars().all()
    members: dict[int, list[str]] = {}
    for m in member_rows:
        members.setdefault(m.cluster_id, []).append(m.ticket_id)
    return [
        ClusterRead(
            id=c.id,
            label=c.label,
            top_terms=c.top_terms,
            size=c.size,
            ticket_ids=sorted(members.get(c.id, [])),
            computed_at=c.computed_at,
        )
        for c in clusters
    ]


@router.get("", response_model=list[ClusterRead])
async def list_clusters(
    session: AsyncSession = Depends(get_session),
) -> list[ClusterRead]:
    return await _serialize(session)


@router.get("/gaps", response_model=list[ClusterGapRead])
async def list_cluster_gaps(
    session: AsyncSession = Depends(get_session),
) -> list[ClusterGapRead]:
    """Roadmap 3.2 — recurring-issue clusters whose dominant EFFECTIVE category
    (override beats AI, invariant #13) has no active playbook, ranked by cluster
    size (most-recurring first). Read-only; never touches `ai_cache`."""
    gaps = await clusters_svc.rank_gaps(session)
    return [ClusterGapRead.model_validate(g) for g in gaps]


@router.post("/recompute", response_model=list[ClusterRead])
async def recompute_clusters(
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
) -> list[ClusterRead]:
    """On-demand recompute (between scheduled background runs). No-op when
    clustering is disabled or there are too few resolved tickets — returns the
    (possibly empty) current snapshot either way."""
    if config.clustering_enabled:
        await clustering.recompute_clusters(session, config.clustering_min_tickets)
    return await _serialize(session)

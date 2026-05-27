"""Cluster content-gap ranking — roadmap 3.2 ("What should I build a playbook for").

Read-only join over the existing `ticket_clusters` / `ticket_cluster_members`
snapshot (produced by the offline clustering job, roadmap 3.1), the `tickets`
table, the manual `overrides`, and the durable `playbooks` rows. NOTHING here
writes — it never touches `ai_cache` (invariant #6) and never reads
`internal_notes` (invariant #4; it only ever inspects category ids, never
ticket text).

The standout view: of the recurring-issue clusters, which ones describe a
problem the operator has NO playbook for yet? Those are exactly what a playbook
should be written for next, ranked by how often the issue recurs (cluster size).

Dominant-category rule
----------------------
A cluster spans several tickets, each with its own EFFECTIVE category (manual
override beats the AI category — invariant #13, mirroring the board's
composition rule). The cluster's *dominant* category is the most common
effective category among its member tickets. Ties break toward the lowest
category id so the ranking is deterministic. Member tickets that are
uncategorized (no AI category and no override) contribute nothing to the tally;
a cluster whose members are ALL uncategorized has no dominant category and is
skipped (we cannot suggest a category-scoped playbook for it).

Gap rule
--------
A cluster is a content gap when its dominant category has NO active
(non-archived) playbook. We deliberately rank on the single dominant category
(simple + actionable: one suggested category per row) rather than flagging
every category a cluster touches — the operator gets one clear "write a playbook
for <category>" call to action per recurring issue.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Category,
    Override,
    Playbook,
    Ticket,
    TicketCluster,
    TicketClusterMember,
)


@dataclass(frozen=True)
class ClusterGap:
    """One recurring-issue cluster whose dominant category lacks a playbook.

    `member_count` is how many of the cluster's tickets resolved to the dominant
    category (the support behind the suggestion); `size` is the full cluster size
    and the primary ranking key.
    """

    cluster_id: int
    label: str
    top_terms: list[str]
    size: int
    category_id: int
    category_name: str
    member_count: int


async def _effective_category_ids(
    session: AsyncSession,
    ticket_ids: list[str],
) -> dict[str, int]:
    """Map each ticket id → its EFFECTIVE category id (override beats AI, #13).

    Mirrors `services.playbooks.list_for_ticket`'s composition rule: a manual
    override wins when it is at least as new as the ticket's last update.
    Uncategorized tickets (no AI category, no override) are omitted from the map.
    """
    if not ticket_ids:
        return {}

    tickets = (await session.scalars(select(Ticket).where(Ticket.id.in_(ticket_ids)))).all()
    overrides = (
        await session.scalars(select(Override).where(Override.ticket_id.in_(ticket_ids)))
    ).all()
    override_by_ticket = {o.ticket_id: o for o in overrides}

    effective: dict[str, int] = {}
    for ticket in tickets:
        category_id = ticket.category_id
        override = override_by_ticket.get(ticket.id)
        if override is not None and ticket.updated_at <= override.set_at:
            category_id = override.category_id
        if category_id is not None:
            effective[ticket.id] = category_id
    return effective


def _dominant_category(category_ids: list[int]) -> int | None:
    """Most common category id in `category_ids`; ties break to the lowest id.

    Returns None for an empty list (a cluster of only-uncategorized tickets).
    """
    if not category_ids:
        return None
    counts = Counter(category_ids)
    top = max(counts.values())
    return min(cid for cid, n in counts.items() if n == top)


async def rank_gaps(session: AsyncSession) -> list[ClusterGap]:
    """Rank recurring-issue clusters whose dominant category has no playbook.

    Ordered by cluster `size` descending (most-recurring first), then cluster id
    ascending for a stable tie-break. Read-only; never touches `ai_cache` and
    never reads ticket text (only category ids participate).
    """
    clusters = (await session.scalars(select(TicketCluster))).all()
    if not clusters:
        return []

    members_by_cluster: dict[int, list[str]] = {}
    for member in (await session.scalars(select(TicketClusterMember))).all():
        members_by_cluster.setdefault(member.cluster_id, []).append(member.ticket_id)

    # Categories that currently have at least one active (non-archived) playbook.
    covered_category_ids = set(
        (
            await session.scalars(
                select(Playbook.category_id).where(Playbook.archived_at.is_(None))
            )
        ).all()
    )

    category_names = {c.id: c.name for c in (await session.scalars(select(Category))).all()}

    gaps: list[ClusterGap] = []
    for cluster in clusters:
        ticket_ids = members_by_cluster.get(cluster.id, [])
        effective = await _effective_category_ids(session, ticket_ids)
        dominant = _dominant_category(list(effective.values()))
        if dominant is None:
            continue  # no category to scope a playbook to
        if dominant in covered_category_ids:
            continue  # already has a playbook — not a gap
        member_count = sum(1 for cid in effective.values() if cid == dominant)
        gaps.append(
            ClusterGap(
                cluster_id=cluster.id,
                label=cluster.label,
                top_terms=list(cluster.top_terms),
                size=cluster.size,
                category_id=dominant,
                category_name=category_names.get(dominant, ""),
                member_count=member_count,
            )
        )

    gaps.sort(key=lambda g: (-g.size, g.cluster_id))
    return gaps

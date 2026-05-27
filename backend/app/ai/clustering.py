"""Offline recurring-issue clustering over resolved tickets' embeddings.

Roadmap 3.1. A periodic BACKGROUND job (never per-request — see the loop in
`app/main.py`) that:

  1. Reads the EXISTING 384-dim embeddings out of the `ticket_embeddings` vec
     table for RESOLVED tickets only. Those vectors were built (in roadmap 2.4)
     from the customer-visible `parts[]` + the operator's local note ONLY —
     Intercom `internal_notes[]` never entered them (invariant #4).
  2. Clusters them with `sklearn.cluster.HDBSCAN`. HDBSCAN natively flags
     density outliers as label ``-1``; we DO NOT force those into a cluster —
     they are simply dropped, so every persisted cluster is genuine.
  3. Labels each cluster with c-TF-IDF top terms. The label corpus is rebuilt
     from each ticket's `title` + customer-visible `parts[]` ONLY (invariant
     #4 again) — `internal_notes[]` is never read here.

Invariant #6: this reads `ticket_embeddings` and writes the `ticket_clusters` /
`ticket_cluster_members` tables. It NEVER reads or writes `ai_cache` and never
recomputes / busts the content signature. Clustering is a derived, disposable
snapshot — each run replaces the previous one atomically.

scikit-learn only (pinned in requirements.txt). No BERTopic / umap / standalone
`hdbscan` native build — HDBSCAN has shipped inside scikit-learn since 1.3.
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.embeddings import EMBEDDING_DIM
from app.models import Ticket, TicketCluster, TicketClusterMember
from app.util import naive_utcnow

logger = logging.getLogger(__name__)

# HDBSCAN tuning. `min_cluster_size` is the smallest group we'll call a
# "recurring" issue — two near-identical tickets is the floor. The defaults are
# deliberately conservative so a tiny single-operator corpus still yields
# structure rather than collapsing everything into noise.
_MIN_CLUSTER_SIZE = 2
# Number of c-TF-IDF terms that make up a cluster label.
_LABEL_TERMS = 4


@dataclass(frozen=True)
class _TicketDoc:
    """A resolved ticket's vector + its customer-visible label text (#4)."""

    ticket_id: str
    vector: list[float]
    label_text: str


@dataclass(frozen=True)
class ClusterResult:
    """One produced cluster, before persistence."""

    label: str
    top_terms: list[str]
    ticket_ids: list[str]


@dataclass(frozen=True)
class ClusteringOutcome:
    """Summary of one clustering run (returned for logging / tests)."""

    clusters: int
    clustered_tickets: int
    outliers: int
    skipped_reason: str | None = None


def _deserialize(blob: bytes) -> list[float]:
    """Unpack sqlite-vec's little-endian float32 blob back into a vector."""
    return list(struct.unpack(f"<{EMBEDDING_DIM}f", blob))


def _customer_visible_text(ticket: Ticket) -> str:
    """Compose the c-TF-IDF label text for a ticket from `title` + the
    customer-visible `parts[]` bodies ONLY.

    Invariant #4: `internal_notes[]` is team-only and MUST NOT contribute to a
    cluster label, so it is never read here — only `title` and `parts`.
    """
    segments: list[str] = []
    title = (ticket.title or "").strip()
    if title:
        segments.append(title)
    for part in ticket.parts or []:
        body = str(part.get("body", "")).strip()
        if body:
            segments.append(body)
    return "\n".join(segments).strip()


async def _load_resolved_docs(session: AsyncSession) -> list[_TicketDoc]:
    """Join resolved tickets to their stored embeddings.

    Reads only `tickets` (for label text) + `ticket_embeddings` (for vectors).
    Never touches `ai_cache`. A ticket with no embedding row is silently skipped
    (e.g. embeddings disabled when it was ingested)."""
    rows = (
        await session.execute(
            text(
                "SELECT t.id AS ticket_id, e.embedding AS embedding "
                "FROM tickets t "
                "JOIN ticket_embeddings e ON e.ticket_id = t.id "
                "WHERE t.resolved_at IS NOT NULL"
            )
        )
    ).all()
    if not rows:
        return []

    ticket_ids = [r.ticket_id for r in rows]
    ticket_rows = {
        t.id: t
        for t in (await session.scalars(select(Ticket).where(Ticket.id.in_(ticket_ids)))).all()
    }
    docs: list[_TicketDoc] = []
    for row in rows:
        ticket = ticket_rows.get(row.ticket_id)
        if ticket is None:
            continue
        docs.append(
            _TicketDoc(
                ticket_id=row.ticket_id,
                vector=_deserialize(row.embedding),
                label_text=_customer_visible_text(ticket),
            )
        )
    return docs


def _label_clusters(
    docs: list[_TicketDoc],
    labels: list[int],
) -> list[ClusterResult]:
    """Build a c-TF-IDF label for each non-outlier cluster.

    c-TF-IDF: concatenate every member ticket's customer-visible text into one
    "class document" per cluster, then run a single Tf-Idf over those class
    documents. The top-weighted terms per class are that cluster's label. Text
    comes from `_customer_visible_text` — `parts[]` + title only (#4).

    Outliers (HDBSCAN label ``-1``) are excluded entirely — never force-fit.
    """
    from sklearn.feature_extraction.text import TfidfVectorizer

    # Group member ids + concatenated text per cluster id, skipping -1 (noise).
    grouped: dict[int, list[str]] = {}
    texts: dict[int, list[str]] = {}
    for doc, lbl in zip(docs, labels, strict=True):
        if lbl < 0:
            continue
        grouped.setdefault(lbl, []).append(doc.ticket_id)
        texts.setdefault(lbl, []).append(doc.label_text)

    if not grouped:
        return []

    ordered_ids = sorted(grouped)
    class_documents = ["\n".join(texts[cid]) for cid in ordered_ids]

    # If every class document is empty (no customer-visible text at all), we
    # can't TF-IDF — fall back to a stable placeholder label so the run still
    # persists clusters rather than crashing.
    nonempty = [d for d in class_documents if d.strip()]
    term_matrix: Any | None = None
    feature_names: list[str] = []
    if nonempty:
        vectorizer = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            token_pattern=r"(?u)\b[a-zA-Z][a-zA-Z]+\b",  # noqa: S106 — TfidfVectorizer regex, not a secret
            max_features=2000,
        )
        try:
            matrix = vectorizer.fit_transform(class_documents)
            term_matrix = matrix.toarray()
            feature_names = list(vectorizer.get_feature_names_out())
        except ValueError:
            # Empty vocabulary (only stop words / single chars) — placeholder.
            term_matrix = None

    results: list[ClusterResult] = []
    for idx, cid in enumerate(ordered_ids):
        top_terms: list[str] = []
        if term_matrix is not None and feature_names:
            row = term_matrix[idx]
            # Indices of the highest-weighted terms, descending.
            ranked = row.argsort()[::-1]
            for term_idx in ranked[:_LABEL_TERMS]:
                if row[term_idx] <= 0:
                    break
                top_terms.append(feature_names[term_idx])
        label = " ".join(top_terms) if top_terms else f"cluster {cid + 1}"
        results.append(
            ClusterResult(
                label=label,
                top_terms=top_terms,
                ticket_ids=sorted(grouped[cid]),
            )
        )
    # Largest cluster first — the standout recurring issues lead.
    results.sort(key=lambda r: len(r.ticket_ids), reverse=True)
    return results


def _run_hdbscan(docs: list[_TicketDoc]) -> list[int]:
    """Cluster the document vectors, returning a parallel list of integer labels
    (HDBSCAN uses ``-1`` for outliers).

    Vectors are L2-normalized first: the real all-MiniLM-L6-v2 encoder already
    emits unit vectors (`normalize_embeddings=True`), so on euclidean distance
    that is equivalent to cosine similarity — the right geometry for sentence
    embeddings. Normalizing here is defensive (a no-op on already-unit vectors)
    and keeps outlier detection clean."""
    import numpy as np
    from sklearn.cluster import HDBSCAN
    from sklearn.preprocessing import normalize

    matrix = normalize(np.asarray([doc.vector for doc in docs], dtype=np.float64))
    # min_cluster_size capped at the corpus size so tiny fixtures don't error.
    min_size = min(_MIN_CLUSTER_SIZE, len(docs))
    clusterer = HDBSCAN(min_cluster_size=max(2, min_size), metric="euclidean")
    return [int(x) for x in clusterer.fit_predict(matrix)]


async def _persist(session: AsyncSession, results: list[ClusterResult]) -> None:
    """Atomically replace the previous clustering snapshot.

    Deletes all prior `ticket_clusters` (members cascade) then inserts the fresh
    ones in the same transaction. Touches ONLY the cluster tables — never
    `ai_cache` (#6)."""
    now = naive_utcnow()
    # Cascade on the FK clears members; delete the parents explicitly so the
    # snapshot is fully replaced even on backends/edge cases without cascade.
    await session.execute(delete(TicketClusterMember))
    await session.execute(delete(TicketCluster))
    for result in results:
        cluster = TicketCluster(
            label=result.label,
            top_terms=result.top_terms,
            size=len(result.ticket_ids),
            computed_at=now,
        )
        session.add(cluster)
        await session.flush()  # assign cluster.id
        for ticket_id in result.ticket_ids:
            session.add(TicketClusterMember(cluster_id=cluster.id, ticket_id=ticket_id))
    await session.commit()


async def recompute_clusters(session: AsyncSession, min_tickets: int) -> ClusteringOutcome:
    """Run one clustering pass over resolved tickets' embeddings + persist it.

    Guards on `min_tickets` so a near-empty corpus is a no-op (no crash). The
    caller owns the session; this function commits the new snapshot itself.
    """
    docs = await _load_resolved_docs(session)
    if len(docs) < min_tickets:
        return ClusteringOutcome(
            clusters=0,
            clustered_tickets=0,
            outliers=0,
            skipped_reason=f"too few resolved tickets with embeddings ({len(docs)} < {min_tickets})",
        )

    labels = _run_hdbscan(docs)
    outliers = sum(1 for lbl in labels if lbl < 0)
    results = _label_clusters(docs, labels)
    await _persist(session, results)
    return ClusteringOutcome(
        clusters=len(results),
        clustered_tickets=sum(len(r.ticket_ids) for r in results),
        outliers=outliers,
    )

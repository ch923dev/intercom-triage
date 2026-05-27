"""Local, fully-offline embedding layer. Reference: roadmap 2.4 (keystone).

A single sentence-transformers model (`all-MiniLM-L6-v2`, 384-dim, CPU) turns a
ticket's customer-visible text into a vector, stored in the `ticket_embeddings`
`vec0` virtual table (migration 0014) for nearest-neighbour retrieval.

Invariants enforced here:
  - #4: `embed_ticket` builds its text from the hydrated ticket's `parts[]` (the
    customer-visible thread) plus the operator's local note ONLY. Intercom
    `internal_notes[]` are team-only and NEVER enter an embedding.
  - #6: this is a SEPARATE store from `ai_cache`. Computing / storing an
    embedding never reads or writes the AI cache or the content signature.

The model is heavy (~80 MB download on first run, then cached on disk) and is
lazy-loaded ONCE at first use, never at import — so importing this module is
cheap and the test suite stays offline. Tests inject a deterministic fake
encoder via `set_encoder`, so `pytest` never downloads or runs the real model.
"""

from __future__ import annotations

import logging
import struct
from collections.abc import Iterable
from typing import Protocol

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas import ConversationPartSchema, HydratedTicket

logger = logging.getLogger(__name__)

# all-MiniLM-L6-v2 produces 384-dimensional embeddings (must match migration 0014).
EMBEDDING_DIM = 384
_MODEL_NAME = "all-MiniLM-L6-v2"


class Encoder(Protocol):
    """Anything that turns text into a fixed-length float vector.

    The real model (sentence-transformers) and the test fake both satisfy this.
    """

    def encode_one(self, text: str) -> list[float]: ...


# ── Encoder singleton (lazy) + test injection ─────────────────────────────────
#
# `_encoder_override` lets tests inject a deterministic, offline fake. When set,
# it short-circuits the real model entirely — nothing is ever downloaded.

_encoder_override: Encoder | None = None
_real_encoder: Encoder | None = None


def set_encoder(encoder: Encoder | None) -> None:
    """Inject (or clear, with None) the encoder used by `embed_text`.

    Tests call this to install a deterministic fake so the suite stays offline
    and fast. Production never calls it — the lazy real model is used.
    """
    global _encoder_override
    _encoder_override = encoder


class _SentenceTransformerEncoder:
    """Wraps a lazily-loaded sentence-transformers model. Loaded ONCE."""

    def __init__(self) -> None:
        # Import is local so the heavy dependency only loads when the real model
        # is actually instantiated — never at module import, never in tests.
        from sentence_transformers import SentenceTransformer

        # CPU-only by default; the local single-operator tool has no GPU
        # assumption and the model is tiny.
        self._model = SentenceTransformer(_MODEL_NAME, device="cpu")

    def encode_one(self, text: str) -> list[float]:
        vector = self._model.encode(
            text,
            normalize_embeddings=True,
            convert_to_numpy=True,
        )
        return [float(x) for x in vector.tolist()]


def _get_encoder() -> Encoder:
    """Return the active encoder: the test override if set, else the lazily
    constructed real model (built once and memoized)."""
    global _real_encoder
    if _encoder_override is not None:
        return _encoder_override
    if _real_encoder is None:
        logger.info("loading embedding model %s (first use)", _MODEL_NAME)
        _real_encoder = _SentenceTransformerEncoder()
    return _real_encoder


def embed_text(text_input: str) -> list[float]:
    """Encode arbitrary text into a 384-dim embedding using the active encoder."""
    return _get_encoder().encode_one(text_input)


# ── Text extraction (invariant #4) ────────────────────────────────────────────


def _parts_text(parts: Iterable[ConversationPartSchema]) -> str:
    """Join the customer-visible parts into one block. Mirrors the AI prompt's
    transcript shape (author tag + body) so the embedding sees the same content
    the categorizer does. Empty bodies are skipped."""
    rendered: list[str] = []
    for part in parts:
        body = part.body.strip()
        if not body:
            continue
        who = part.author.name or part.author.email or part.author.type or "user"
        rendered.append(f"[{who}] {body}")
    return "\n\n".join(rendered)


def build_embedding_text(ticket: HydratedTicket, operator_note: str | None = None) -> str:
    """Compose the text to embed for a ticket: title + customer-visible parts +
    the operator's local note. NEVER includes `internal_notes` (invariant #4).

    `operator_note` is the operator's own `ticket_notes.body` jot — durable,
    operator-authored context. It is distinct from Intercom internal notes.
    """
    segments: list[str] = []
    title = (ticket.title or "").strip()
    if title:
        segments.append(title)
    parts_block = _parts_text(ticket.parts)
    if parts_block:
        segments.append(parts_block)
    if operator_note:
        note = operator_note.strip()
        if note:
            segments.append(f"[operator note] {note}")
    return "\n\n".join(segments).strip()


# ── Vector serialization + storage ────────────────────────────────────────────


def _serialize(vector: list[float]) -> bytes:
    """Pack a float vector into the little-endian float32 blob sqlite-vec wants."""
    return struct.pack(f"<{len(vector)}f", *vector)


async def store_embedding(session: AsyncSession, ticket_id: str, vector: list[float]) -> None:
    """Upsert one ticket's embedding into the `vec0` table.

    A `vec0` table does not support UPSERT, so we delete-then-insert. This is a
    SEPARATE store from `ai_cache` — it never touches the cache or the content
    signature (invariant #6). The caller owns the transaction / commit.
    """
    if len(vector) != EMBEDDING_DIM:
        raise ValueError(f"expected {EMBEDDING_DIM}-dim embedding, got {len(vector)}")
    blob = _serialize(vector)
    await session.execute(
        text("DELETE FROM ticket_embeddings WHERE ticket_id = :tid"),
        {"tid": ticket_id},
    )
    await session.execute(
        text("INSERT INTO ticket_embeddings (ticket_id, embedding) VALUES (:tid, :emb)"),
        {"tid": ticket_id, "emb": blob},
    )


async def embed_and_store_ticket(
    session: AsyncSession,
    ticket: HydratedTicket,
    operator_note: str | None = None,
) -> bool:
    """Compute + store the embedding for one ticket from `parts[]` + operator note.

    Returns True if an embedding was stored, False if there was nothing to embed
    (no customer-visible text and no operator note). Encoding the empty string
    is skipped so we don't store a degenerate zero-content vector.
    """
    body = build_embedding_text(ticket, operator_note)
    if not body:
        return False
    vector = embed_text(body)
    await store_embedding(session, ticket.id, vector)
    return True


# ── Nearest-neighbour query ───────────────────────────────────────────────────


async def nearest_neighbours(
    session: AsyncSession,
    vector: list[float],
    k: int = 5,
) -> list[tuple[str, float]]:
    """Return up to `k` nearest stored tickets to `vector` as `(ticket_id,
    distance)` ordered closest-first. Distance is sqlite-vec's default L2."""
    blob = _serialize(vector)
    rows = (
        await session.execute(
            text(
                "SELECT ticket_id, distance FROM ticket_embeddings "
                "WHERE embedding MATCH :emb AND k = :k ORDER BY distance"
            ),
            {"emb": blob, "k": k},
        )
    ).all()
    return [(row.ticket_id, float(row.distance)) for row in rows]


async def nearest_to_text(
    session: AsyncSession,
    query_text: str,
    k: int = 5,
) -> list[tuple[str, float]]:
    """Convenience: embed `query_text` then run the nearest-neighbour query."""
    return await nearest_neighbours(session, embed_text(query_text), k=k)

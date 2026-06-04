"""`GET /health` — startup smoke + cred summary.

Reference: plan.md §4, tasks.md T005.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app import __version__
from app.ai import embeddings
from app.config import AppConfig
from app.deps import get_app_config
from app.models import sqlite_vec_loaded
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(config: AppConfig = Depends(get_app_config)) -> HealthResponse:
    missing = config.missing_secrets

    # Semantic layer (few-shot / RAG / clustering) is operational only when it's
    # enabled AND both halves loaded: the embedding model and the sqlite-vec
    # extension. Clustering additionally rides on embeddings. Both load
    # best-effort and otherwise fail silently — surface it so the operator isn't
    # left wondering why semantic features do nothing.
    embeddings_available = (
        config.embeddings_enabled and embeddings.encoder_available() and sqlite_vec_loaded()
    )
    clustering_available = config.clustering_enabled and embeddings_available

    # Degraded when a secret is missing, or the operator asked for embeddings but
    # the layer failed to come up (enabled-but-unavailable is the actionable case).
    degraded = bool(missing) or (config.embeddings_enabled and not embeddings_available)

    return HealthResponse(
        status="degraded" if degraded else "ok",
        version=__version__,
        model=config.openrouter_model,
        openrouter_configured=config.openrouter_configured,
        intercom_configured=config.intercom_configured,
        missing_secrets=missing,
        review_confidence_threshold=config.review_confidence_threshold,
        embeddings_available=embeddings_available,
        clustering_available=clustering_available,
    )

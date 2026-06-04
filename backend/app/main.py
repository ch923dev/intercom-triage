"""FastAPI app entrypoint.

Reference: plan.md §2 (architecture), §4 (API), tasks.md T005, T008, T012, T028.

Run:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 4000
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.intercom import IntercomClient
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig, get_config
from app.db import make_engine, make_session_factory
from app.metrics import metrics
from app.models import init_db
from app.observability import configure_logging, log_event
from app.routers import attachments as attachments_router
from app.routers import categories as categories_router
from app.routers import clusters as clusters_router
from app.routers import followups as followups_router
from app.routers import health as health_router
from app.routers import metrics as metrics_router
from app.routers import note_entries as note_entries_router
from app.routers import notes as notes_router
from app.routers import playbooks as playbooks_router
from app.routers import proposals as proposals_router
from app.routers import settings as settings_router
from app.routers import snippets as snippets_router
from app.routers import stats as stats_router
from app.routers import tickets as tickets_router
from app.services.cache import sweep_expired

_CACHE_SWEEP_INTERVAL_SECONDS = 3600


async def _cache_sweep_loop(
    session_factory: async_sessionmaker[AsyncSession],
    ttl_seconds: int,
) -> None:
    """Background loop: sweep expired ai_cache rows once at startup, then hourly."""
    while True:
        try:
            async with session_factory() as session:
                count = await sweep_expired(session, ttl_seconds)
            if count:
                log_event("cache_sweep", op="background", rows_deleted=count)
                metrics.incr("cache_rows_swept_total", count)
        except Exception as exc:
            log_event(
                "cache_sweep_error",
                level=logging.WARNING,
                op="background",
                error=str(exc),
            )
        await asyncio.sleep(_CACHE_SWEEP_INTERVAL_SECONDS)


async def _attachment_sweep_loop(
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig,
) -> None:
    """Background loop: hard-delete expired soft-deleted attachments + unlink
    orphaned disk files. Once at startup, then every
    `config.attachment_sweep_interval_seconds`."""
    from app.services.attachments import sweep_attachments

    while True:
        try:
            async with session_factory() as session:
                result = await sweep_attachments(session, config)
            if result.rows_deleted or result.files_unlinked:
                log_event(
                    "attachment_sweep",
                    op="background",
                    rows_deleted=result.rows_deleted,
                    files_unlinked=result.files_unlinked,
                )
        except Exception as exc:
            log_event(
                "attachment_sweep_error",
                level=logging.WARNING,
                op="background",
                error=str(exc),
            )
        await asyncio.sleep(config.attachment_sweep_interval_seconds)


async def _clustering_loop(
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig,
) -> None:
    """Background loop: recompute recurring-issue clusters (roadmap 3.1) over
    RESOLVED tickets' existing embeddings. Once at startup, then every
    `config.clustering_interval_seconds`.

    Reads `ticket_embeddings` + `tickets`; NEVER touches `ai_cache` / the content
    signature (invariant #6). Gated on `embeddings_enabled` (no embeddings means
    nothing to cluster). Catches broad `Exception` on purpose so a clustering
    failure can never stop the loop ticking."""
    from app.ai.clustering import recompute_clusters

    while True:
        try:
            async with session_factory() as session:
                outcome = await recompute_clusters(session, config.clustering_min_tickets)
            log_event(
                "clustering_run",
                op="background",
                clusters=outcome.clusters,
                clustered_tickets=outcome.clustered_tickets,
                outliers=outcome.outliers,
                skipped=outcome.skipped_reason or "",
            )
        except Exception as exc:
            log_event(
                "clustering_error",
                level=logging.WARNING,
                op="background",
                error=str(exc),
            )
        await asyncio.sleep(config.clustering_interval_seconds)


async def _intercom_poll_loop(
    session_factory: async_sessionmaker[AsyncSession],
    config: AppConfig,
    intercom: IntercomClient,
    openrouter: OpenRouterClient | None,
) -> None:
    """Background loop: poll Intercom and ingest. Once at startup, then every
    `config.intercom_poll_interval_seconds`.

    Catches broad `Exception` on purpose — a transient Intercom/network failure
    (including a bad-token `IntercomAuthError`) must never stop the loop ticking;
    the operator fixes the token and the next tick recovers."""
    from app.services.sync import run_sync_cycle

    while True:
        try:
            async with session_factory() as session:
                out = await run_sync_cycle(
                    session=session,
                    openrouter=openrouter,
                    intercom=intercom,
                    config=config,
                )
            log_event(
                "intercom_poll",
                op="background",
                received=out.received,
                categorized=out.categorized,
                skipped_known=out.skipped_known,
                closed_detected=out.closed_detected,
            )
        except Exception as exc:
            log_event(
                "intercom_poll_error",
                level=logging.WARNING,
                op="background",
                error=str(exc),
            )
        await asyncio.sleep(config.intercom_poll_interval_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot: logging → DB (create_all + seed) → external clients. Reverse on shutdown."""
    config = get_config()
    configure_logging(config.log_level)

    engine = make_engine(config.database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine, session_factory)

    config.attachments_dir.mkdir(parents=True, exist_ok=True)
    (config.attachments_dir / "thumbs").mkdir(parents=True, exist_ok=True)

    # External clients — created only when their secret is present (FR-014).
    openrouter: OpenRouterClient | None = None
    if config.openrouter_configured:
        openrouter = OpenRouterClient(
            config.openrouter_api_key,
            referer=config.openrouter_referer,
            title=config.openrouter_title,
        )

    intercom: IntercomClient | None = None
    if config.intercom_configured:
        intercom = IntercomClient(
            config.intercom_access_token,
            base=config.intercom_api_base,
            version=config.intercom_api_version,
            contact_cache_ttl_seconds=config.intercom_contact_cache_ttl_seconds,
        )

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.config = config
    app.state.openrouter = openrouter
    app.state.intercom = intercom

    if config.missing_secrets:
        log_event(
            "degraded_boot",
            level=logging.WARNING,
            op="startup",
            missing=",".join(config.missing_secrets),
        )

    sweep_task = asyncio.create_task(
        _cache_sweep_loop(session_factory, config.cache_ttl_seconds),
    )
    app.state.sweep_task = sweep_task

    attachment_sweep_task = asyncio.create_task(
        _attachment_sweep_loop(session_factory, config),
    )
    app.state.attachment_sweep_task = attachment_sweep_task

    # Roadmap 3.1 — recurring-issue clustering. Only spawned when enabled AND
    # embeddings exist to cluster over.
    clustering_task: asyncio.Task[None] | None = None
    if config.clustering_enabled and config.embeddings_enabled:
        clustering_task = asyncio.create_task(_clustering_loop(session_factory, config))
    app.state.clustering_task = clustering_task

    # Intercom poller — only when a token is set AND a positive interval is
    # configured (interval 0 = manual `POST /tickets/sync` only). No autonomous
    # Intercom traffic or token spend out of the box.
    intercom_poll_task: asyncio.Task[None] | None = None
    if intercom is not None and config.intercom_poll_interval_seconds > 0:
        intercom_poll_task = asyncio.create_task(
            _intercom_poll_loop(session_factory, config, intercom, openrouter),
        )
    app.state.intercom_poll_task = intercom_poll_task

    try:
        yield
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        attachment_sweep_task.cancel()
        try:
            await attachment_sweep_task
        except asyncio.CancelledError:
            pass
        if clustering_task is not None:
            clustering_task.cancel()
            try:
                await clustering_task
            except asyncio.CancelledError:
                pass
        if intercom_poll_task is not None:
            intercom_poll_task.cancel()
            try:
                await intercom_poll_task
            except asyncio.CancelledError:
                pass
        if openrouter is not None:
            await openrouter.aclose()
        if intercom is not None:
            await intercom.aclose()
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Intercom Triage",
        version="0.1.0",
        description="Local single-operator triage for Intercom conversations.",
        lifespan=lifespan,
    )

    # CORS — webapp on 5173 + Chrome extension origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_origin_regex=r"chrome-extension://[a-z]{32}",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router.router)
    app.include_router(categories_router.router)
    app.include_router(proposals_router.router)
    app.include_router(tickets_router.router)
    app.include_router(settings_router.router)
    app.include_router(followups_router.router)
    app.include_router(notes_router.router)
    app.include_router(note_entries_router.router)
    app.include_router(playbooks_router.router)
    app.include_router(snippets_router.router)
    app.include_router(attachments_router.router)
    app.include_router(clusters_router.router)
    app.include_router(metrics_router.router)
    app.include_router(stats_router.router)

    return app


app = create_app()

"""FastAPI app entrypoint.

Reference: plan.md §2 (architecture), §4 (API), tasks.md T005, T008, T012, T028.

Run:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.clients.intercom import IntercomClient, IntercomError
from app.clients.openrouter import OpenRouterClient
from app.config import get_config
from app.db import make_engine, make_session_factory
from app.metrics import metrics
from app.models import init_db
from app.observability import configure_logging, log_event
from app.routers import categories as categories_router
from app.routers import followups as followups_router
from app.routers import health as health_router
from app.routers import metrics as metrics_router
from app.routers import notes as notes_router
from app.routers import proposals as proposals_router
from app.routers import settings as settings_router
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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot: logging → DB (create_all + seed) → external clients. Reverse on shutdown."""
    config = get_config()
    configure_logging(config.log_level)

    engine = make_engine(config.database_url)
    session_factory = make_session_factory(engine)
    await init_db(engine, session_factory)

    # External clients — created only when their secret is present (FR-014).
    intercom: IntercomClient | None = None
    if config.intercom_configured:
        intercom = IntercomClient(config.intercom_access_token)
        try:
            workspace_id = await intercom.resolve_workspace_id()
            log_event("intercom_ready", op="startup", workspace_id=workspace_id)
        except IntercomError as exc:
            log_event(
                "intercom_unresolved",
                level=logging.WARNING,
                op="startup",
                error=str(exc),
            )

    openrouter: OpenRouterClient | None = None
    if config.openrouter_configured:
        openrouter = OpenRouterClient(
            config.openrouter_api_key,
            referer=config.openrouter_referer,
            title=config.openrouter_title,
        )

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.config = config
    app.state.intercom = intercom
    app.state.openrouter = openrouter

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

    try:
        yield
    finally:
        sweep_task.cancel()
        try:
            await sweep_task
        except asyncio.CancelledError:
            pass
        if intercom is not None:
            await intercom.aclose()
        if openrouter is not None:
            await openrouter.aclose()
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
    app.include_router(metrics_router.router)

    return app


app = create_app()

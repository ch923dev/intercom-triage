"""FastAPI app entrypoint.

Reference: plan.md §2 (architecture), §4 (API), tasks.md T005, T008, T012, T028.

Run:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.clients.intercom import IntercomClient, IntercomError
from app.clients.openrouter import OpenRouterClient
from app.config import get_config
from app.db import make_engine, make_session_factory
from app.models import init_db
from app.observability import configure_logging, log_event
from app.routers import categories as categories_router
from app.routers import health as health_router
from app.routers import proposals as proposals_router
from app.routers import settings as settings_router
from app.routers import tickets as tickets_router


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

    try:
        yield
    finally:
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

    return app


app = create_app()

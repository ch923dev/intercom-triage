"""FastAPI app entrypoint.

Reference: plan.md §2 (architecture), §4 (API), tasks.md T005.

Run:
    uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_config
from app.db import make_engine, make_session_factory
from app.models import init_db
from app.routers import categories as categories_router
from app.routers import health as health_router

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Boot: engine → factory → init_db (create_all + seed). Shutdown: dispose engine."""
    config = get_config()
    logging.basicConfig(
        level=config.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    engine = make_engine(config.database_url)
    session_factory = make_session_factory(engine)

    await init_db(engine, session_factory)

    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.config = config

    if config.missing_secrets:
        log.warning(
            "Booting in degraded mode — missing secrets: %s",
            ", ".join(config.missing_secrets),
        )

    try:
        yield
    finally:
        await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Intercom Triage",
        version="0.1.0",
        description="Local single-operator triage for Intercom conversations.",
        lifespan=lifespan,
    )

    # CORS — webapp on 5173 + Chrome extension origin.
    # `chrome-extension://<id>` needs a regex; the id isn't known until install.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_origin_regex=r"chrome-extension://[a-z]{32}",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health_router.router)
    app.include_router(categories_router.router)

    return app


app = create_app()

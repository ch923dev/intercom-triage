"""FastAPI dependencies that read process-wide state off `app.state`.

The OpenRouter client and the resolved config are bound onto `app.state` in
the lifespan hook (see `main.py`).
"""

from __future__ import annotations

from fastapi import Request

from app.clients.intercom import IntercomClient
from app.clients.openrouter import OpenRouterClient
from app.config import AppConfig


def get_app_config(request: Request) -> AppConfig:
    config: AppConfig = request.app.state.config
    return config


def get_openrouter(request: Request) -> OpenRouterClient | None:
    client: OpenRouterClient | None = getattr(request.app.state, "openrouter", None)
    return client


def get_intercom(request: Request) -> IntercomClient | None:
    client: IntercomClient | None = getattr(request.app.state, "intercom", None)
    return client

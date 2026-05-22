"""Application configuration — reads `.env` via pydantic-settings.

Reference: plan.md §1 (Stack), tasks.md T004.

The class is intentionally named `AppConfig` so it does not collide with the
SQLAlchemy `Settings` table defined in `models.py`.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """All configuration is loaded from `.env` at the backend working directory.

    Missing secrets do NOT prevent startup — `/health` reports them so the
    operator can see what's wired up without booting blind (FR-014, T005).
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Intercom ──────────────────────────────────────────────────────────────
    intercom_access_token: str = ""

    # ── OpenRouter ────────────────────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_referer: str = "http://localhost:8000"
    openrouter_title: str = "Intercom Triage"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/triage.db"

    # ── Behavior ──────────────────────────────────────────────────────────────
    default_lookback_hours: int = Field(default=24, ge=1, le=720)
    max_tickets_per_fetch: int = Field(default=100, ge=1, le=1000)
    ai_concurrency: int = Field(default=4, ge=1, le=64)
    cache_ttl_seconds: int = Field(default=300, ge=0)

    # ── Server ────────────────────────────────────────────────────────────────
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def intercom_configured(self) -> bool:
        return bool(self.intercom_access_token.strip())

    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def missing_secrets(self) -> list[str]:
        out: list[str] = []
        if not self.intercom_configured:
            out.append("INTERCOM_ACCESS_TOKEN")
        if not self.openrouter_configured:
            out.append("OPENROUTER_API_KEY")
        return out


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Cached singleton. Override in tests via `get_config.cache_clear()`."""
    return AppConfig()

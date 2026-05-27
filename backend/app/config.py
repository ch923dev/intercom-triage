"""Application configuration — reads `.env` via pydantic-settings.

Reference: plan.md §1 (Stack), tasks.md T004.

The class is intentionally named `AppConfig` so it does not collide with the
SQLAlchemy `Settings` table defined in `models.py`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Cap on the number of ticket ids in a single bulk request (FR-036, plan §8d).
# Module constant so `app.schemas` and the bulk endpoints share one source of
# truth. Bumping this requires a code change rather than an env override — the
# value bounds memory + transaction size per request and shouldn't drift per
# environment.
MAX_BULK_IDS: int = 200

# Cap on tickets accepted in one POST /tickets/ingest call. Bounds memory +
# per-request OpenRouter fan-out / token spend. Code constant for the same
# reasons as MAX_BULK_IDS — must not drift per environment.
MAX_INGEST_TICKETS: int = 500


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

    # ── OpenRouter ────────────────────────────────────────────────────────────
    openrouter_api_key: str = ""
    openrouter_model: str = "anthropic/claude-sonnet-4.5"
    openrouter_referer: str = "http://localhost:4000"
    openrouter_title: str = "Intercom Triage"

    # ── Database ──────────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/triage.db"

    # ── Behavior ──────────────────────────────────────────────────────────────
    max_tickets_per_fetch: int = Field(default=100, ge=1, le=1000)
    ai_concurrency: int = Field(default=4, ge=1, le=64)
    cache_ttl_seconds: int = Field(default=300, ge=0)

    # ── Attachments (note attachments spec) ──────────────────────────────────
    attachments_dir: Path = Path("./data/attachments")
    attachment_gc_days: int = Field(default=7, ge=0)
    attachment_sweep_interval_seconds: int = Field(default=86_400, ge=60)
    # Hard cap on a single uploaded file. Bounds memory per request — an
    # unbounded read would let one upload OOM the local process.
    attachment_max_bytes: int = Field(default=25 * 1024 * 1024, ge=1)

    # ── Embeddings (local, offline) ──────────────────────────────────────────
    # Local sentence-transformers model (all-MiniLM-L6-v2, 384-dim, CPU). The
    # ~80 MB model loads lazily on first use; disable to skip the heavy import
    # entirely (e.g. low-RAM machines, or to keep ingest fast). When off, the
    # ingest hook is a no-op — no embeddings are computed or stored.
    embeddings_enabled: bool = True

    # ── Few-shot categorization (roadmap 2.5) ────────────────────────────────
    # When categorizing an uncached ticket, inject the nearest CONFIRMED-override
    # neighbours (operator-confirmed gold labels) as in-context examples. Set to
    # 0 to disable injection entirely (the prompt then matches the cold-corpus
    # path exactly). The retrieval is gated on `embeddings_enabled` — no
    # embeddings means no neighbours to retrieve.
    fewshot_examples: int = Field(default=3, ge=0, le=10)

    # ── Server ────────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def missing_secrets(self) -> list[str]:
        out: list[str] = []
        if not self.openrouter_configured:
            out.append("OPENROUTER_API_KEY")
        return out


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Cached singleton. Override in tests via `get_config.cache_clear()`."""
    return AppConfig()

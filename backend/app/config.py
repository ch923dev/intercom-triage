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

    # ── Model cascade (roadmap 2.2) ───────────────────────────────────────────
    # Route easy tickets to a cheap model, escalate low-confidence ones to the
    # strong `openrouter_model`. The cheap model is a current OpenRouter id —
    # Claude 3.5 Haiku is ~3.75x cheaper per token than Sonnet 4.5 on both input
    # and output (see app/pricing.py) and supports the strict JSON-schema output
    # the categorization prompt requires. Set `openrouter_cheap_model` equal to
    # `openrouter_model` (or leave the cascade disabled) to fall back to a single
    # strong-model call.
    openrouter_cheap_model: str = "anthropic/claude-3.5-haiku"
    # When the cheap model's self-reported confidence is BELOW this threshold (or
    # the cheap call fails / returns malformed output) the ticket escalates to the
    # strong model. 0.7 keeps only confident cheap answers; raise it to escalate
    # more aggressively (better accuracy, more double calls), lower it to trust
    # the cheap model more.
    cascade_escalate_below: float = Field(default=0.7, ge=0.0, le=1.0)
    # Disabled by default: opt-in so out-of-the-box behavior is unchanged (a
    # single strong-model call). The escalation rate must be measured on a real
    # corpus before flipping this on — a >40% rate erases the cost savings.
    cascade_enabled: bool = False

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

    # ── Needs-review lane (roadmap 2.3) ───────────────────────────────────────
    # An OPEN, non-overridden ticket whose categorization self-confidence is
    # BELOW this threshold surfaces in the webapp "needs review" lane — a
    # view-layer split over the existing `ai_confidence`, NOT a stored state
    # (mirrors invariant #10 / the non-actionable column). The operator reviews
    # the lane and confirming a ticket (writing an override) clears it.
    #
    # Default 0.65 is CALIBRATED, not guessed — see
    # `backend/tests/test_review_calibration.py`. On a representative spread of
    # categorization confidences (fallbacks at 0.0; genuine answers across the
    # 0.3–0.95 band) labelled by whether the operator later overrode them, 0.65
    # is the threshold that catches the large majority of would-be-overridden
    # tickets while leaving most correct ones off the lane (it sits above the
    # card's 0.5 "low confidence" tint and just under the cascade's 0.7
    # trust-the-cheap-model bar — the zone where the AI is unsure enough to be
    # worth a human glance). The webapp mirrors this default as
    # `REVIEW_CONFIDENCE_THRESHOLD` (webapp/src/utils/review.ts); keep them in
    # sync. The value is also surfaced on `GET /health` for auditability.
    review_confidence_threshold: float = Field(default=0.65, ge=0.0, le=1.0)

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

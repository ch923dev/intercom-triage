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

    # ── Intercom (official REST API) ──────────────────────────────────────────
    # The backend polls Intercom's documented API directly with a workspace
    # Access Token (cross-package invariant #1). The token is a secret; an empty
    # token boots the backend degraded (no poller, `/tickets/sync` → 503) exactly
    # like a missing OpenRouter key. `intercom_workspace_app_id` is the workspace
    # slug used only to build deep-link URLs (e.g. `j3dxf22l`) — NOT a secret.
    intercom_access_token: str = ""
    intercom_api_base: str = "https://api.intercom.io"
    # Pinned API version — `part_type` enum + contact `location` shapes are
    # version-stable only when pinned. Bump deliberately, re-verify a live
    # payload (the normalizer mapping depends on it).
    intercom_api_version: str = "2.13"
    intercom_workspace_app_id: str = ""
    # Background poller cadence. 0 = OFF (manual `POST /tickets/sync` only) so an
    # out-of-the-box boot makes zero autonomous Intercom traffic / token spend.
    intercom_poll_interval_seconds: int = Field(default=0, ge=0)
    # Bounded fan-out for the per-conversation detail + contact fetches.
    intercom_poll_concurrency: int = Field(default=4, ge=1, le=32)
    # Closure pass: how far back to look for open→closed transitions among
    # tracked-open tickets that fell off the open list. Default 7 days.
    intercom_closure_lookback_seconds: int = Field(default=7 * 24 * 3600, ge=0)
    # In-process TTL for the contact-enrichment cache (location/timezone/phone/
    # company panel fields). Repeat customers across a batch reuse the fetch.
    intercom_contact_cache_ttl_seconds: int = Field(default=300, ge=0)

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

    # ── Recurring-issue clustering (roadmap 3.1) ─────────────────────────────
    # Offline periodic background job that clusters RESOLVED tickets' existing
    # embeddings (HDBSCAN) and labels each cluster with c-TF-IDF top terms drawn
    # from `parts[]` + title ONLY (invariant #4). It reads `ticket_embeddings`
    # and never touches `ai_cache` / the content signature (invariant #6).
    # Gated on `embeddings_enabled` — no embeddings means nothing to cluster.
    clustering_enabled: bool = True
    # Cadence: once at startup, then every interval. Default 6h (clustering is
    # cheap on a single operator's corpus but does not need to be fresh-to-the-
    # minute; 3.2 consumes the persisted snapshot).
    clustering_interval_seconds: int = Field(default=21_600, ge=60)
    # Below this many resolved tickets with embeddings, skip the run (HDBSCAN
    # needs a handful of points to find structure; fewer is just noise).
    clustering_min_tickets: int = Field(default=5, ge=2)

    # ── Server ────────────────────────────────────────────────────────────────
    log_level: str = "INFO"

    # ── Auth / sessions (Phase 1: hosted multi-user) ──────────────────────────
    # Required in production — boot hard-fails if empty (see main.lifespan).
    session_jwt_secret: str = ""
    session_access_ttl_seconds: int = Field(default=1800, ge=60)
    session_refresh_ttl_seconds: int = Field(default=30 * 24 * 3600, ge=300)
    # Fernet key (urlsafe-base64, 32 bytes) used to encrypt the stored OnlySales
    # refresh token at rest. Empty → upstream refresh is not stored.
    session_refresh_encryption_key: str = ""
    onlysales_auth_base: str = "https://pyapi.onlysales.io"
    session_cookie_name: str = "triage_refresh"
    session_cookie_secure: bool = True  # set False for plain-http local dev
    session_cookie_samesite: str = "lax"
    login_rate_max_attempts: int = Field(default=10, ge=1)
    login_rate_window_seconds: int = Field(default=300, ge=1)
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]
    )

    # ── Derived helpers ───────────────────────────────────────────────────────
    @property
    def openrouter_configured(self) -> bool:
        return bool(self.openrouter_api_key.strip())

    @property
    def intercom_configured(self) -> bool:
        return bool(self.intercom_access_token.strip())

    @property
    def session_secret_configured(self) -> bool:
        return bool(self.session_jwt_secret.strip())

    @property
    def missing_secrets(self) -> list[str]:
        out: list[str] = []
        if not self.openrouter_configured:
            out.append("OPENROUTER_API_KEY")
        if not self.intercom_configured:
            out.append("INTERCOM_ACCESS_TOKEN")
        return out


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    """Cached singleton. Override in tests via `get_config.cache_clear()`."""
    return AppConfig()

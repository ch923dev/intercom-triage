# Multi-Hosted-User — Phase 1: Auth Core — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a real login gate in front of the whole app — the webapp proxies an OnlySales email/password login through our backend, which mirrors the user, issues its own session (stateless access JWT + DB-backed revocable refresh in an httpOnly cookie), and requires a valid access token on every route except health + login + refresh.

**Architecture:** Browser → `POST /auth/login` on our FastAPI backend → forwards to `pyapi.onlysales.io/auth/login` → on success we upsert a `users` mirror row, create a `sessions` row (hashed refresh + encrypted upstream refresh), set an httpOnly refresh cookie, and return a short-lived access JWT. A `get_current_user` dependency verifies that JWT **offline** (HS256, no DB hit) on every protected router and yields a `CurrentUser` value object from the claims. The Vue webapp holds the access token in memory, sends it as a Bearer header, and on `401` silently calls `POST /auth/refresh` (cookie) once then retries.

**Tech Stack:** FastAPI + async SQLAlchemy 2.0 + Alembic + Pydantic v2 (backend); PyJWT (HS256 access tokens) + cryptography/Fernet (encrypt the upstream refresh token at rest); httpx + pytest-httpx (OnlySales client + its tests); Vue 3 + Pinia + plain `fetch` + Vitest/happy-dom (webapp).

**Spec:** `docs/superpowers/specs/2026-06-05-multi-hosted-user-design.md` (§4 architecture, §5.1 users/sessions, §6 API, §7 webapp, §8 security). This plan implements spec Phase 1 only. Phases 2–5 (attribution, assignment/My-Queue, per-user follow-ups/notes, hosting hardening) get their own plans.

**Branch:** `feat/multi-hosted-user` (already created, off the extension-removed `refactor/remove-extension` state).

---

## Conventions confirmed from the codebase (read before starting)

- **Backend config** (`backend/app/config.py`): `AppConfig(BaseSettings)` with `SettingsConfigDict(env_file=".env", extra="ignore")`; secrets default to `""`; cached via `@lru_cache` `get_config()`; tests clear it with `get_config.cache_clear()`.
- **DB** (`backend/app/db.py`): `make_engine` / `make_session_factory`; `get_session(request)` yields `AsyncSession` from `request.app.state.session_factory`.
- **Deps** (`backend/app/deps.py`): functions read `request.app.state.*`, may return `None`.
- **Routers**: `APIRouter(prefix="/x", tags=["x"])`, async endpoints, `Depends(get_session)`, `response_model=`, call `app.services.x as svc`.
- **Services**: `async def`, take `AsyncSession`, own the `.commit()`, raise `HTTPException` directly, return Pydantic schemas; timestamps via `app.util.naive_utcnow()`.
- **Models** (`backend/app/models.py`): `Mapped[T]` + `mapped_column(...)`, `CheckConstraint` in `__table_args__`, `init_db` runs Alembic then seeds.
- **Migrations** (`backend/alembic/versions/`): `revision`/`down_revision` strings, `op.batch_alter_table`, `upgrade`/`downgrade`. Current head is **0020**; this plan adds **0021**.
- **Backend tests** (`backend/tests/conftest.py`): `app` fixture wires engine/factory/`test_config` and calls `init_db`; `client` (ASGI `AsyncClient`), `session` fixtures; `@pytest.mark.asyncio`; `dependency_overrides[get_config]`.
- **Webapp api** (`webapp/src/api/client.ts`): `request<T>(path, init)` wraps `fetch(BASE+path)`, `BASE='/api'`, throws `ApiError`; `export const api = { ... }`.
- **Webapp stores**: setup-style `defineStore('x', () => { ... return {...} })`, optimistic try/catch.
- **Webapp tests**: `setActivePinia(createPinia())` in `beforeEach`; `vi.mock('@/api/client', () => ({ api: { ... } }))`; happy-dom; files `*.spec.ts`; `globals:false` so import `{ describe, it, expect }`.
- **Run a single backend test:** from `backend/`, `./.venv/Scripts/python -m pytest tests/test_x.py::test_y -v` (use the venv per the project's `backend-gate-needs-venv` note — bare `pytest` drifts off pins).
- **Run a single webapp test:** from `webapp/`, `npx vitest run src/stores/x.spec.ts`.

---

## File structure (created / modified in Phase 1)

**Backend — create:**
- `backend/app/security/__init__.py` — package marker.
- `backend/app/security/tokens.py` — access-JWT mint/verify, refresh-token gen/hash, upstream-refresh encrypt/decrypt. One responsibility: cryptographic token primitives (pure, no DB).
- `backend/app/security/ratelimit.py` — tiny in-memory fixed-window limiter for `/auth/login`.
- `backend/app/clients/onlysales.py` — async login/refresh proxy to `pyapi.onlysales.io`.
- `backend/app/services/auth.py` — login/refresh/logout orchestration + user-mirror upsert + session lifecycle.
- `backend/app/routers/auth.py` — `/auth/*` + `/users` endpoints.
- `backend/alembic/versions/0021_add_auth_tables.py` — `users` + `sessions` tables.
- Tests: `backend/tests/test_security_tokens.py`, `test_onlysales_client.py`, `test_auth_service.py`, `test_auth_api.py`, `test_auth_required.py`, `test_ratelimit.py`.

**Backend — modify:**
- `backend/requirements.txt` — add `PyJWT`, `cryptography`.
- `backend/app/config.py` — add session/cookie/OnlySales/CORS/rate-limit fields.
- `backend/app/models.py` — add `User` + `Session` models.
- `backend/app/schemas.py` — add `LoginRequest`, `LoginResponse`, `UserOut`, `MeResponse`.
- `backend/app/deps.py` — add `get_onlysales`, `get_current_user`, `CurrentUser`.
- `backend/app/main.py` — wire OnlySales client into `app.state`; include the auth router; apply `Depends(get_current_user)` to every protected router; `allow_credentials=True` + configurable CORS origins; boot-guard `session_jwt_secret`.
- `backend/tests/conftest.py` — set `session_jwt_secret` in `test_config`; default-authenticate the existing suite via `dependency_overrides[get_current_user]`; add `unauth_client` fixture.

**Webapp — create:**
- `webapp/src/types/auth.ts` — `User`, `LoginRequest`, `LoginResponse`, `MeResponse`.
- `webapp/src/stores/auth.ts` — in-memory access token + current user + login/logout/bootstrap.
- `webapp/src/components/LoginView.vue` — login form.
- Tests: `webapp/src/stores/auth.spec.ts`, `webapp/src/api/authClient.spec.ts`.

**Webapp — modify:**
- `webapp/src/api/client.ts` — inject Bearer header, `credentials:'include'`, 401→refresh→retry single-flight, add `login/refresh/logout/me/listUsers`.
- `webapp/src/App.vue` — gate on auth state; bootstrap before store loads.

---

## Task 1: Backend auth dependencies + config fields

**Files:**
- Modify: `backend/requirements.txt`
- Modify: `backend/app/config.py` (after the `# ── Server ──` block, ~line 168)
- Test: `backend/tests/test_auth_config.py` (create)

- [ ] **Step 1: Add the two libraries to requirements**

In `backend/requirements.txt`, add under a new section before the Postgres comment:

```
# Auth (Phase 1: hosted multi-user)
PyJWT==2.10.1
cryptography==44.0.0
```

- [ ] **Step 2: Install into the backend venv**

Run (from `backend/`): `./.venv/Scripts/python -m pip install PyJWT==2.10.1 cryptography==44.0.0`
Expected: both install successfully.

- [ ] **Step 3: Write the failing config test**

Create `backend/tests/test_auth_config.py`:

```python
"""Phase 1 — auth config fields exist with the documented defaults."""

from __future__ import annotations

from app.config import AppConfig


def test_auth_defaults() -> None:
    cfg = AppConfig(session_jwt_secret="x")
    assert cfg.session_jwt_secret == "x"
    assert cfg.session_access_ttl_seconds == 1800
    assert cfg.session_refresh_ttl_seconds == 30 * 24 * 3600
    assert cfg.onlysales_auth_base == "https://pyapi.onlysales.io"
    assert cfg.session_cookie_name == "triage_refresh"
    assert cfg.session_cookie_secure is True
    assert cfg.session_cookie_samesite == "lax"
    assert cfg.login_rate_max_attempts == 10
    assert cfg.login_rate_window_seconds == 300
    assert cfg.cors_allowed_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_session_secret_configured_property() -> None:
    assert AppConfig(session_jwt_secret="").session_secret_configured is False
    assert AppConfig(session_jwt_secret="abc").session_secret_configured is True
```

- [ ] **Step 4: Run it to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_config.py -v`
Expected: FAIL (`AttributeError` / unexpected-kwarg — fields not defined yet).

- [ ] **Step 5: Add the config fields**

In `backend/app/config.py`, add after the `log_level` field (the `# ── Server ──` block):

```python
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
```

And add this property next to the other derived helpers (near `openrouter_configured`):

```python
    @property
    def session_secret_configured(self) -> bool:
        return bool(self.session_jwt_secret.strip())
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add backend/requirements.txt backend/app/config.py backend/tests/test_auth_config.py
git commit -m "feat(backend): add auth/session config fields + PyJWT/cryptography deps"
```

---

## Task 2: Access-token mint + verify (security/tokens.py)

**Files:**
- Create: `backend/app/security/__init__.py`
- Create: `backend/app/security/tokens.py`
- Test: `backend/tests/test_security_tokens.py`

- [ ] **Step 1: Create the package marker**

Create `backend/app/security/__init__.py`:

```python
"""Security primitives: token mint/verify, password-free session crypto."""
```

- [ ] **Step 2: Write the failing access-token test**

Create `backend/tests/test_security_tokens.py`:

```python
"""Phase 1 — token primitives: access-JWT mint/verify."""

from __future__ import annotations

import time

import pytest

from app.security import tokens

SECRET = "unit-test-secret"


def test_mint_then_verify_roundtrips_claims() -> None:
    token = tokens.mint_access_token(
        SECRET,
        user_id=7,
        onlysales_id="abc123",
        email="op@example.com",
        scope="admin",
        ttl_seconds=1800,
    )
    claims = tokens.verify_access_token(SECRET, token)
    assert claims.user_id == 7
    assert claims.onlysales_id == "abc123"
    assert claims.email == "op@example.com"
    assert claims.scope == "admin"


def test_verify_rejects_wrong_secret() -> None:
    token = tokens.mint_access_token(
        SECRET, user_id=1, onlysales_id="a", email="e", scope=None, ttl_seconds=1800
    )
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token("other-secret", token)


def test_verify_rejects_expired() -> None:
    token = tokens.mint_access_token(
        SECRET, user_id=1, onlysales_id="a", email="e", scope=None, ttl_seconds=-1
    )
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token(SECRET, token)


def test_verify_rejects_garbage() -> None:
    with pytest.raises(tokens.TokenError):
        tokens.verify_access_token(SECRET, "not-a-jwt")
```

- [ ] **Step 3: Run it to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_security_tokens.py -v`
Expected: FAIL (`ModuleNotFoundError: app.security.tokens`).

- [ ] **Step 4: Implement the access-token half of tokens.py**

Create `backend/app/security/tokens.py`:

```python
"""Token primitives — pure, no DB.

Access tokens are stateless HS256 JWTs verified offline on every request.
Refresh tokens are opaque random strings stored only as a sha256 hash; the
upstream OnlySales refresh token is encrypted at rest with Fernet.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass

import jwt
from cryptography.fernet import Fernet, InvalidToken

from app.util import naive_utcnow

_ALGO = "HS256"


class TokenError(Exception):
    """Raised when an access token is missing, malformed, or expired."""


@dataclass(frozen=True)
class AccessClaims:
    user_id: int
    onlysales_id: str
    email: str
    scope: str | None


def mint_access_token(
    secret: str,
    *,
    user_id: int,
    onlysales_id: str,
    email: str,
    scope: str | None,
    ttl_seconds: int,
) -> str:
    """Encode a short-lived access JWT. `ttl_seconds` may be negative (tests)."""
    now = int(naive_utcnow().timestamp())
    payload = {
        "sub": str(user_id),
        "oid": onlysales_id,
        "email": email,
        "scope": scope,
        "type": "access",
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm=_ALGO)


def verify_access_token(secret: str, token: str) -> AccessClaims:
    """Decode + validate signature/exp/type. Raises TokenError on any failure."""
    try:
        payload = jwt.decode(token, secret, algorithms=[_ALGO])
    except jwt.PyJWTError as exc:  # signature, expiry, malformed — all subclasses
        raise TokenError(str(exc)) from exc
    if payload.get("type") != "access":
        raise TokenError("not an access token")
    try:
        return AccessClaims(
            user_id=int(payload["sub"]),
            onlysales_id=str(payload["oid"]),
            email=str(payload["email"]),
            scope=payload.get("scope"),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise TokenError(f"malformed claims: {exc}") from exc
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_security_tokens.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add backend/app/security/__init__.py backend/app/security/tokens.py backend/tests/test_security_tokens.py
git commit -m "feat(backend): access-token mint/verify (HS256, offline)"
```

---

## Task 3: Refresh-token gen/hash + upstream-refresh encryption

**Files:**
- Modify: `backend/app/security/tokens.py`
- Test: `backend/tests/test_security_tokens.py` (append)

- [ ] **Step 1: Append failing tests**

Add to `backend/tests/test_security_tokens.py`:

```python
def test_refresh_token_is_random_and_hash_is_stable() -> None:
    raw1 = tokens.generate_refresh_token()
    raw2 = tokens.generate_refresh_token()
    assert raw1 != raw2
    assert len(raw1) >= 32
    assert tokens.hash_refresh_token(raw1) == tokens.hash_refresh_token(raw1)
    assert tokens.hash_refresh_token(raw1) != tokens.hash_refresh_token(raw2)


def test_encrypt_decrypt_upstream_roundtrips() -> None:
    key = tokens.generate_encryption_key()
    blob = tokens.encrypt_secret(key, "onlysales-refresh-xyz")
    assert blob != "onlysales-refresh-xyz"
    assert tokens.decrypt_secret(key, blob) == "onlysales-refresh-xyz"


def test_encrypt_with_empty_key_returns_none() -> None:
    assert tokens.encrypt_secret("", "anything") is None
    assert tokens.decrypt_secret("", "anything") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_security_tokens.py -v`
Expected: FAIL (`AttributeError: generate_refresh_token`).

- [ ] **Step 3: Append the implementation to tokens.py**

Add to `backend/app/security/tokens.py`:

```python
def generate_refresh_token() -> str:
    """Opaque, URL-safe random refresh token (~48 bytes of entropy)."""
    return secrets.token_urlsafe(48)


def hash_refresh_token(raw: str) -> str:
    """Stable sha256 hex of a refresh token — only the hash is ever stored."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def generate_encryption_key() -> str:
    """A fresh Fernet key (urlsafe base64). Used to seed config in tests/setup."""
    return Fernet.generate_key().decode("ascii")


def encrypt_secret(key: str, plaintext: str) -> str | None:
    """Encrypt the upstream refresh token. Empty key → None (storage disabled)."""
    if not key:
        return None
    return Fernet(key.encode("ascii")).encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(key: str, blob: str | None) -> str | None:
    """Decrypt; returns None on empty key/blob or any tampering."""
    if not key or not blob:
        return None
    try:
        return Fernet(key.encode("ascii")).decrypt(blob.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError):
        return None
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_security_tokens.py -v`
Expected: PASS (7 tests total).

- [ ] **Step 5: Commit**

```bash
git add backend/app/security/tokens.py backend/tests/test_security_tokens.py
git commit -m "feat(backend): refresh-token gen/hash + Fernet upstream-refresh crypto"
```

---

## Task 4: Login rate limiter (security/ratelimit.py)

**Files:**
- Create: `backend/app/security/ratelimit.py`
- Test: `backend/tests/test_ratelimit.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_ratelimit.py`:

```python
"""Phase 1 — fixed-window login limiter."""

from __future__ import annotations

from app.security.ratelimit import FixedWindowLimiter


def test_allows_up_to_max_then_blocks() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowLimiter(max_attempts=3, window_seconds=60, now=lambda: clock["t"])
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False  # 4th in the window


def test_window_resets() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowLimiter(max_attempts=1, window_seconds=60, now=lambda: clock["t"])
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    clock["t"] += 61
    assert limiter.allow("k") is True


def test_keys_are_independent() -> None:
    clock = {"t": 1000.0}
    limiter = FixedWindowLimiter(max_attempts=1, window_seconds=60, now=lambda: clock["t"])
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_ratelimit.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the limiter**

Create `backend/app/security/ratelimit.py`:

```python
"""In-process fixed-window rate limiter for /auth/login.

Single-process only (matches the single-backend deploy). Not distributed — a
multi-replica deploy would move this to Redis, out of scope for Phase 1.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class FixedWindowLimiter:
    def __init__(
        self,
        *,
        max_attempts: int,
        window_seconds: int,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max = max_attempts
        self._window = window_seconds
        self._now = now
        self._buckets: dict[str, tuple[float, int]] = {}  # key -> (window_start, count)

    def allow(self, key: str) -> bool:
        """Record an attempt; return False once the window cap is exceeded."""
        now = self._now()
        start, count = self._buckets.get(key, (now, 0))
        if now - start >= self._window:
            start, count = now, 0
        count += 1
        self._buckets[key] = (start, count)
        return count <= self._max
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_ratelimit.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/security/ratelimit.py backend/tests/test_ratelimit.py
git commit -m "feat(backend): in-process fixed-window login rate limiter"
```

---

## Task 5: User + Session models + migration 0021

**Files:**
- Modify: `backend/app/models.py` (add two model classes near the other tables)
- Create: `backend/alembic/versions/0021_add_auth_tables.py`
- Test: `backend/tests/test_auth_models.py`

- [ ] **Step 1: Write the failing model test**

Create `backend/tests/test_auth_models.py`:

```python
"""Phase 1 — users + sessions tables exist and round-trip."""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.models import Session as SessionRow
from app.models import User
from app.util import naive_utcnow


@pytest.mark.asyncio
async def test_user_and_session_roundtrip(session) -> None:  # noqa: ANN001
    user = User(
        onlysales_id="oid-1",
        email="op@example.com",
        name="Op Erator",
        scope="admin",
    )
    session.add(user)
    await session.flush()

    sess = SessionRow(
        id="sess-1",
        user_id=user.id,
        refresh_token_hash="deadbeef",
        onlysales_refresh_encrypted=None,
        issued_at=naive_utcnow(),
        expires_at=naive_utcnow(),
    )
    session.add(sess)
    await session.commit()

    got = await session.scalar(select(User).where(User.onlysales_id == "oid-1"))
    assert got is not None
    assert got.email == "op@example.com"
    assert got.is_active is True

    got_sess = await session.get(SessionRow, "sess-1")
    assert got_sess is not None
    assert got_sess.user_id == user.id
    assert got_sess.revoked_at is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_models.py -v`
Expected: FAIL (`ImportError: cannot import name 'User'`).

- [ ] **Step 3: Add the models**

In `backend/app/models.py`, add (place after the `Settings` class; keep imports — `String` may need adding to the `from sqlalchemy import (...)` block):

```python
class User(Base):
    """Mirror of an OnlySales identity. NOT a credential store — no password."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    onlysales_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    name: Mapped[str | None] = mapped_column(Text)
    scope: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(
        default=True, server_default=text("1"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)


class Session(Base):
    """Refresh-token store + revocation ledger. PK is an opaque session id."""

    __tablename__ = "sessions"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    refresh_token_hash: Mapped[str] = mapped_column(Text, nullable=False)
    onlysales_refresh_encrypted: Mapped[str | None] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        Index("ix_sessions_refresh_hash", "refresh_token_hash"),
        Index("ix_sessions_user_id", "user_id"),
    )
```

> `Index`, `ForeignKey`, `Integer`, `Text`, `DateTime`, `text` are already imported in `models.py`. If `mypy` flags a missing import, add it to the existing `from sqlalchemy import (...)` tuple.

- [ ] **Step 4: Create the migration**

Create `backend/alembic/versions/0021_add_auth_tables.py`:

```python
"""Add users + sessions tables (Phase 1: hosted multi-user / T167).

Mirror of the OnlySales identity (`users`) + the refresh-token/revocation
ledger (`sessions`). Additive — no existing table is touched.

Revision ID: 0021
Revises: 0020
Create Date: 2026-06-05 00:00:21.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("onlysales_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("scope", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_onlysales_id", "users", ["onlysales_id"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "sessions",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("refresh_token_hash", sa.Text(), nullable=False),
        sa.Column("onlysales_refresh_encrypted", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("last_used_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_sessions_refresh_hash", "sessions", ["refresh_token_hash"])
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_index("ix_sessions_refresh_hash", table_name="sessions")
    op.drop_table("sessions")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_onlysales_id", table_name="users")
    op.drop_table("users")
```

- [ ] **Step 5: Run the model test to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_models.py -v`
Expected: PASS (`init_db` runs migration 0021, creating both tables).

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0021_add_auth_tables.py backend/tests/test_auth_models.py
git commit -m "feat(backend): users + sessions tables (migration 0021)"
```

---

## Task 6: Auth schemas

**Files:**
- Modify: `backend/app/schemas.py` (append near the end)
- Test: `backend/tests/test_auth_schemas.py`

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_auth_schemas.py`:

```python
"""Phase 1 — auth wire schemas."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas import LoginRequest, LoginResponse, UserOut


def test_login_request_lowercases_and_trims_email() -> None:
    req = LoginRequest(email="  OP@Example.COM ", password="pw")
    assert req.email == "op@example.com"


def test_login_request_requires_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="op@example.com", password="")


def test_login_response_shape() -> None:
    resp = LoginResponse(
        access_token="jwt",
        user=UserOut(id=1, onlysales_id="oid", email="op@example.com", name="Op", scope="admin"),
    )
    assert resp.access_token == "jwt"
    assert resp.user.email == "op@example.com"
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_schemas.py -v`
Expected: FAIL (`ImportError`).

- [ ] **Step 3: Append the schemas**

In `backend/app/schemas.py`, append (match the file's existing pydantic v2 style — `BaseModel`, `Field`, `field_validator`):

```python
from pydantic import field_validator  # if not already imported at the top


class LoginRequest(BaseModel):
    email: str
    password: str = Field(min_length=1)

    @field_validator("email")
    @classmethod
    def _normalize_email(cls, v: str) -> str:
        return v.strip().lower()


class UserOut(BaseModel):
    id: int
    onlysales_id: str
    email: str
    name: str | None
    scope: str | None


class LoginResponse(BaseModel):
    access_token: str
    user: UserOut


class MeResponse(BaseModel):
    user: UserOut
```

> If `BaseModel` / `Field` / `field_validator` are already imported at the top of `schemas.py`, don't duplicate the import — add only the missing names.

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_schemas.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/tests/test_auth_schemas.py
git commit -m "feat(backend): auth wire schemas (LoginRequest/Response, UserOut, MeResponse)"
```

---

## Task 7: OnlySales client (clients/onlysales.py)

**Files:**
- Create: `backend/app/clients/onlysales.py`
- Test: `backend/tests/test_onlysales_client.py`

- [ ] **Step 1: Write the failing test (mocks HTTP via pytest-httpx)**

Create `backend/tests/test_onlysales_client.py`:

```python
"""Phase 1 — OnlySales auth proxy client."""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

from app.clients.onlysales import OnlySalesAuthError, OnlySalesClient

BASE = "https://pyapi.onlysales.io"


@pytest.mark.asyncio
async def test_login_normalizes_user_id_and_returns_payload(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/auth/login",
        method="POST",
        json={
            "accessToken": "os-access",
            "refreshToken": "os-refresh",
            "user": {"id": "oid-9", "email": "Op@Example.com", "firstName": "Op", "lastName": "E", "scope": "admin"},
        },
    )
    client = OnlySalesClient(base=BASE)
    try:
        result = await client.login(email="op@example.com", password="pw")
    finally:
        await client.aclose()

    assert result.access_token == "os-access"
    assert result.refresh_token == "os-refresh"
    assert result.onlysales_id == "oid-9"
    assert result.email == "op@example.com"
    assert result.name == "Op E"
    assert result.scope == "admin"


@pytest.mark.asyncio
async def test_login_raises_on_bad_credentials(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/auth/login", method="POST", status_code=401, json={"message": "Invalid"}
    )
    client = OnlySalesClient(base=BASE)
    try:
        with pytest.raises(OnlySalesAuthError):
            await client.login(email="op@example.com", password="bad")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_login_raises_when_no_access_token(httpx_mock: HTTPXMock) -> None:
    httpx_mock.add_response(
        url=f"{BASE}/auth/login", method="POST", json={"name": "AccountNotVerified"}
    )
    client = OnlySalesClient(base=BASE)
    try:
        with pytest.raises(OnlySalesAuthError):
            await client.login(email="op@example.com", password="pw")
    finally:
        await client.aclose()
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_onlysales_client.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the client**

Create `backend/app/clients/onlysales.py`:

```python
"""OnlySales auth proxy — login + refresh against pyapi.onlysales.io.

Mirrors chrome-extension/api.js: normalizes `user.id → onlysales_id`, joins
firstName+lastName, surfaces a human error. We never store OnlySales passwords;
this is the only path that sees them, in-flight, to forward upstream.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx


class OnlySalesAuthError(Exception):
    """Raised on any login/refresh failure (bad creds, unverified, upstream down)."""


@dataclass(frozen=True)
class OnlySalesIdentity:
    access_token: str
    refresh_token: str | None
    onlysales_id: str
    email: str
    name: str | None
    scope: str | None


def _extract_error(body: object, fallback: str) -> str:
    if isinstance(body, dict):
        for key in ("message", "detail", "name"):
            val = body.get(key)
            if isinstance(val, str) and val:
                return val
    return fallback


def _parse_identity(data: dict[str, object]) -> OnlySalesIdentity:
    if data.get("name") == "AccountNotVerified":
        raise OnlySalesAuthError("Account not verified")
    access = data.get("accessToken")
    if not isinstance(access, str) or not access:
        raise OnlySalesAuthError(_extract_error(data, "Login failed"))
    user = data.get("user")
    if not isinstance(user, dict):
        raise OnlySalesAuthError("Unexpected auth response")
    oid = user.get("_id") or user.get("id")
    email = user.get("email")
    if not isinstance(oid, str) or not isinstance(email, str):
        raise OnlySalesAuthError("Auth response missing user id/email")
    first = user.get("firstName") or ""
    last = user.get("lastName") or ""
    name = f"{first} {last}".strip() or None
    scope = user.get("scope") if isinstance(user.get("scope"), str) else None
    refresh = data.get("refreshToken")
    return OnlySalesIdentity(
        access_token=access,
        refresh_token=refresh if isinstance(refresh, str) else None,
        onlysales_id=oid,
        email=email.strip().lower(),
        name=name,
        scope=scope,
    )


class OnlySalesClient:
    def __init__(
        self,
        *,
        base: str = "https://pyapi.onlysales.io",
        version: str = "0.1.0",
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(
            base_url=base,
            headers={"X-Version": version, "Content-Type": "application/json"},
            timeout=httpx.Timeout(20.0),
        )

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    async def login(self, *, email: str, password: str) -> OnlySalesIdentity:
        try:
            resp = await self._http.post(
                "/auth/login", json={"email": email.strip().lower(), "password": password}
            )
        except httpx.HTTPError as exc:
            raise OnlySalesAuthError(f"OnlySales unreachable: {exc}") from exc
        body = resp.json() if resp.content else {}
        if resp.status_code != 200:
            raise OnlySalesAuthError(_extract_error(body, f"Login failed ({resp.status_code})"))
        if not isinstance(body, dict):
            raise OnlySalesAuthError("Unexpected auth response")
        return _parse_identity(body)

    async def refresh(self, refresh_token: str) -> OnlySalesIdentity:
        try:
            resp = await self._http.post(
                "/auth/refresh-token", json={"refreshToken": refresh_token}
            )
        except httpx.HTTPError as exc:
            raise OnlySalesAuthError(f"OnlySales unreachable: {exc}") from exc
        body = resp.json() if resp.content else {}
        if resp.status_code != 200 or not isinstance(body, dict):
            raise OnlySalesAuthError(_extract_error(body, "Token refresh failed"))
        return _parse_identity(body)
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_onlysales_client.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/clients/onlysales.py backend/tests/test_onlysales_client.py
git commit -m "feat(backend): OnlySales auth proxy client (login/refresh)"
```

---

## Task 8: Auth service (services/auth.py)

**Files:**
- Create: `backend/app/services/auth.py`
- Test: `backend/tests/test_auth_service.py`

- [ ] **Step 1: Write the failing service test**

Create `backend/tests/test_auth_service.py`:

```python
"""Phase 1 — auth service: login → mirror + session; refresh rotates; logout revokes."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.clients.onlysales import OnlySalesIdentity
from app.models import Session as SessionRow
from app.models import User
from app.security import tokens
from app.services import auth as svc

SECRET = "svc-secret"


def _identity(refresh: str | None = "os-refresh") -> OnlySalesIdentity:
    return OnlySalesIdentity(
        access_token="os-access",
        refresh_token=refresh,
        onlysales_id="oid-1",
        email="op@example.com",
        name="Op E",
        scope="admin",
    )


@pytest.mark.asyncio
async def test_login_creates_user_and_session(session) -> None:  # noqa: ANN001
    out = await svc.complete_login(
        session,
        identity=_identity(),
        jwt_secret=SECRET,
        access_ttl=1800,
        refresh_ttl=3600,
        encryption_key="",
        new_session_id=str(uuid.uuid4()),
    )
    # access token verifies + carries the new user id
    claims = tokens.verify_access_token(SECRET, out.access_token)
    user = await session.scalar(select(User).where(User.onlysales_id == "oid-1"))
    assert user is not None
    assert claims.user_id == user.id
    assert user.last_login_at is not None
    # a session row exists, keyed by the hash of the raw cookie value
    sess = await session.scalar(
        select(SessionRow).where(SessionRow.refresh_token_hash == tokens.hash_refresh_token(out.refresh_cookie))
    )
    assert sess is not None
    assert sess.revoked_at is None


@pytest.mark.asyncio
async def test_login_is_idempotent_on_user(session) -> None:  # noqa: ANN001
    await svc.complete_login(session, identity=_identity(), jwt_secret=SECRET, access_ttl=1800, refresh_ttl=3600, encryption_key="", new_session_id="s1")
    await svc.complete_login(session, identity=_identity(), jwt_secret=SECRET, access_ttl=1800, refresh_ttl=3600, encryption_key="", new_session_id="s2")
    users = (await session.scalars(select(User).where(User.onlysales_id == "oid-1"))).all()
    assert len(users) == 1  # mirror upserted, not duplicated


@pytest.mark.asyncio
async def test_refresh_rotates_token_and_keeps_session(session) -> None:  # noqa: ANN001
    login = await svc.complete_login(session, identity=_identity(), jwt_secret=SECRET, access_ttl=1800, refresh_ttl=3600, encryption_key="", new_session_id="s1")
    rotated = await svc.rotate_session(
        session, raw_refresh=login.refresh_cookie, jwt_secret=SECRET, access_ttl=1800, refresh_ttl=3600
    )
    assert rotated.refresh_cookie != login.refresh_cookie
    # old cookie no longer resolves
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(session, raw_refresh=login.refresh_cookie, jwt_secret=SECRET, access_ttl=1800, refresh_ttl=3600)


@pytest.mark.asyncio
async def test_logout_revokes(session) -> None:  # noqa: ANN001
    login = await svc.complete_login(session, identity=_identity(), jwt_secret=SECRET, access_ttl=1800, refresh_ttl=3600, encryption_key="", new_session_id="s1")
    await svc.revoke_by_refresh(session, raw_refresh=login.refresh_cookie)
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(session, raw_refresh=login.refresh_cookie, jwt_secret=SECRET, access_ttl=1800, refresh_ttl=3600)
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_service.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement the service**

Create `backend/app/services/auth.py`:

```python
"""Auth orchestration — mirror the OnlySales identity, manage our sessions.

complete_login: upsert user mirror + create a session + mint an access token.
rotate_session: validate a refresh cookie, rotate it, re-mint access.
revoke_by_refresh / revoke_all_for_user: logout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.onlysales import OnlySalesIdentity
from app.models import Session as SessionRow
from app.models import User
from app.security import tokens
from app.util import naive_utcnow


class AuthSessionError(Exception):
    """Raised when a refresh cookie is unknown, expired, or revoked."""


@dataclass(frozen=True)
class IssuedSession:
    access_token: str
    refresh_cookie: str
    user: User


async def _upsert_user(session: AsyncSession, identity: OnlySalesIdentity) -> User:
    user = await session.scalar(select(User).where(User.onlysales_id == identity.onlysales_id))
    if user is None:
        user = User(onlysales_id=identity.onlysales_id, email=identity.email)
        session.add(user)
    user.email = identity.email
    user.name = identity.name
    user.scope = identity.scope
    user.last_login_at = naive_utcnow()
    await session.flush()
    return user


def _mint(user: User, secret: str, ttl: int) -> str:
    return tokens.mint_access_token(
        secret,
        user_id=user.id,
        onlysales_id=user.onlysales_id,
        email=user.email,
        scope=user.scope,
        ttl_seconds=ttl,
    )


async def complete_login(
    session: AsyncSession,
    *,
    identity: OnlySalesIdentity,
    jwt_secret: str,
    access_ttl: int,
    refresh_ttl: int,
    encryption_key: str,
    new_session_id: str,
) -> IssuedSession:
    user = await _upsert_user(session, identity)
    raw_refresh = tokens.generate_refresh_token()
    now = naive_utcnow()
    row = SessionRow(
        id=new_session_id,
        user_id=user.id,
        refresh_token_hash=tokens.hash_refresh_token(raw_refresh),
        onlysales_refresh_encrypted=tokens.encrypt_secret(encryption_key, identity.refresh_token)
        if identity.refresh_token
        else None,
        issued_at=now,
        expires_at=now + timedelta(seconds=refresh_ttl),
        last_used_at=now,
    )
    session.add(row)
    access = _mint(user, jwt_secret, access_ttl)
    await session.commit()
    return IssuedSession(access_token=access, refresh_cookie=raw_refresh, user=user)


async def _active_session(session: AsyncSession, raw_refresh: str) -> SessionRow:
    row = await session.scalar(
        select(SessionRow).where(
            SessionRow.refresh_token_hash == tokens.hash_refresh_token(raw_refresh)
        )
    )
    if row is None:
        raise AuthSessionError("unknown refresh token")
    if row.revoked_at is not None:
        raise AuthSessionError("session revoked")
    if row.expires_at <= naive_utcnow():
        raise AuthSessionError("session expired")
    return row


async def rotate_session(
    session: AsyncSession,
    *,
    raw_refresh: str,
    jwt_secret: str,
    access_ttl: int,
    refresh_ttl: int,
) -> IssuedSession:
    row = await _active_session(session, raw_refresh)
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthSessionError("user inactive")
    new_raw = tokens.generate_refresh_token()
    now = naive_utcnow()
    row.refresh_token_hash = tokens.hash_refresh_token(new_raw)
    row.last_used_at = now
    row.expires_at = now + timedelta(seconds=refresh_ttl)
    access = _mint(user, jwt_secret, access_ttl)
    await session.commit()
    return IssuedSession(access_token=access, refresh_cookie=new_raw, user=user)


async def revoke_by_refresh(session: AsyncSession, *, raw_refresh: str) -> None:
    row = await session.scalar(
        select(SessionRow).where(
            SessionRow.refresh_token_hash == tokens.hash_refresh_token(raw_refresh)
        )
    )
    if row is not None and row.revoked_at is None:
        row.revoked_at = naive_utcnow()
        await session.commit()


async def revoke_all_for_user(session: AsyncSession, *, user_id: int) -> None:
    await session.execute(
        update(SessionRow)
        .where(SessionRow.user_id == user_id, SessionRow.revoked_at.is_(None))
        .values(revoked_at=naive_utcnow())
    )
    await session.commit()
```

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_service.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/auth.py backend/tests/test_auth_service.py
git commit -m "feat(backend): auth service — login mirror+session, rotate, revoke"
```

---

## Task 9: get_current_user dependency + get_onlysales

**Files:**
- Modify: `backend/app/deps.py`
- Test: `backend/tests/test_current_user_dep.py`

- [ ] **Step 1: Write the failing dependency test**

Create `backend/tests/test_current_user_dep.py`:

```python
"""Phase 1 — get_current_user verifies the Bearer access token offline."""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from app.config import AppConfig
from app.deps import CurrentUser, get_current_user
from app.security import tokens

SECRET = "dep-secret"


def _request_with(app: FastAPI, authorization: str | None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {"type": "http", "headers": headers, "app": app}
    return Request(scope)


def _app() -> FastAPI:
    app = FastAPI()
    app.state.config = AppConfig(session_jwt_secret=SECRET)
    return app


def test_returns_current_user_for_valid_token() -> None:
    app = _app()
    token = tokens.mint_access_token(
        SECRET, user_id=5, onlysales_id="oid", email="op@example.com", scope="admin", ttl_seconds=1800
    )
    user = get_current_user(_request_with(app, f"Bearer {token}"))
    assert isinstance(user, CurrentUser)
    assert user.id == 5
    assert user.email == "op@example.com"
    assert user.scope == "admin"


def test_401_when_header_missing() -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with(_app(), None))
    assert exc.value.status_code == 401


def test_401_when_token_invalid() -> None:
    with pytest.raises(HTTPException) as exc:
        get_current_user(_request_with(_app(), "Bearer garbage"))
    assert exc.value.status_code == 401
```

- [ ] **Step 2: Run to verify it fails**

Run: `./.venv/Scripts/python -m pytest tests/test_current_user_dep.py -v`
Expected: FAIL (`ImportError: cannot import name 'CurrentUser'`).

- [ ] **Step 3: Add to deps.py**

Append to `backend/app/deps.py`:

```python
from dataclasses import dataclass

from fastapi import HTTPException, status

from app.clients.onlysales import OnlySalesClient
from app.security import tokens


@dataclass(frozen=True)
class CurrentUser:
    id: int
    onlysales_id: str
    email: str
    scope: str | None


def get_onlysales(request: Request) -> OnlySalesClient:
    client: OnlySalesClient | None = getattr(request.app.state, "onlysales", None)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="auth backend not configured"
        )
    return client


def get_current_user(request: Request) -> CurrentUser:
    """Verify the Bearer access token offline. 401 on any failure. No DB hit."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = header[7:].strip()
    secret: str = request.app.state.config.session_jwt_secret
    try:
        claims = tokens.verify_access_token(secret, token)
    except tokens.TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    return CurrentUser(
        id=claims.user_id,
        onlysales_id=claims.onlysales_id,
        email=claims.email,
        scope=claims.scope,
    )
```

> Keep the existing imports at the top of `deps.py`; add `OnlySalesClient` to its imports if your linter prefers top-of-file imports over the inline block above.

- [ ] **Step 4: Run to verify it passes**

Run: `./.venv/Scripts/python -m pytest tests/test_current_user_dep.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/deps.py backend/tests/test_current_user_dep.py
git commit -m "feat(backend): get_current_user (offline JWT verify) + get_onlysales dep"
```

---

## Task 10: Auth router (routers/auth.py)

**Files:**
- Create: `backend/app/routers/auth.py`
- Test: deferred to Task 11 (needs the wired app + conftest auth fixtures)

- [ ] **Step 1: Implement the router**

Create `backend/app/routers/auth.py`:

```python
"""Auth + users endpoints. Public: /auth/login, /auth/refresh. Spec §6."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.onlysales import OnlySalesAuthError, OnlySalesClient
from app.deps import CurrentUser, get_app_config, get_current_user, get_onlysales
from app.config import AppConfig
from app.db import get_session
from app.models import User
from app.schemas import LoginRequest, LoginResponse, MeResponse, UserOut
from app.security.ratelimit import FixedWindowLimiter
from app.services import auth as svc

router = APIRouter(prefix="/auth", tags=["auth"])

# Module-level limiter — created once; bounds set from config at request time is
# unnecessary because config is process-wide. Reset is not exposed (per-process).
_login_limiter: FixedWindowLimiter | None = None


def _limiter(config: AppConfig) -> FixedWindowLimiter:
    global _login_limiter
    if _login_limiter is None:
        _login_limiter = FixedWindowLimiter(
            max_attempts=config.login_rate_max_attempts,
            window_seconds=config.login_rate_window_seconds,
        )
    return _login_limiter


def _set_refresh_cookie(response: Response, config: AppConfig, value: str) -> None:
    response.set_cookie(
        key=config.session_cookie_name,
        value=value,
        max_age=config.session_refresh_ttl_seconds,
        httponly=True,
        secure=config.session_cookie_secure,
        samesite=config.session_cookie_samesite,  # type: ignore[arg-type]
        path="/",
    )


def _check_origin(request: Request, config: AppConfig) -> None:
    """CSRF defense for cookie-authenticated endpoints: Origin must be allowed."""
    origin = request.headers.get("origin")
    if origin is not None and origin not in config.cors_allowed_origins:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="bad origin")


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id, onlysales_id=user.onlysales_id, email=user.email, name=user.name, scope=user.scope
    )


@router.post("/login", response_model=LoginResponse)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    onlysales: OnlySalesClient = Depends(get_onlysales),
    config: AppConfig = Depends(get_app_config),
) -> LoginResponse:
    client_ip = request.client.host if request.client else "unknown"
    if not _limiter(config).allow(f"{client_ip}:{body.email}"):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts")
    try:
        identity = await onlysales.login(email=body.email, password=body.password)
    except OnlySalesAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    issued = await svc.complete_login(
        session,
        identity=identity,
        jwt_secret=config.session_jwt_secret,
        access_ttl=config.session_access_ttl_seconds,
        refresh_ttl=config.session_refresh_ttl_seconds,
        encryption_key=config.session_refresh_encryption_key,
        new_session_id=str(uuid.uuid4()),
    )
    _set_refresh_cookie(response, config, issued.refresh_cookie)
    return LoginResponse(access_token=issued.access_token, user=_user_out(issued.user))


@router.post("/refresh", response_model=LoginResponse)
async def refresh(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
) -> LoginResponse:
    _check_origin(request, config)
    cookie = request.cookies.get(config.session_cookie_name)
    if not cookie:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="no session")
    try:
        issued = await svc.rotate_session(
            session,
            raw_refresh=cookie,
            jwt_secret=config.session_jwt_secret,
            access_ttl=config.session_access_ttl_seconds,
            refresh_ttl=config.session_refresh_ttl_seconds,
        )
    except svc.AuthSessionError as exc:
        response.delete_cookie(config.session_cookie_name, path="/")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    _set_refresh_cookie(response, config, issued.refresh_cookie)
    return LoginResponse(access_token=issued.access_token, user=_user_out(issued.user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
) -> Response:
    _check_origin(request, config)
    cookie = request.cookies.get(config.session_cookie_name)
    if cookie:
        await svc.revoke_by_refresh(session, raw_refresh=cookie)
    response.delete_cookie(config.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    session: AsyncSession = Depends(get_session),
    config: AppConfig = Depends(get_app_config),
    user: CurrentUser = Depends(get_current_user),
) -> Response:
    await svc.revoke_all_for_user(session, user_id=user.id)
    response.delete_cookie(config.session_cookie_name, path="/")
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=MeResponse)
async def me(
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> MeResponse:
    row = await session.get(User, user.id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")
    return MeResponse(user=_user_out(row))
```

- [ ] **Step 2: Add the `/users` list endpoint to the same router**

Append to `backend/app/routers/auth.py`:

```python
@router.get("/../users", include_in_schema=False)
async def _users_alias() -> None:  # pragma: no cover - placeholder, replaced below
    raise NotImplementedError
```

> Remove the placeholder above — `/users` lives on its own router prefix. Instead, at the END of the file add a second router:

```python
users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("", response_model=list[UserOut])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(get_current_user),
) -> list[UserOut]:
    rows = (await session.scalars(select(User).where(User.is_active.is_(True)))).all()
    return [_user_out(r) for r in rows]
```

> Delete the `_users_alias` placeholder block — it exists only to make the intent explicit while editing; the real endpoint is `users_router`.

- [ ] **Step 3: Commit (router compiles; wired + tested in Task 11)**

```bash
git add backend/app/routers/auth.py
git commit -m "feat(backend): /auth router (login/refresh/logout/me) + /users"
```

---

## Task 11: Wire auth into the app + protect every router

**Files:**
- Modify: `backend/app/main.py` (lifespan client wiring + `create_app` includes/CORS + boot guard)
- Modify: `backend/tests/conftest.py` (auth fixtures)
- Test: `backend/tests/test_auth_api.py`, `backend/tests/test_auth_required.py`

- [ ] **Step 1: Wire the OnlySales client into lifespan**

In `backend/app/main.py` lifespan, after the `intercom` client block and before `app.state.* =` assignments, add:

```python
    from app.clients.onlysales import OnlySalesClient

    onlysales = OnlySalesClient(base=config.onlysales_auth_base)
```

And add to the `app.state` assignments:

```python
    app.state.onlysales = onlysales
```

And in the `finally:` cleanup block (where other clients are closed, near `await engine.dispose()`), add:

```python
        await onlysales.aclose()
```

- [ ] **Step 2: Add the boot guard for the JWT secret**

In `backend/app/main.py` lifespan, immediately after `config = get_config()`, add:

```python
    if not config.session_secret_configured:
        raise RuntimeError(
            "SESSION_JWT_SECRET is required — refusing to boot without it. "
            "Set it in backend/.env."
        )
```

- [ ] **Step 3: Update CORS + include the auth/users routers + protect the rest**

In `backend/app/main.py` `create_app`, replace the CORS middleware block with:

```python
    config = get_config()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

Then change the router includes so health + auth stay public and everything else requires a session. Replace the `app.include_router(...)` block with:

```python
    from app.deps import get_current_user
    from app.routers import auth as auth_router

    protected = [Depends(get_current_user)]

    app.include_router(health_router.router)  # public
    app.include_router(auth_router.router)  # public (login/refresh); /me + logout-all self-guard
    app.include_router(auth_router.users_router, dependencies=protected)
    app.include_router(categories_router.router, dependencies=protected)
    app.include_router(proposals_router.router, dependencies=protected)
    app.include_router(tickets_router.router, dependencies=protected)
    app.include_router(settings_router.router, dependencies=protected)
    app.include_router(followups_router.router, dependencies=protected)
    app.include_router(notes_router.router, dependencies=protected)
    app.include_router(note_entries_router.router, dependencies=protected)
    app.include_router(playbooks_router.router, dependencies=protected)
    app.include_router(snippets_router.router, dependencies=protected)
    app.include_router(attachments_router.router, dependencies=protected)
    app.include_router(clusters_router.router, dependencies=protected)
    app.include_router(metrics_router.router, dependencies=protected)
    app.include_router(stats_router.router, dependencies=protected)
```

> `Depends` is already imported by FastAPI usage elsewhere; if not present in `main.py`, add `from fastapi import Depends`.

- [ ] **Step 4: Update conftest — authenticate the existing suite + add fixtures**

In `backend/tests/conftest.py`:

(a) Add `session_jwt_secret` to `test_config`:

```python
        session_jwt_secret="test-session-secret",
```

(b) In the `app` fixture, after `application.dependency_overrides[get_config] = lambda: test_config`, add a default-authenticated user override and wire a fake OnlySales client. First add imports at the top:

```python
from app.deps import CurrentUser, get_current_user
```

Then in the `app` fixture body:

```python
    application.state.onlysales = None  # tests that exercise login set their own
    application.dependency_overrides[get_current_user] = lambda: CurrentUser(
        id=1, onlysales_id="seed-oid", email="op@test", scope="admin"
    )
```

(c) Add an `unauth_client` fixture (no auth override) after the `client` fixture:

```python
@pytest_asyncio.fixture
async def unauth_client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Client with NO get_current_user override — for testing the 401 gate."""
    app.dependency_overrides.pop(get_current_user, None)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

- [ ] **Step 5: Write the 401-gate test**

Create `backend/tests/test_auth_required.py`:

```python
"""Phase 1 — protected routes 401 without a token; health/login stay public."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_is_public(unauth_client: AsyncClient) -> None:
    assert (await unauth_client.get("/health")).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/tickets", "/categories", "/settings", "/users"])
async def test_protected_routes_401_without_token(unauth_client: AsyncClient, path: str) -> None:
    assert (await unauth_client.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_authenticated_client_reaches_settings(client: AsyncClient) -> None:
    # `client` carries the default get_current_user override → authenticated.
    assert (await client.get("/settings")).status_code == 200
```

- [ ] **Step 6: Write the login/refresh API test (fake OnlySales via app.state)**

Create `backend/tests/test_auth_api.py`:

```python
"""Phase 1 — /auth/login + /auth/refresh + /auth/logout end-to-end."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.clients.onlysales import OnlySalesIdentity
from app.deps import get_current_user


class FakeOnlySales:
    async def login(self, *, email: str, password: str) -> OnlySalesIdentity:
        if password != "good":
            from app.clients.onlysales import OnlySalesAuthError

            raise OnlySalesAuthError("Invalid credentials")
        return OnlySalesIdentity(
            access_token="os-access",
            refresh_token="os-refresh",
            onlysales_id="oid-1",
            email=email,
            name="Op E",
            scope="admin",
        )

    async def aclose(self) -> None:  # pragma: no cover
        pass


@pytest.fixture
def login_app(app: FastAPI) -> FastAPI:
    """The wired app but with login enabled: drop the auth override, fake OnlySales."""
    app.dependency_overrides.pop(get_current_user, None)
    app.state.onlysales = FakeOnlySales()
    # the router resolves the client via get_onlysales(request) → app.state.onlysales
    from app.deps import get_onlysales

    app.dependency_overrides[get_onlysales] = lambda: app.state.onlysales
    return app


@pytest.mark.asyncio
async def test_login_sets_cookie_and_returns_access_token(login_app: FastAPI) -> None:
    transport = ASGITransport(app=login_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/auth/login", json={"email": "op@example.com", "password": "good"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["access_token"]
        assert body["user"]["email"] == "op@example.com"
        assert "triage_refresh" in resp.cookies

        # access token reaches a protected route
        token = body["access_token"]
        me = await ac.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert me.status_code == 200
        assert me.json()["user"]["onlysales_id"] == "oid-1"


@pytest.mark.asyncio
async def test_login_rejects_bad_password(login_app: FastAPI) -> None:
    transport = ASGITransport(app=login_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        resp = await ac.post("/auth/login", json={"email": "op@example.com", "password": "bad"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_rotates_and_logout_revokes(login_app: FastAPI) -> None:
    transport = ASGITransport(app=login_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        login = await ac.post("/auth/login", json={"email": "op@example.com", "password": "good"})
        assert login.status_code == 200

        refreshed = await ac.post("/auth/refresh")
        assert refreshed.status_code == 200
        assert refreshed.json()["access_token"]

        out = await ac.post("/auth/logout")
        assert out.status_code == 204

        again = await ac.post("/auth/refresh")
        assert again.status_code == 401
```

- [ ] **Step 7: Run the auth + gate tests**

Run: `./.venv/Scripts/python -m pytest tests/test_auth_api.py tests/test_auth_required.py -v`
Expected: PASS (all). If `/auth/refresh` cookie isn't sent back, confirm `AsyncClient` persists cookies (it does by default across calls on the same instance).

- [ ] **Step 8: Run the FULL backend suite to catch retrofit regressions**

Run: `./.venv/Scripts/python -m pytest -q`
Expected: PASS. The single conftest `get_current_user` override keeps the ~400 existing tests authenticated. Investigate any 401s — they indicate a test hitting a now-protected route without the override (should not happen with the `client` fixture).

- [ ] **Step 9: Commit**

```bash
git add backend/app/main.py backend/tests/conftest.py backend/tests/test_auth_api.py backend/tests/test_auth_required.py
git commit -m "feat(backend): require auth on all routers; wire OnlySales client + boot guard"
```

---

## Task 12: Backend quality gate

- [ ] **Step 1: Run the full backend gate**

Run (from `backend/`):
`./.venv/Scripts/python -m ruff check app tests && ./.venv/Scripts/python -m ruff format --check app tests && ./.venv/Scripts/python -m mypy app && ./.venv/Scripts/python -m pytest -q`
Expected: all green. Fix ruff/mypy findings (common: unused imports in `main.py`, the inline imports in `deps.py`/`main.py` — hoist if the linter objects).

- [ ] **Step 2: Commit any gate fixups**

```bash
git add -A backend
git commit -m "chore(backend): satisfy ruff/mypy for auth core"
```

---

## Task 13: Webapp auth types

**Files:**
- Create: `webapp/src/types/auth.ts`

- [ ] **Step 1: Create the types**

Create `webapp/src/types/auth.ts`:

```typescript
// Auth wire contracts. Mirror of backend app/schemas.py auth models.

export interface User {
  id: number;
  onlysales_id: string;
  email: string;
  name: string | null;
  scope: string | null;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  user: User;
}

export interface MeResponse {
  user: User;
}
```

- [ ] **Step 2: Commit**

```bash
git add webapp/src/types/auth.ts
git commit -m "feat(webapp): auth wire types"
```

---

## Task 14: Webapp api client — Bearer + refresh interceptor + auth endpoints

**Files:**
- Modify: `webapp/src/api/client.ts`
- Test: `webapp/src/api/authClient.spec.ts`

- [ ] **Step 1: Write the failing interceptor test**

Create `webapp/src/api/authClient.spec.ts`:

```typescript
// Auth-aware request layer: Bearer injection + 401→refresh→retry.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, setAccessToken, onAuthLost } from './client';

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal('fetch', fetchMock);
  fetchMock.mockReset();
  setAccessToken(null);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function jsonResponse(status: number, body: unknown): Response {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

describe('auth request layer', () => {
  it('attaches the Bearer header when a token is set', async () => {
    setAccessToken('tok-1');
    fetchMock.mockResolvedValueOnce(jsonResponse(200, []));
    await api.listCategories();
    const [, init] = fetchMock.mock.calls[0];
    expect((init.headers as Record<string, string>)['authorization']).toBe('Bearer tok-1');
    expect(init.credentials).toBe('include');
  });

  it('on 401 refreshes once then retries with the new token', async () => {
    setAccessToken('stale');
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'expired' })) // first call
      .mockResolvedValueOnce(jsonResponse(200, { access_token: 'fresh', user: { id: 1, onlysales_id: 'o', email: 'e', name: null, scope: null } })) // /auth/refresh
      .mockResolvedValueOnce(jsonResponse(200, [])); // retry
    const result = await api.listCategories();
    expect(result).toEqual([]);
    const retryInit = fetchMock.mock.calls[2][1];
    expect((retryInit.headers as Record<string, string>)['authorization']).toBe('Bearer fresh');
  });

  it('calls onAuthLost when refresh itself fails', async () => {
    setAccessToken('stale');
    const lost = vi.fn();
    onAuthLost(lost);
    fetchMock
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'expired' }))
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'no session' })); // refresh fails
    await expect(api.listCategories()).rejects.toThrow();
    expect(lost).toHaveBeenCalledOnce();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run (from `webapp/`): `npx vitest run src/api/authClient.spec.ts`
Expected: FAIL (`setAccessToken` is not exported).

- [ ] **Step 3: Modify client.ts**

In `webapp/src/api/client.ts`, replace the `request<T>` helper and add the auth machinery. Add near the top (after `const BASE = '/api';`):

```typescript
// ── auth state (in-memory only; never localStorage) ─────────────────────────
let accessToken: string | null = null;
let authLostHandler: (() => void) | null = null;
let refreshInFlight: Promise<boolean> | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function onAuthLost(handler: () => void): void {
  authLostHandler = handler;
}

/** Single-flight refresh. Resolves true if a new access token was obtained. */
async function refreshAccessToken(): Promise<boolean> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const resp = await fetch(BASE + '/auth/refresh', {
        method: 'POST',
        credentials: 'include',
        headers: { 'content-type': 'application/json' },
      });
      if (!resp.ok) return false;
      const body = (await resp.json()) as { access_token: string };
      accessToken = body.access_token;
      return true;
    } catch {
      return false;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}
```

Then replace the `request<T>` function with an auth-aware version:

```typescript
async function rawFetch(path: string, init: RequestInit): Promise<Response> {
  const headers: Record<string, string> = {
    'content-type': 'application/json',
    ...((init.headers as Record<string, string>) ?? {}),
  };
  if (accessToken) headers['authorization'] = `Bearer ${accessToken}`;
  return fetch(BASE + path, { ...init, headers, credentials: 'include' });
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let resp = await rawFetch(path, init);

  // Don't try to refresh the refresh/login calls themselves.
  const isAuthCall = path.startsWith('/auth/');
  if (resp.status === 401 && !isAuthCall) {
    const refreshed = await refreshAccessToken();
    if (refreshed) {
      resp = await rawFetch(path, init);
    } else {
      authLostHandler?.();
    }
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, body, `${init.method ?? 'GET'} ${path} → ${resp.status}`);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}
```

Then add the auth endpoints to the `api` object (anywhere inside the `export const api = { ... }` literal):

```typescript
  // ── auth ────────────────────────────────────────────────────────────────
  login: (body: import('@/types/auth').LoginRequest): Promise<import('@/types/auth').LoginResponse> =>
    request('/auth/login', { method: 'POST', body: JSON.stringify(body) }),
  refreshSession: (): Promise<import('@/types/auth').LoginResponse> =>
    request('/auth/refresh', { method: 'POST' }),
  logout: (): Promise<void> => request('/auth/logout', { method: 'POST' }),
  me: (): Promise<import('@/types/auth').MeResponse> => request('/auth/me'),
  listUsers: (): Promise<import('@/types/auth').User[]> => request('/users'),
```

> The `import('@/types/auth')` inline type imports avoid touching the existing top-of-file import block; if the project prefers named imports, add `User, LoginRequest, LoginResponse, MeResponse` to a new `import type` line instead.

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/api/authClient.spec.ts`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add webapp/src/api/client.ts webapp/src/api/authClient.spec.ts
git commit -m "feat(webapp): Bearer injection + 401→refresh→retry + auth endpoints"
```

---

## Task 15: Webapp auth store

**Files:**
- Create: `webapp/src/stores/auth.ts`
- Test: `webapp/src/stores/auth.spec.ts`

- [ ] **Step 1: Write the failing store test**

Create `webapp/src/stores/auth.spec.ts`:

```typescript
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from './auth';
import { api, setAccessToken } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: { login: vi.fn(), refreshSession: vi.fn(), logout: vi.fn() },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

const mocked = vi.mocked(api);

const USER = { id: 1, onlysales_id: 'o', email: 'op@example.com', name: 'Op', scope: 'admin' };

describe('authStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('login stores the token + user and flips authenticated', async () => {
    mocked.login.mockResolvedValue({ access_token: 'tok', user: USER });
    const s = useAuthStore();
    await s.login('op@example.com', 'pw');
    expect(s.isAuthenticated).toBe(true);
    expect(s.user?.email).toBe('op@example.com');
    expect(vi.mocked(setAccessToken)).toHaveBeenCalledWith('tok');
  });

  it('bootstrap returns true when a session refreshes', async () => {
    mocked.refreshSession.mockResolvedValue({ access_token: 'tok', user: USER });
    const s = useAuthStore();
    const ok = await s.bootstrap();
    expect(ok).toBe(true);
    expect(s.isAuthenticated).toBe(true);
  });

  it('bootstrap returns false when no session exists', async () => {
    mocked.refreshSession.mockRejectedValue(new Error('401'));
    const s = useAuthStore();
    const ok = await s.bootstrap();
    expect(ok).toBe(false);
    expect(s.isAuthenticated).toBe(false);
  });

  it('logout clears state', async () => {
    mocked.login.mockResolvedValue({ access_token: 'tok', user: USER });
    mocked.logout.mockResolvedValue(undefined);
    const s = useAuthStore();
    await s.login('op@example.com', 'pw');
    await s.logout();
    expect(s.isAuthenticated).toBe(false);
    expect(s.user).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run src/stores/auth.spec.ts`
Expected: FAIL (`Failed to resolve import './auth'`).

- [ ] **Step 3: Implement the store**

Create `webapp/src/stores/auth.ts`:

```typescript
// Auth store — in-memory access token + current user. The refresh token lives
// only in an httpOnly cookie the browser manages; nothing sensitive is stored
// in localStorage. On load, bootstrap() silently refreshes any live session.

import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { api, setAccessToken, onAuthLost } from '@/api/client';
import type { User } from '@/types/auth';

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null);
  const loading = ref(false);
  const error = ref<string | null>(null);

  const isAuthenticated = computed(() => user.value !== null);

  async function login(email: string, password: string): Promise<void> {
    loading.value = true;
    error.value = null;
    try {
      const resp = await api.login({ email, password });
      setAccessToken(resp.access_token);
      user.value = resp.user;
    } catch (e) {
      error.value = e instanceof Error ? e.message : 'Login failed';
      throw e;
    } finally {
      loading.value = false;
    }
  }

  /** Silent session restore on app load. True if a session was refreshed. */
  async function bootstrap(): Promise<boolean> {
    try {
      const resp = await api.refreshSession();
      setAccessToken(resp.access_token);
      user.value = resp.user;
      return true;
    } catch {
      setAccessToken(null);
      user.value = null;
      return false;
    }
  }

  async function logout(): Promise<void> {
    try {
      await api.logout();
    } finally {
      setAccessToken(null);
      user.value = null;
    }
  }

  /** Called by the api layer when a refresh fails mid-session. */
  function handleAuthLost(): void {
    setAccessToken(null);
    user.value = null;
  }
  onAuthLost(handleAuthLost);

  return { user, loading, error, isAuthenticated, login, bootstrap, logout };
});
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run src/stores/auth.spec.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add webapp/src/stores/auth.ts webapp/src/stores/auth.spec.ts
git commit -m "feat(webapp): auth store (login/bootstrap/logout, in-memory token)"
```

---

## Task 16: Login view component

**Files:**
- Create: `webapp/src/components/LoginView.vue`

- [ ] **Step 1: Implement the component**

Create `webapp/src/components/LoginView.vue` (uses design tokens per `webapp/DESIGN.md` — `var(--*)`, no hardcoded hex):

```vue
<script setup lang="ts">
import { ref } from 'vue';
import { useAuthStore } from '@/stores/auth';

const auth = useAuthStore();
const email = ref('');
const password = ref('');

async function onSubmit() {
  try {
    await auth.login(email.value, password.value);
  } catch {
    // auth.error is set by the store; the template renders it.
  }
}
</script>

<template>
  <div class="login">
    <form class="card" @submit.prevent="onSubmit">
      <h1 class="title mono">Intercom Triage</h1>
      <p class="subtitle">Sign in with your OnlySales account.</p>

      <label class="field">
        <span>Email</span>
        <input v-model="email" type="email" autocomplete="username" required />
      </label>

      <label class="field">
        <span>Password</span>
        <input v-model="password" type="password" autocomplete="current-password" required />
      </label>

      <p v-if="auth.error" class="error mono">{{ auth.error }}</p>

      <button type="submit" :disabled="auth.loading">
        {{ auth.loading ? 'Signing in…' : 'Sign in' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.login {
  display: grid;
  place-items: center;
  min-height: 100vh;
  background: var(--bg);
}
.card {
  display: flex;
  flex-direction: column;
  gap: var(--space-3, 12px);
  width: 320px;
  padding: var(--space-5, 24px);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius, 8px);
}
.title {
  margin: 0;
  font-size: var(--font-lg, 18px);
  color: var(--text);
}
.subtitle {
  margin: 0;
  color: var(--text-muted);
  font-size: var(--font-sm, 13px);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: var(--font-sm, 13px);
  color: var(--text-muted);
}
.field input {
  padding: 8px 10px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm, 6px);
  color: var(--text);
}
.error {
  margin: 0;
  color: var(--danger, #c0392b);
  font-size: var(--font-sm, 13px);
}
button {
  padding: 10px;
  background: var(--accent);
  color: var(--accent-contrast, #fff);
  border: none;
  border-radius: var(--radius-sm, 6px);
  cursor: pointer;
}
button:disabled {
  opacity: 0.6;
  cursor: default;
}
</style>
```

> Token names follow `webapp/src/styles/tokens.css`. If a referenced token doesn't exist, the `var(--x, fallback)` fallback keeps it functional; reconcile names against `tokens.css` during review.

- [ ] **Step 2: Commit**

```bash
git add webapp/src/components/LoginView.vue
git commit -m "feat(webapp): LoginView component"
```

---

## Task 17: App.vue auth gate + bootstrap

**Files:**
- Modify: `webapp/src/App.vue`
- Test: `webapp/src/stores/authGate.spec.ts` (a store-level gate test — App.vue itself is integration-verified manually)

- [ ] **Step 1: Add the gate to App.vue script**

In `webapp/src/App.vue` `<script setup>`, add the import + store + a ready flag:

```typescript
import LoginView from '@/components/LoginView.vue';
import { useAuthStore } from '@/stores/auth';
import { ref } from 'vue';

const auth = useAuthStore();
const authReady = ref(false);
```

- [ ] **Step 2: Gate the existing onMounted load behind auth**

Replace the existing `onMounted(async () => { ... })` body in `App.vue` with:

```typescript
onMounted(async () => {
  // Restore any live session before loading data. If none, show the login.
  await auth.bootstrap();
  authReady.value = true;
  if (!auth.isAuthenticated) return;
  await loadAll();
});

async function loadAll() {
  await settings.load();
  await categories.load();
  await Promise.all([followups.load(), notes.load(), noteEntries.load()]);
  await tickets.refresh().catch(() => undefined);
}

// Load data the moment the user authenticates (e.g. just logged in).
watch(
  () => auth.isAuthenticated,
  (now, before) => {
    if (now && !before) void loadAll();
  },
);
```

> `watch` is already imported in `App.vue` (it imports `onBeforeUnmount, onMounted, watch`). Keep that import.

- [ ] **Step 3: Gate the template**

In `webapp/src/App.vue` `<template>`, wrap the existing app shell. Replace the outer `<div class="app">` open so the login renders before auth:

```vue
<template>
  <div v-if="!authReady" class="status mono">Loading…</div>
  <LoginView v-else-if="!auth.isAuthenticated" />
  <div v-else class="app">
    <Topbar />
    <!-- …existing board/views/drawers/flyout/banners unchanged… -->
  </div>
</template>
```

> Keep everything currently inside `<div class="app">` exactly as-is; only the surrounding `v-if`/`v-else-if`/`v-else` branches are new.

- [ ] **Step 4: Write a gate behavior test (store-level)**

Create `webapp/src/stores/authGate.spec.ts`:

```typescript
// Verifies the gate predicate the App template relies on.

import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAuthStore } from './auth';
import { api } from '@/api/client';

vi.mock('@/api/client', () => ({
  api: { refreshSession: vi.fn(), login: vi.fn(), logout: vi.fn() },
  setAccessToken: vi.fn(),
  onAuthLost: vi.fn(),
}));

describe('auth gate predicate', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.clearAllMocks();
  });

  it('is unauthenticated before bootstrap and after a failed bootstrap', async () => {
    vi.mocked(api).refreshSession.mockRejectedValue(new Error('401'));
    const s = useAuthStore();
    expect(s.isAuthenticated).toBe(false);
    await s.bootstrap();
    expect(s.isAuthenticated).toBe(false);
  });
});
```

- [ ] **Step 5: Run the test**

Run: `npx vitest run src/stores/authGate.spec.ts`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/App.vue webapp/src/stores/authGate.spec.ts
git commit -m "feat(webapp): gate the app behind auth + bootstrap on load"
```

---

## Task 18: Env example, dev cookie note, and full gates

**Files:**
- Modify: `backend/.env.example` (create if absent)
- Modify: `webapp/README.md` or `backend/README.md` (dev note)

- [ ] **Step 1: Document the new env vars**

Add to `backend/.env.example` (create if it doesn't exist):

```
# ── Auth / sessions (Phase 1: hosted multi-user) ──────────────────────────
# REQUIRED — backend refuses to boot without it. Generate a long random string.
SESSION_JWT_SECRET=
# Optional — Fernet key (urlsafe base64, 32 bytes) to encrypt the stored
# OnlySales refresh token. Generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
SESSION_REFRESH_ENCRYPTION_KEY=
# OnlySales auth backend (login/refresh proxy target).
ONLYSALES_AUTH_BASE=https://pyapi.onlysales.io
# For plain-http LOCAL dev the refresh cookie must not be Secure-only:
SESSION_COOKIE_SECURE=false
# Comma-separated allowed origins for CORS + CSRF Origin check.
# (pydantic-settings parses a JSON list or comma string per its env conventions.)
```

> **Verify at impl start (spec §12 item 3):** confirm the real OnlySales auth base — the extension code uses `pyapi.onlysales.io`; the request said `api.onlysales.io`. Update `ONLYSALES_AUTH_BASE` accordingly and confirm OnlySales permits server-side login from the deploy host.

- [ ] **Step 2: Run the full backend gate**

Run (from `backend/`):
`./.venv/Scripts/python -m ruff check app tests && ./.venv/Scripts/python -m ruff format --check app tests && ./.venv/Scripts/python -m mypy app && ./.venv/Scripts/python -m pytest -q`
Expected: all green.

- [ ] **Step 3: Run the full webapp gate**

Run (from `webapp/`):
`npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`
Expected: all green. (If `format:check` flags CRLF, the repo's `.gitattributes eol=lf` + prettier `endOfLine:auto` should already handle it — re-run after `npm run format`.)

- [ ] **Step 4: Manual smoke (local, plain http)**

1. In `backend/.env`: set `SESSION_JWT_SECRET=devsecret`, `SESSION_COOKIE_SECURE=false`, a valid `INTERCOM_ACCESS_TOKEN`/`OPENROUTER_API_KEY` (or accept degraded), and a reachable `ONLYSALES_AUTH_BASE`.
2. Start backend + webapp: `./scripts/dev.ps1`.
3. Open `http://127.0.0.1:5173` → expect the **LoginView**, not the board.
4. Sign in with valid OnlySales creds → board loads; reload the page → still signed in (cookie refresh).
5. DevTools → Application → Cookies: `triage_refresh` is **httpOnly**; no token in localStorage.
6. Network: API calls carry `Authorization: Bearer …`; let the access token expire (or delete it in memory by editing) → a `401` triggers one `/auth/refresh` then a retry.

- [ ] **Step 5: Commit**

```bash
git add backend/.env.example backend/README.md webapp/README.md
git commit -m "docs: document auth env vars + local dev cookie note"
```

---

## Self-Review (completed during planning)

**Spec coverage (Phase 1 scope only):**
- §4 proxy-login + own-session + offline verify → Tasks 2, 7, 8, 9, 10, 11. ✓
- §5.1 users + sessions tables → Task 5. ✓
- §6 `/auth/login|refresh|logout|logout-all|me` + `/users` + auth on all routers → Tasks 10, 11. ✓
- §7 login view + auth store + Bearer/refresh interceptor + app gate → Tasks 13–17. ✓
- §8 CORS+credentials, httpOnly cookie, CSRF Origin check, login rate-limit, secrets, hard-fail on missing JWT secret → Tasks 1, 4, 11. ✓
- §11 test-harness retrofit (one conftest override) → Task 11 Step 4. ✓
- Out of Phase 1 (own plans): attribution, assignment/My-Queue, per-user follow-ups/notes, Postgres/embeddings hosting hardening. Noted, not built here. ✓

**Placeholder scan:** the only intentional "remove this" is the `_users_alias` block in Task 10 Step 2, explicitly instructed to be deleted in favor of `users_router`. No TBD/TODO. ✓

**Type consistency:** `IssuedSession.refresh_cookie` / `.access_token` used consistently across service + router + tests; `CurrentUser(id, onlysales_id, email, scope)` identical in deps, conftest, router, tests; webapp `setAccessToken`/`onAuthLost`/`refreshSession` names match between `client.ts`, `auth.ts`, and specs. ✓

---

## Notes carried to later-phase plans

- **Reuse-detection on refresh** is minimal here (a rotated token simply stops resolving). Full theft-chain revocation is a hardening item for the Phase 5 plan.
- **Attribution FKs** (`resolved_by`, `acted_by`, `assigned_to`) and the **`/users` picker** consumption land in Phases 2–3; `/users` already exists after Phase 1.
- **Postgres + embeddings** (`sqlite-vec` SQLite-only) is the Phase 5 hosting decision (spec §8.1) — Phase 1 runs on SQLite and is Postgres-agnostic in its new DDL (plain types, no dialect SQL).

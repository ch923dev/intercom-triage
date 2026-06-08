# MHU PR #10 — Security Hardening + Attribution + Assignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the remaining multi-user work onto the open PR #10 (`feat/mhu-auth`): fix the two foundation security gaps found in review, then add ticket attribution (who resolved / who recategorized) and assignment + a "My Queue" board filter — all over the one shared ticket pool.

**Architecture:** Additive only. Three forward-only migrations (`0022` reuse-detection, `0023` attribution, `0024` assignment) extend existing tables. Attribution/assignment columns are **board-state only** — they live on `TicketSchema`/`Override`, never on `HydratedTicket` (cross-package invariant #2 stays intact). The single shared stamp point `resolution.apply_resolve` carries the actor through both the single-id and bulk paths. The webapp gains nested `{id,name}` actor refs on the `Ticket` type, a `myTickets` getter, an assignee picker, and a "My Queue" toggle (no vue-router — the existing tickets-store filter pattern).

**Tech Stack:** FastAPI + async SQLAlchemy 2.0 + Alembic + SQLite/Postgres (backend); Vue 3 + Pinia + Vite + vitest (webapp); PyJWT + cryptography.Fernet (auth). All work happens in the worktree `.claude/worktrees/mhu-auth` on branch `feat/mhu-auth`.

**Conventions to honor (from backend/CLAUDE.md):** `from __future__ import annotations` at every module top; `naive_utcnow()` for all DB datetimes (never `datetime.utcnow()`); services own commits, routers don't; routers stay thin (parse → service → schema); module docstrings cite the spec; en-dash section banners `# ── Title ──…`; ruff line-length 100, double quotes, mypy strict. Run the backend gate via `backend/.venv` python (not global). Browser-test the webapp at `http://127.0.0.1:5173`.

**Quality gates (run before the PR is updated):**
- Backend: `ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
- Webapp: `cd webapp && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`

> ## ⚠️ Working environment (READ FIRST — overrides every command below)
> - **All work happens in the worktree** `F:\Claude Projects\niche\intercom-ticket-management\.claude\worktrees\mhu-auth` on branch `feat/mhu-auth`. Use absolute paths under it; run every `git`/`pytest`/`npm` command with that as the working directory.
> - **The worktree has NO backend venv.** Run all backend Python tooling via the **main repo venv** by absolute path. Wherever a step says `.\.venv\Scripts\Activate.ps1 && <cmd>`, instead run from `<worktree>\backend`:
>   - tests: `& "F:\Claude Projects\niche\intercom-ticket-management\backend\.venv\Scripts\python.exe" -m pytest -q <args>`
>   - ruff: `& "F:\Claude Projects\niche\intercom-ticket-management\backend\.venv\Scripts\ruff.exe" check app tests`
>   - format check: `& "...\backend\.venv\Scripts\ruff.exe" format --check app tests`
>   - mypy: `& "...\backend\.venv\Scripts\python.exe" -m mypy app`
>   - schema smoke: `& "...\backend\.venv\Scripts\python.exe" -m app.models`
>   (cwd = `<worktree>\backend` so `import app` resolves to the worktree's source.) The webapp uses the worktree's own `node_modules` (present) — `npm` commands run as written from `<worktree>\webapp`.
> - **Git hygiene:** plain `git add <specific files>` + `git commit` only. **NEVER** `git add -A` / `git add .` / `git add -u` — there is an uncommitted local edit to `backend/.env.example` (real dev secrets) in the worktree that must NOT be committed and must NOT be touched. Never `git rebase`/`amend`/`reset` (policy-denied). Stage only the exact files each task lists.

---

## File Structure

**New files:**
- `backend/alembic/versions/0022_add_session_prev_hash.py` — reuse-detection column
- `backend/alembic/versions/0023_add_ticket_attribution.py` — `tickets.resolved_by`, `overrides.acted_by`
- `backend/alembic/versions/0024_add_ticket_assignment.py` — `tickets.assigned_to`, `tickets.assigned_at`
- `backend/tests/test_auth_reuse_detection.py`
- `backend/tests/test_attribution.py`
- `backend/tests/test_assignment.py`
- `webapp/src/components/ticket/AssigneePicker.vue` — the assignee dropdown
- `webapp/src/stores/assignment.spec.ts` (or extend `tickets.spec.ts`)

**Modified files (with responsibility):**
- `backend/app/security/tokens.py` — unchanged (already correct); referenced only
- `backend/app/security/ratelimit.py` — add bucket eviction
- `backend/app/services/auth.py` — reuse-detection in `rotate_session`
- `backend/app/routers/auth.py` — two-limiter login; trim `GET /users` payload
- `backend/app/models.py` — add columns to `Session`, `Ticket`, `Override`
- `backend/app/schemas.py` — `UserRef`, `UserListItem`, `BulkAssign`, extend `TicketSchema`
- `backend/app/services/resolution.py` — thread `resolved_by` through `apply_resolve`/`resolve`
- `backend/app/services/bulk.py` — thread actor through `bulk_resolve`/`bulk_recategorize`; add `bulk_assign`
- `backend/app/services/tickets.py` — stamp `acted_by` in `set_override`; user-join in `get_tickets`; new `assign`
- `backend/app/routers/tickets.py` — pass `CurrentUser` into resolve/category/bulk; add assign endpoints
- `backend/tests/conftest.py` — seed a `User(id=1)` row so FK stamps resolve
- `webapp/src/types/api.ts` — add `UserRef`, attribution + assignment fields on `Ticket`
- `webapp/src/api/client.ts` — `assignTicket`, `bulkAssign`, `listUsers`
- `webapp/src/stores/tickets.ts` — `myTickets` getter, `myQueueOnly` toggle, `assign`/`bulkAssign` actions
- `webapp/src/components/ticket/TicketResolution.vue` — "resolved by X" + assignee picker mount
- `webapp/src/components/TicketCard.vue` — assignee tag
- `webapp/src/components/Topbar.vue` — "My Queue" toggle chip

**Contract/docs (one task at the end):** `docs/contract/spec.md`, `plan.md`, `tasks.md`, root `CLAUDE.md`.

---

# PART 1 — Security hardening (fix before stacking features)

## Task 1: Rate limiter — bucket eviction + helper for two-keyed limiting

**Files:**
- Modify: `backend/app/security/ratelimit.py`
- Test: `backend/tests/test_ratelimit.py` (extend; file already exists)

- [ ] **Step 1: Write the failing test** — add to `backend/tests/test_ratelimit.py`:

```python
def test_evicts_fully_elapsed_windows() -> None:
    clock = {"t": 0.0}
    limiter = FixedWindowLimiter(max_attempts=2, window_seconds=10, now=lambda: clock["t"])
    assert limiter.allow("a") is True
    assert limiter.allow("b") is True
    # advance past the window — both buckets are now stale
    clock["t"] = 11.0
    limiter.allow("c")  # triggers eviction
    assert "a" not in limiter._buckets
    assert "b" not in limiter._buckets
    assert "c" in limiter._buckets
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd backend && .\.venv\Scripts\Activate.ps1 && pytest -q tests/test_ratelimit.py::test_evicts_fully_elapsed_windows`
Expected: FAIL — `"a"` still present (no eviction yet).

- [ ] **Step 3: Implement eviction** — replace the body of `FixedWindowLimiter` in `backend/app/security/ratelimit.py`:

```python
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

    def _evict(self, now: float) -> None:
        """Drop buckets whose window has fully elapsed — bounds memory so a
        spray of distinct keys can't grow the dict without limit."""
        stale = [k for k, (start, _) in self._buckets.items() if now - start >= self._window]
        for k in stale:
            del self._buckets[k]

    def allow(self, key: str) -> bool:
        """Record an attempt; return False once the window cap is exceeded."""
        now = self._now()
        self._evict(now)
        start, count = self._buckets.get(key, (now, 0))
        if now - start >= self._window:
            start, count = now, 0
        count += 1
        self._buckets[key] = (start, count)
        return count <= self._max
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_ratelimit.py`
Expected: PASS (all, including the new test).

- [ ] **Step 5: Commit**

```bash
git add backend/app/security/ratelimit.py backend/tests/test_ratelimit.py
git commit -m "fix(auth): evict elapsed rate-limit buckets (bounds memory)"
```

## Task 2: Login — separate per-IP and per-email limiters

**Files:**
- Modify: `backend/app/routers/auth.py` (the `_limiter` helper + `login` handler)
- Test: `backend/tests/test_auth_api.py` (extend; review existing login-limit test and update it to the two-limiter behavior)

- [ ] **Step 1: Write the failing test** — add to `backend/tests/test_auth_api.py` (mock OnlySales via the same pattern existing auth tests use; if the existing file mocks `app.state.onlysales`, reuse that fixture):

```python
async def test_login_rate_limited_per_email_across_ips(client, monkeypatch) -> None:
    # 10 failed attempts for one email exhausts the email window regardless of IP.
    # (max_attempts default = 10.)
    import app.routers.auth as auth_router

    auth_router._ip_limiter = None
    auth_router._email_limiter = None

    async def fake_login(*, email: str, password: str):
        raise auth_router.OnlySalesAuthError("bad creds")

    # wire a fake onlysales client onto the app
    client._transport.app.state.onlysales.login = fake_login  # type: ignore[attr-defined]

    last = None
    for i in range(11):
        last = await client.post(
            "/auth/login",
            json={"email": "victim@x.com", "password": "p"},
            headers={"x-forwarded-for": f"10.0.0.{i}"},
        )
    assert last.status_code == 429
```

> NOTE: if `client.host` is always `testclient` under ASGITransport, the per-IP test is weak; this test asserts the **email** window trips even when the IP varies — the property the fix adds. Adjust the wiring line to however `test_auth_api.py` already injects a fake `onlysales` (read the file first; reuse its helper instead of the `_transport` hack if one exists).

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest -q tests/test_auth_api.py::test_login_rate_limited_per_email_across_ips`
Expected: FAIL — current per-`{ip}:{email}` key gives each IP its own bucket, so the email never trips.

- [ ] **Step 3: Implement two limiters** — in `backend/app/routers/auth.py` replace the limiter module-global + helper:

```python
_ip_limiter: FixedWindowLimiter | None = None
_email_limiter: FixedWindowLimiter | None = None


def _limiters(config: AppConfig) -> tuple[FixedWindowLimiter, FixedWindowLimiter]:
    global _ip_limiter, _email_limiter
    if _ip_limiter is None or _email_limiter is None:
        _ip_limiter = FixedWindowLimiter(
            max_attempts=config.login_rate_max_attempts,
            window_seconds=config.login_rate_window_seconds,
        )
        _email_limiter = FixedWindowLimiter(
            max_attempts=config.login_rate_max_attempts,
            window_seconds=config.login_rate_window_seconds,
        )
    return _ip_limiter, _email_limiter
```

Then in the `login` handler replace the rate-limit block:

```python
    client_ip = request.client.host if request.client else "unknown"
    ip_limiter, email_limiter = _limiters(config)
    # Call BOTH (no short-circuit) so each window counts this attempt.
    ip_ok = ip_limiter.allow(client_ip)
    email_ok = email_limiter.allow(body.email)
    if not (ip_ok and email_ok):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too many attempts"
        )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_auth_api.py`
Expected: PASS. Fix any existing login-limit test that assumed the combined key.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/auth.py backend/tests/test_auth_api.py
git commit -m "fix(auth): rate-limit login per-IP AND per-email (spec §8)"
```

## Task 3: Session model — add `prev_refresh_token_hash` + migration 0022

**Files:**
- Modify: `backend/app/models.py` (the `Session` class — add column after `refresh_token_hash`)
- Create: `backend/alembic/versions/0022_add_session_prev_hash.py`
- Test: `backend/tests/test_auth_models.py` (extend — roundtrip the new column)

- [ ] **Step 1: Write the failing test** — add to `backend/tests/test_auth_models.py`:

```python
async def test_session_stores_prev_refresh_hash(session) -> None:
    from app.models import Session as SessionRow
    from app.models import User
    from app.util import naive_utcnow

    user = User(onlysales_id="oid-x", email="x@x")
    session.add(user)
    await session.flush()
    row = SessionRow(
        id="sess-1",
        user_id=user.id,
        refresh_token_hash="h2",
        prev_refresh_token_hash="h1",
        issued_at=naive_utcnow(),
        expires_at=naive_utcnow(),
        last_used_at=naive_utcnow(),
    )
    session.add(row)
    await session.flush()
    got = await session.get(SessionRow, "sess-1")
    assert got is not None and got.prev_refresh_token_hash == "h1"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest -q tests/test_auth_models.py::test_session_stores_prev_refresh_hash`
Expected: FAIL — `TypeError`/`AttributeError` (`prev_refresh_token_hash` not a column).

- [ ] **Step 3: Add the model column** — in `backend/app/models.py`, in `class Session`, immediately after the `refresh_token_hash` mapped column add:

```python
    prev_refresh_token_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
```

And add to that class's `__table_args__` index tuple (create one if absent, matching the existing `ix_sessions_refresh_hash` style):

```python
        Index("ix_sessions_prev_refresh_hash", "prev_refresh_token_hash"),
```

- [ ] **Step 4: Create the migration** — `backend/alembic/versions/0022_add_session_prev_hash.py`:

```python
"""Add sessions.prev_refresh_token_hash — refresh reuse-detection (T168).

Stores the immediately-preceding refresh hash so a replayed (rotated-away)
token is detected and the session chain revoked. Additive.

Revision ID: 0022
Revises: 0021
Create Date: 2026-06-05 00:00:22.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("sessions", sa.Column("prev_refresh_token_hash", sa.Text(), nullable=True))
    op.create_index("ix_sessions_prev_refresh_hash", "sessions", ["prev_refresh_token_hash"])


def downgrade() -> None:
    op.drop_index("ix_sessions_prev_refresh_hash", table_name="sessions")
    op.drop_column("sessions", "prev_refresh_token_hash")
```

- [ ] **Step 5: Verify migration + model agree**

Run: `pytest -q tests/test_auth_models.py` then `python -m app.models`
Expected: PASS; schema smoke prints seeded categories with no error.

- [ ] **Step 6: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0022_add_session_prev_hash.py backend/tests/test_auth_models.py
git commit -m "feat(auth): sessions.prev_refresh_token_hash + migration 0022"
```

## Task 4: Refresh reuse-detection in `rotate_session`

**Files:**
- Modify: `backend/app/services/auth.py` (replace `_active_session` use inside `rotate_session`)
- Create: `backend/tests/test_auth_reuse_detection.py`

- [ ] **Step 1: Write the failing test** — `backend/tests/test_auth_reuse_detection.py`:

```python
"""Refresh reuse-detection: a replayed rotated token revokes the chain."""

from __future__ import annotations

import pytest

from app.models import Session as SessionRow
from app.models import User
from app.services import auth as svc


@pytest.fixture
async def seeded(session):
    user = User(onlysales_id="oid-1", email="op@x", scope="agent")
    session.add(user)
    await session.flush()
    from app.clients.onlysales import OnlySalesIdentity

    issued = await svc.complete_login(
        session,
        identity=OnlySalesIdentity(
            onlysales_id="oid-1", email="op@x", name="Op", scope="agent", refresh_token=None
        ),
        jwt_secret="s" * 32,
        access_ttl=1800,
        refresh_ttl=2_592_000,
        encryption_key="",
        new_session_id="sess-1",
    )
    return user, issued


async def test_reuse_of_rotated_token_revokes_chain(session, seeded) -> None:
    _user, issued = seeded
    r1 = issued.refresh_cookie
    # legit rotation r1 -> r2
    rotated = await svc.rotate_session(
        session, raw_refresh=r1, jwt_secret="s" * 32, access_ttl=1800, refresh_ttl=2_592_000
    )
    r2 = rotated.refresh_cookie
    # attacker replays r1 -> must be detected and revoke the session
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(
            session, raw_refresh=r1, jwt_secret="s" * 32, access_ttl=1800, refresh_ttl=2_592_000
        )
    row = await session.get(SessionRow, "sess-1")
    assert row is not None and row.revoked_at is not None
    # the legit r2 is now dead too (chain revoked)
    with pytest.raises(svc.AuthSessionError):
        await svc.rotate_session(
            session, raw_refresh=r2, jwt_secret="s" * 32, access_ttl=1800, refresh_ttl=2_592_000
        )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest -q tests/test_auth_reuse_detection.py`
Expected: FAIL — replaying `r1` raises "unknown refresh token" but does NOT set `revoked_at`, and `r2` still works.

- [ ] **Step 3: Implement reuse-detection** — in `backend/app/services/auth.py`, replace `_active_session` and `rotate_session` with:

```python
async def _lookup_session(
    session: AsyncSession, raw_refresh: str
) -> tuple[SessionRow | None, bool]:
    """Find the session by current hash, else by the previous (rotated-away)
    hash. Returns (row, reused) — `reused=True` means a superseded token was
    replayed (theft signal)."""
    h = tokens.hash_refresh_token(raw_refresh)
    row = await session.scalar(select(SessionRow).where(SessionRow.refresh_token_hash == h))
    if row is not None:
        return row, False
    prior = await session.scalar(
        select(SessionRow).where(SessionRow.prev_refresh_token_hash == h)
    )
    return prior, prior is not None


async def rotate_session(
    session: AsyncSession,
    *,
    raw_refresh: str,
    jwt_secret: str,
    access_ttl: int,
    refresh_ttl: int,
) -> IssuedSession:
    row, reused = await _lookup_session(session, raw_refresh)
    if row is None:
        raise AuthSessionError("unknown refresh token")
    if reused:
        # A rotated-away token was replayed → assume theft, revoke the chain.
        if row.revoked_at is None:
            row.revoked_at = naive_utcnow()
            await session.commit()
        raise AuthSessionError("refresh token reuse detected")
    if row.revoked_at is not None:
        raise AuthSessionError("session revoked")
    if row.expires_at <= naive_utcnow():
        raise AuthSessionError("session expired")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise AuthSessionError("user inactive")
    new_raw = tokens.generate_refresh_token()
    now = naive_utcnow()
    row.prev_refresh_token_hash = row.refresh_token_hash
    row.refresh_token_hash = tokens.hash_refresh_token(new_raw)
    row.last_used_at = now
    row.expires_at = now + timedelta(seconds=refresh_ttl)
    access = _mint(user, jwt_secret, access_ttl)
    await session.commit()
    return IssuedSession(access_token=access, refresh_cookie=new_raw, user=user)
```

> Keep `complete_login`, `revoke_by_refresh`, `revoke_all_for_user` unchanged. Remove the now-unused `_active_session` (mypy/ruff will flag it).

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_auth_reuse_detection.py tests/test_auth_service.py`
Expected: PASS (and existing auth-service tests still green).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/auth.py backend/tests/test_auth_reuse_detection.py
git commit -m "feat(auth): refresh reuse-detection revokes the session chain (spec §4/§8)"
```

---

# PART 2 — Attribution (Phase 2)

## Task 5: Seed a User row in the test harness (FK target)

**Files:**
- Modify: `backend/tests/conftest.py` (the `app` fixture — after `init_db`)

The `app` fixture already overrides `get_current_user` → `CurrentUser(id=1, ...)`, but `init_db` seeds no `users` row. Attribution/assignment FKs (`resolved_by=1`) need a real row.

- [ ] **Step 1: Add the seed** — in `backend/tests/conftest.py`, in the `app` fixture, after `await init_db(engine, session_factory)` add:

```python
    # The get_current_user override returns id=1; seed the matching mirror user
    # so attribution / assignment FKs (resolved_by, assigned_to) resolve.
    async with session_factory() as s:
        s.add(
            User(
                id=1,
                onlysales_id="seed-oid",
                email="op@test",
                name="Seed Operator",
                scope="admin",
            )
        )
        await s.commit()
```

Add `from app.models import User` to the conftest imports if not present.

- [ ] **Step 2: Run the suite to confirm nothing broke**

Run: `pytest -q`
Expected: PASS (same as before — the row is just additive).

- [ ] **Step 3: Commit**

```bash
git add backend/tests/conftest.py
git commit -m "test(auth): seed mirror User(id=1) so attribution FKs resolve"
```

## Task 6: Migration 0023 + model columns (`tickets.resolved_by`, `overrides.acted_by`)

**Files:**
- Modify: `backend/app/models.py` (`Ticket` + `Override`)
- Create: `backend/alembic/versions/0023_add_ticket_attribution.py`

- [ ] **Step 1: Add model columns** — in `class Ticket` (after `non_actionable_kind`):

```python
    # Phase 2 (T169) — attribution. Board-state only; AI/system resolve → NULL.
    resolved_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
```

In `class Override` (after `category_id`):

```python
    acted_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
```

- [ ] **Step 2: Create the migration** — `backend/alembic/versions/0023_add_ticket_attribution.py`:

```python
"""Add attribution columns: tickets.resolved_by, overrides.acted_by (T169).

Both FK users.id, nullable, ON DELETE SET NULL — AI/system actions stay NULL.
Additive. Reference: docs/superpowers/specs/2026-06-05-multi-hosted-user-design.md §5.2.

Revision ID: 0023
Revises: 0022
Create Date: 2026-06-05 00:00:23.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column(
            "resolved_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "overrides",
        sa.Column(
            "acted_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("overrides", "acted_by")
    op.drop_column("tickets", "resolved_by")
```

> Note: SQLite cannot drop an FK column in-place without a table rebuild; `downgrade` is best-effort and the repo is forward-only — leave as written (matches existing migrations' downgrade style).

- [ ] **Step 3: Verify schema smoke**

Run: `python -m app.models` then `pytest -q tests/test_auth_models.py`
Expected: PASS / clean.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0023_add_ticket_attribution.py
git commit -m "feat(attribution): tickets.resolved_by + overrides.acted_by + migration 0023"
```

## Task 7: Schemas — `UserRef` + attribution fields on `TicketSchema`

**Files:**
- Modify: `backend/app/schemas.py`
- Test: covered by Task 9 (API roundtrip)

- [ ] **Step 1: Add `UserRef`** — in `backend/app/schemas.py`, near the auth schemas (after `UserOut`):

```python
class UserRef(BaseModel):
    """Lightweight actor reference embedded on the board ticket — id + name only.
    Board-state only; never on HydratedTicket (invariant #2)."""

    id: int
    name: str | None
```

- [ ] **Step 2: Extend `TicketSchema`** — add after the `parked_note` field:

```python
    # Phase 2/3 (T169/T170) — attribution + assignment. Board-state only.
    resolved_by: UserRef | None = None
    acted_by: UserRef | None = None
    assigned_to: UserRef | None = None
    assigned_at: UTCDatetime | None = None
```

- [ ] **Step 3: Verify it imports**

Run: `python -c "from app.schemas import TicketSchema, UserRef"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas.py
git commit -m "feat(attribution): UserRef + attribution/assignment fields on TicketSchema"
```

## Task 8: Thread `resolved_by` through resolve (single + bulk) and `acted_by` through override

**Files:**
- Modify: `backend/app/services/resolution.py` (`apply_resolve`, `resolve`)
- Modify: `backend/app/services/bulk.py` (`bulk_resolve`, `bulk_recategorize`)
- Modify: `backend/app/services/tickets.py` (`set_override`)
- Modify: `backend/app/routers/tickets.py` (inject `CurrentUser`)
- Test: `backend/tests/test_attribution.py`

- [ ] **Step 1: Write the failing test** — `backend/tests/test_attribution.py`:

```python
"""Attribution capture: resolve stamps resolved_by; override stamps acted_by."""

from __future__ import annotations

from app.models import Override, Ticket
from app.util import naive_utcnow


async def _seed_ticket(session, tid: str = "t1") -> None:
    session.add(
        Ticket(
            id=tid,
            title="x",
            state="open",
            author={},
            parts=[],
            created_at=naive_utcnow(),
            updated_at=naive_utcnow(),
        )
    )
    await session.commit()


async def test_manual_resolve_stamps_resolved_by(client, session) -> None:
    await _seed_ticket(session)
    resp = await client.post("/tickets/t1/resolve")
    assert resp.status_code == 200
    row = await session.get(Ticket, "t1")
    assert row is not None and row.resolved_by == 1  # seeded CurrentUser id


async def test_override_stamps_acted_by(client, session) -> None:
    await _seed_ticket(session)
    # category 1 is a seeded default category
    resp = await client.patch("/tickets/t1/category", json={"category_id": 1})
    assert resp.status_code == 200
    ov = await session.get(Override, "t1")
    assert ov is not None and ov.acted_by == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest -q tests/test_attribution.py`
Expected: FAIL — `resolved_by`/`acted_by` are `None` (services don't stamp yet).

- [ ] **Step 3a: `resolution.py`** — change `apply_resolve` + `resolve` to accept the actor:

```python
def apply_resolve(row: Ticket, *, resolved_by: int | None) -> ResolveOutcome:
    """Mutate a Ticket row to mark it manually resolved. Does NOT commit.
    `resolved_by` is the acting operator's user id (None for system paths)."""
    if row.resolved_at is not None:
        raise HTTPException(status_code=409, detail="ticket is already resolved")
    now = naive_utcnow()
    row.resolved_at = now
    row.resolved_source = "manual"
    row.resolved_by = resolved_by
    row.non_actionable_kind = None
    clear_parked(row)
    return ResolveOutcome(resolved_at=now, resolved_source="manual")
```

```python
async def resolve(session: AsyncSession, ticket_id: str, *, resolved_by: int | None) -> ResolveOutcome:
    """Mark a ticket as manually resolved. 409 if already resolved."""
    row = await get_or_404(session, ticket_id)
    outcome = apply_resolve(row, resolved_by=resolved_by)
    await session.commit()
    metrics.incr("tickets_resolved_total.manual")
    return outcome
```

> In `clear_resolution`, also clear the actor on reopen so a re-resolve re-attributes:
> add `row.resolved_by = None` alongside the existing clears.

- [ ] **Step 3b: `bulk.py`** — thread the actor into `bulk_resolve` and `bulk_recategorize`:

```python
async def bulk_resolve(
    session: AsyncSession, ticket_ids: list[str], *, resolved_by: int | None
) -> BulkResult:
    async def per_id(tid: str) -> None:
        row = await resolution_svc.get_or_404(session, tid)
        resolution_svc.apply_resolve(row, resolved_by=resolved_by)
        metrics.incr("tickets_resolved_total.manual")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("resolve", result)
    return result
```

In `bulk_recategorize`'s `per_id`, when creating/updating the override set `acted_by`:

```python
        if override is None:
            session.add(Override(ticket_id=tid, category_id=category_id, set_at=now, acted_by=acted_by))
        else:
            override.category_id = category_id
            override.set_at = now
            override.acted_by = acted_by
```

and change the signature to `async def bulk_recategorize(session, ticket_ids, category_id, *, acted_by: int | None)`.

- [ ] **Step 3c: `tickets.py` `set_override`** — accept + stamp `acted_by`:

```python
async def set_override(
    session: AsyncSession, ticket_id: str, category_id: int, *, acted_by: int | None
) -> int:
    ...
    if override is None:
        session.add(
            Override(ticket_id=ticket_id, category_id=category_id, set_at=naive_utcnow(), acted_by=acted_by),
        )
    else:
        override.category_id = category_id
        override.set_at = naive_utcnow()
        override.acted_by = acted_by
    ...
```

- [ ] **Step 3d: `routers/tickets.py`** — import the dep and inject it; pass through. Add to imports:

```python
from app.deps import CurrentUser, get_app_config, get_current_user, get_intercom, get_openrouter
```

Update the four handlers (resolve, bulk_resolve, override_category, bulk_recategorize):

```python
@router.post("/{ticket_id}/resolve", response_model=ResolveResponse)
async def resolve_ticket(
    ticket_id: str,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> ResolveResponse:
    out = await resolution_svc.resolve(session, ticket_id, resolved_by=user.id)
    return ResolveResponse(resolved_at=out.resolved_at, resolved_source=out.resolved_source)


@router.post("/bulk/resolve", response_model=BulkResult)
async def bulk_resolve(
    body: BulkTicketIds,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> BulkResult:
    return await bulk_svc.bulk_resolve(session, body.ticket_ids, resolved_by=user.id)


@router.patch("/{ticket_id}/category", response_model=OverrideResponse)
async def override_category(
    ticket_id: str,
    body: CategoryUpdate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> OverrideResponse:
    category_id = await svc.set_override(session, ticket_id, body.category_id, acted_by=user.id)
    return OverrideResponse(category_id=category_id)


@router.patch("/bulk/category", response_model=BulkResult)
async def bulk_recategorize(
    body: BulkCategoryUpdate,
    session: AsyncSession = Depends(get_session),
    user: CurrentUser = Depends(get_current_user),
) -> BulkResult:
    return await bulk_svc.bulk_recategorize(
        session, body.ticket_ids, body.category_id, acted_by=user.id
    )
```

> The routers are already gated at the router level (`dependencies=protected` in main.py), so adding `Depends(get_current_user)` here just surfaces the `CurrentUser` value — it does not double-authenticate in a way that breaks; FastAPI dedupes identical dependencies. The conftest override supplies `id=1`.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_attribution.py tests/test_resolution_api.py tests/test_bulk_api.py`
Expected: PASS. Fix any existing resolve/bulk test calling `resolve(session, id)` positionally — they now need `resolved_by=...`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/resolution.py backend/app/services/bulk.py backend/app/services/tickets.py backend/app/routers/tickets.py backend/tests/test_attribution.py
git commit -m "feat(attribution): stamp resolved_by/acted_by on resolve + override (single+bulk)"
```

## Task 8b: Attribute manual "mark non-actionable" (decision: stamp it too)

**Decision (Christian, 2026-06-05):** a manual "mark non-actionable" is an operator resolve (`resolved_source='non_actionable'`) and MUST stamp `resolved_by`, like manual resolve/override. (Design §6.3 only named resolve+override; this extends it for consistency.)

**Files:**
- Modify: `backend/app/services/resolution.py` (`apply_mark_non_actionable` + its single-id `mark_non_actionable` wrapper)
- Modify: `backend/app/services/bulk.py` (`bulk_mark_non_actionable`)
- Modify: `backend/app/routers/tickets.py` (the non-actionable single + bulk handlers — inject `CurrentUser`, pass `user.id`)
- Test: extend `backend/tests/test_attribution.py`

- [ ] **Step 1: Read the current code.** Find `apply_mark_non_actionable` in `resolution.py` (the reviewer placed it ~lines 124–138), its single-id async wrapper, `bulk_mark_non_actionable` in `bulk.py`, and the matching router handlers (the non-actionable resolve endpoint + `POST /tickets/bulk/...non_actionable`). Note their exact current signatures.

- [ ] **Step 2: Write the failing test** — add to `backend/tests/test_attribution.py`:

```python
async def test_manual_non_actionable_stamps_resolved_by(client, session) -> None:
    await _seed_ticket(session, "tna")
    # use the SAME endpoint/body the webapp calls for "mark non-actionable"
    # (read routers/tickets.py for the exact path; it sets resolved_source='non_actionable')
    resp = await client.post("/tickets/tna/non-actionable")  # adjust path to the real one
    assert resp.status_code == 200
    row = await session.get(Ticket, "tna")
    assert row is not None and row.resolved_by == 1 and row.resolved_source == "non_actionable"
```

- [ ] **Step 3: Run it, verify FAIL** (`resolved_by` is None).

- [ ] **Step 4: Implement** — mirror Task 8's pattern exactly:
  - `apply_mark_non_actionable(row, *, resolved_by: int | None, ...)` — set `row.resolved_by = resolved_by` alongside `resolved_source='non_actionable'`.
  - single-id wrapper + `bulk_mark_non_actionable(..., *, resolved_by: int | None)` thread it through.
  - the two router handlers inject `user: CurrentUser = Depends(get_current_user)` and pass `resolved_by=user.id`.
  - Update every caller found (grep `mark_non_actionable`), incl. existing tests, to the keyword form.
  - `clear_resolution` already nulls `resolved_by` (Task 8) — no change needed; it covers the non-actionable reopen path too.

- [ ] **Step 5: Run** `pytest -q tests/test_attribution.py tests/test_resolution_api.py tests/test_bulk_api.py` + the broad `pytest -q --deselect tests/test_auth_config.py::test_auth_defaults`. Green. Then ruff/format/mypy clean.

- [ ] **Step 6: Commit** (scoped):

```bash
git add backend/app/services/resolution.py backend/app/services/bulk.py backend/app/routers/tickets.py backend/tests/test_attribution.py
git commit -m "feat(attribution): stamp resolved_by on manual mark-non-actionable (single+bulk)"
```

> Also add a bulk-path attribution assertion (reviewer's minor note from Task 8): a test that `POST /tickets/bulk/resolve` stamps `resolved_by` on each ok row. Fold into Step 2 or a sibling test.

## Task 9: Compose attribution into the board response (`get_tickets` user-join)

**Files:**
- Modify: `backend/app/services/tickets.py` (`get_tickets` — add a users lookup + populate `resolved_by`/`acted_by` on `TicketSchema`)
- Test: extend `backend/tests/test_attribution.py`

- [ ] **Step 1: Write the failing test** — append to `test_attribution.py`:

```python
async def test_board_surfaces_resolved_by_name(client, session) -> None:
    await _seed_ticket(session, "t2")
    await client.post("/tickets/t2/resolve")
    resp = await client.get("/tickets?resolved=true")
    assert resp.status_code == 200
    row = next(t for t in resp.json() if t["id"] == "t2")
    assert row["resolved_by"] == {"id": 1, "name": "Seed Operator"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest -q tests/test_attribution.py::test_board_surfaces_resolved_by_name`
Expected: FAIL — `resolved_by` is `None` in the response (not composed yet).

- [ ] **Step 3: Implement the user-join** — in `backend/app/services/tickets.py`:

Add `User, UserRef` to imports (`from app.models import ... User`; `from app.schemas import ... UserRef`).

Inside `get_tickets`, after the `overrides`/`followups`/`notes`/`ai_cache` side-table reads (within the `if ticket_ids:` block), collect actor ids and fetch a `{id: UserRef}` map:

```python
        actor_ids = {row.resolved_by for row in rows if row.resolved_by is not None}
        actor_ids |= {row.assigned_to for row in rows if getattr(row, "assigned_to", None) is not None}
        actor_ids |= {o.acted_by for o in overrides.values() if o.acted_by is not None}
        users = (
            {
                u.id: UserRef(id=u.id, name=u.name)
                for u in (
                    await session.scalars(select(User).where(User.id.in_(actor_ids)))
                ).all()
            }
            if actor_ids
            else {}
        )
```

(For the empty branch add `users = {}` alongside the other `= {}` defaults.)

Then in the `TicketSchema(...)` construction add, near the `resolved_source=` line:

```python
                resolved_by=users.get(row.resolved_by) if row.resolved_by is not None else None,
                acted_by=(
                    users.get(user_override and overrides[row.id].acted_by)
                    if user_override and overrides.get(row.id) is not None
                    and overrides[row.id].acted_by is not None
                    else None
                ),
                assigned_to=users.get(row.assigned_to) if row.assigned_to is not None else None,
                assigned_at=row.assigned_at,
```

> `assigned_to`/`assigned_at` columns arrive in Task 11; until then guard with `getattr`. After Task 11 simplify to direct attribute access. Simplest: do Task 11's migration first if executing strictly in order — but this task is written so it compiles either way via the `getattr` guard on the actor-id collection. Clean up the `getattr` in Task 12.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_attribution.py tests/test_tickets_api.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tickets.py backend/tests/test_attribution.py
git commit -m "feat(attribution): compose resolved_by/acted_by UserRef into board response"
```

## Task 10: Webapp — attribution types + display

**Files:**
- Modify: `webapp/src/types/api.ts` (add `UserRef`, attribution fields on `Ticket`)
- Modify: `webapp/src/components/ticket/TicketResolution.vue` ("resolved by X")
- Test: `webapp/src/components/ticket/TicketResolution.spec.ts` (create if absent, else extend)

- [ ] **Step 1: Add types** — in `webapp/src/types/api.ts`, add above `interface Ticket`:

```typescript
export interface UserRef {
  id: number;
  name: string | null;
}
```

Add inside `interface Ticket` (after `parked_note`):

```typescript
  resolved_by: UserRef | null;
  acted_by: UserRef | null;
  assigned_to: UserRef | null;
  assigned_at: string | null;
```

- [ ] **Step 2: Write the failing component test** — `TicketResolution.spec.ts`:

```typescript
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it } from 'vitest';
import TicketResolution from './TicketResolution.vue';
import type { Ticket } from '@/types/api';

function ticket(over: Partial<Ticket> = {}): Ticket {
  return {
    id: 't1', title: 'x', state: 'open', priority: null,
    created_at: '2026-06-05T00:00:00Z', updated_at: '2026-06-05T00:00:00Z',
    author: { type: 'user', name: 'C', email: null }, url: null, parts: [], internal_notes: [],
    category_id: 1, proposal_id: null, summary: '', ai_confidence: 0, user_override: false,
    title_user_edited: false, summary_user_edited: false, followup: null, note: null,
    resolved_at: '2026-06-05T01:00:00Z', resolved_source: 'manual', non_actionable_kind: null,
    ai_resolve_enabled: false, ai_resolve_override: null, ai_resolution_verdict: null,
    ai_resolution_confidence: null, ai_resolution_reason: null, resolution_chip_state: null,
    ai_priority: null, ai_sentiment: null, ai_labels: [],
    parked_at: null, parked_until: null, parked_reason: null, parked_note: null,
    resolved_by: { id: 1, name: 'Alice' }, acted_by: null, assigned_to: null, assigned_at: null,
    ...over,
  };
}

describe('TicketResolution attribution', () => {
  beforeEach(() => setActivePinia(createPinia()));
  it('shows "by <name>" when resolved_by is set', () => {
    const wrapper = mount(TicketResolution, { props: { ticket: ticket() } });
    expect(wrapper.text()).toContain('Alice');
  });
});
```

- [ ] **Step 3: Run it to verify it fails**

Run: `cd webapp && npm test -- TicketResolution`
Expected: FAIL — "Alice" not rendered.

- [ ] **Step 4: Render attribution** — in `TicketResolution.vue`, in the status-row section (after the resolved `status-pill`), add:

```vue
    <span v-if="ticket.resolved_at && ticket.resolved_by" class="status-by">
      by {{ ticket.resolved_by.name ?? 'unknown' }}
    </span>
```

(Add a minimal `.status-by { opacity: 0.7; font-size: 0.85em; }` rule if the style block needs it.)

- [ ] **Step 5: Run test to verify pass**

Run: `npm test -- TicketResolution`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/types/api.ts webapp/src/components/ticket/TicketResolution.vue webapp/src/components/ticket/TicketResolution.spec.ts
git commit -m "feat(attribution): show 'resolved by <name>' in the flyout"
```

---

# PART 3 — Assignment + My Queue (Phase 3)

## Task 11: Migration 0024 + model columns (`tickets.assigned_to`, `tickets.assigned_at`)

**Files:**
- Modify: `backend/app/models.py` (`Ticket`)
- Create: `backend/alembic/versions/0024_add_ticket_assignment.py`

- [ ] **Step 1: Add model columns** — in `class Ticket` (after `resolved_by`):

```python
    # Phase 3 (T170) — assignment. assigned_to NULL = unassigned.
    assigned_to: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

Add to `Ticket.__table_args__`:

```python
        Index("ix_tickets_assigned_to", "assigned_to"),
```

- [ ] **Step 2: Create the migration** — `backend/alembic/versions/0024_add_ticket_assignment.py`:

```python
"""Add assignment columns: tickets.assigned_to + assigned_at (T170).

assigned_to FK users.id (SET NULL), assigned_at naive-UTC. Both nullable.
Additive. Reference: multi-hosted-user-design.md §5.2.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-05 00:00:24.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets",
        sa.Column(
            "assigned_to",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column("tickets", sa.Column("assigned_at", sa.DateTime(), nullable=True))
    op.create_index("ix_tickets_assigned_to", "tickets", ["assigned_to"])


def downgrade() -> None:
    op.drop_index("ix_tickets_assigned_to", table_name="tickets")
    op.drop_column("tickets", "assigned_at")
    op.drop_column("tickets", "assigned_to")
```

- [ ] **Step 3: Verify schema smoke + clean up the Task-9 `getattr` guard**

In `get_tickets`, replace `getattr(row, "assigned_to", None)` with `row.assigned_to` now the column exists.

Run: `python -m app.models` then `pytest -q tests/test_attribution.py`
Expected: clean / PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0024_add_ticket_assignment.py backend/app/services/tickets.py
git commit -m "feat(assignment): tickets.assigned_to + assigned_at + migration 0024"
```

## Task 12: Assign service + endpoints (single + bulk) + `BulkAssign` schema

**Files:**
- Modify: `backend/app/schemas.py` (`BulkAssign`, `AssignRequest`, `AssignResponse`)
- Modify: `backend/app/services/tickets.py` (`assign`)
- Modify: `backend/app/services/bulk.py` (`bulk_assign`)
- Modify: `backend/app/routers/tickets.py` (two endpoints)
- Test: `backend/tests/test_assignment.py`

- [ ] **Step 1: Write the failing test** — `backend/tests/test_assignment.py`:

```python
"""Assignment: PATCH /tickets/{id}/assign + bulk; null clears."""

from __future__ import annotations

from app.models import Ticket
from app.util import naive_utcnow


async def _seed(session, tid: str) -> None:
    session.add(
        Ticket(id=tid, title="x", state="open", author={}, parts=[],
               created_at=naive_utcnow(), updated_at=naive_utcnow())
    )
    await session.commit()


async def test_assign_sets_and_clears(client, session) -> None:
    await _seed(session, "t1")
    resp = await client.patch("/tickets/t1/assign", json={"user_id": 1})
    assert resp.status_code == 200
    row = await session.get(Ticket, "t1")
    assert row is not None and row.assigned_to == 1 and row.assigned_at is not None
    # null clears
    resp = await client.patch("/tickets/t1/assign", json={"user_id": None})
    assert resp.status_code == 200
    row = await session.get(Ticket, "t1")
    assert row is not None and row.assigned_to is None and row.assigned_at is None


async def test_assign_unknown_user_422(client, session) -> None:
    await _seed(session, "t2")
    resp = await client.patch("/tickets/t2/assign", json={"user_id": 999})
    assert resp.status_code == 422


async def test_bulk_assign(client, session) -> None:
    await _seed(session, "a")
    await _seed(session, "b")
    resp = await client.patch("/tickets/bulk/assign", json={"ticket_ids": ["a", "b"], "user_id": 1})
    assert resp.status_code == 200
    body = resp.json()
    assert set(body["ok_ids"]) == {"a", "b"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest -q tests/test_assignment.py`
Expected: FAIL — endpoints don't exist (404/405).

- [ ] **Step 3a: Schemas** — in `backend/app/schemas.py`:

```python
class AssignRequest(BaseModel):
    user_id: int | None  # null clears the assignment


class AssignResponse(BaseModel):
    assigned_to: UserRef | None
    assigned_at: UTCDatetime | None


class BulkAssign(BulkTicketIds):
    """`PATCH /tickets/bulk/assign` body — assign N tickets to one operator (or null)."""

    user_id: int | None
```

- [ ] **Step 3b: Service `assign`** — in `backend/app/services/tickets.py`:

```python
async def assign(
    session: AsyncSession, ticket_id: str, *, user_id: int | None
) -> tuple[UserRef | None, datetime | None]:
    """Assign (or, with user_id=None, unassign) a ticket. 404 unknown ticket,
    422 unknown/inactive user."""
    row = await session.get(Ticket, ticket_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    if user_id is None:
        row.assigned_to = None
        row.assigned_at = None
        await session.commit()
        metrics.incr("tickets_assigned_total")
        return None, None
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=422, detail=f"user {user_id} not found")
    row.assigned_to = user_id
    row.assigned_at = naive_utcnow()
    await session.commit()
    metrics.incr("tickets_assigned_total")
    return UserRef(id=user.id, name=user.name), row.assigned_at
```

- [ ] **Step 3c: Service `bulk_assign`** — in `backend/app/services/bulk.py`:

```python
async def bulk_assign(
    session: AsyncSession, ticket_ids: list[str], *, user_id: int | None
) -> BulkResult:
    """Assign (or unassign, user_id=None) N tickets. 422 up-front for an unknown
    user; per-id 404 for an unknown ticket."""
    if user_id is not None:
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            raise HTTPException(status_code=422, detail=f"user {user_id} not found")
    now = naive_utcnow()

    async def per_id(tid: str) -> None:
        ticket = await session.get(Ticket, tid)
        if ticket is None:
            raise HTTPException(status_code=404, detail=f"ticket {tid!r} not found")
        ticket.assigned_to = user_id
        ticket.assigned_at = now if user_id is not None else None
        metrics.incr("tickets_assigned_total")

    result = await _run_per_id(session, ticket_ids, per_id)
    _record_outcome("assign", result)
    return result
```

Add `User` to `bulk.py` imports and `from app.models import ... User` / `Ticket` as needed.

- [ ] **Step 3d: Endpoints** — in `backend/app/routers/tickets.py` (add `AssignRequest, AssignResponse, BulkAssign` to the schemas import):

```python
@router.patch("/{ticket_id}/assign", response_model=AssignResponse)
async def assign_ticket(
    ticket_id: str,
    body: AssignRequest,
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(get_current_user),
) -> AssignResponse:
    """Assign a ticket to an operator (user_id=null clears it)."""
    ref, at = await svc.assign(session, ticket_id, user_id=body.user_id)
    return AssignResponse(assigned_to=ref, assigned_at=at)


@router.patch("/bulk/assign", response_model=BulkResult)
async def bulk_assign(
    body: BulkAssign,
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(get_current_user),
) -> BulkResult:
    """Assign N tickets to one operator (user_id=null clears). Per-id ok/failed."""
    return await bulk_svc.bulk_assign(session, body.ticket_ids, user_id=body.user_id)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_assignment.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/services/tickets.py backend/app/services/bulk.py backend/app/routers/tickets.py backend/tests/test_assignment.py
git commit -m "feat(assignment): assign + bulk_assign endpoints (null clears)"
```

## Task 13: Trim `GET /users` to id+name (Finding #4) + keep `/auth/me` full

**Files:**
- Modify: `backend/app/schemas.py` (`UserListItem`)
- Modify: `backend/app/routers/auth.py` (`list_users` response)
- Test: `backend/tests/test_auth_api.py` (extend)

- [ ] **Step 1: Write the failing test** — add to `test_auth_api.py`:

```python
async def test_users_list_excludes_onlysales_id_and_scope(client) -> None:
    resp = await client.get("/users")
    assert resp.status_code == 200
    rows = resp.json()
    assert rows and "onlysales_id" not in rows[0] and "scope" not in rows[0]
    assert set(rows[0].keys()) == {"id", "name"}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `pytest -q tests/test_auth_api.py::test_users_list_excludes_onlysales_id_and_scope`
Expected: FAIL — current `UserOut` includes `onlysales_id`/`email`/`scope`.

- [ ] **Step 3: Implement** — `UserListItem` already exists as `UserRef` (id+name). Reuse it. In `routers/auth.py`:

```python
from app.schemas import LoginRequest, LoginResponse, MeResponse, UserOut, UserRef
...
@users_router.get("", response_model=list[UserRef])
async def list_users(
    session: AsyncSession = Depends(get_session),
    _user: CurrentUser = Depends(get_current_user),
) -> list[UserRef]:
    rows = (await session.scalars(select(User).where(User.is_active.is_(True)))).all()
    return [UserRef(id=r.id, name=r.name) for r in rows]
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest -q tests/test_auth_api.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas.py backend/app/routers/auth.py backend/tests/test_auth_api.py
git commit -m "fix(auth): GET /users returns id+name only (no onlysales_id/scope leak)"
```

## Task 14: Webapp — API methods + tickets store (`myTickets`, `assign`, `bulkAssign`, `myQueueOnly`)

**Files:**
- Modify: `webapp/src/api/client.ts`
- Modify: `webapp/src/stores/tickets.ts`
- Test: `webapp/src/stores/tickets.spec.ts` (extend; create if absent)

- [ ] **Step 1: Add API methods** — in `webapp/src/api/client.ts` add `User`/`UserRef` import then, after `overrideCategory`:

```typescript
  assignTicket: (ticketId: string, userId: number | null) =>
    request<{ assigned_to: UserRef | null; assigned_at: string | null }>(
      `/tickets/${ticketId}/assign`,
      { method: 'PATCH', body: JSON.stringify({ user_id: userId }) },
    ),
```

after `bulkRecategorize`:

```typescript
  bulkAssign: (ticketIds: string[], userId: number | null): Promise<BulkResult> =>
    request('/tickets/bulk/assign', {
      method: 'PATCH',
      body: JSON.stringify({ ticket_ids: ticketIds, user_id: userId }),
    }),
```

and a users list method:

```typescript
  listUsers: (): Promise<UserRef[]> => request('/users'),
```

- [ ] **Step 2: Write the failing store test** — in `tickets.spec.ts`:

```typescript
it('myTickets filters to the current user', () => {
  const auth = useAuthStore();
  auth.user = { id: 7, onlysales_id: 'o', email: 'e', name: 'Me', scope: null };
  const tickets = useTicketsStore();
  tickets.tickets = [
    { ...baseTicket('a'), assigned_to: { id: 7, name: 'Me' } },
    { ...baseTicket('b'), assigned_to: { id: 9, name: 'Other' } },
    { ...baseTicket('c'), assigned_to: null },
  ];
  expect(tickets.myTickets.map((t) => t.id)).toEqual(['a']);
});
```

(`baseTicket(id)` helper mirrors the `ticket()` factory from Task 10; add it to the spec's setup.)

- [ ] **Step 3: Run it to verify it fails**

Run: `cd webapp && npm test -- tickets`
Expected: FAIL — `myTickets` undefined.

- [ ] **Step 4: Implement store additions** — in `webapp/src/stores/tickets.ts`:

Add near the top where other stores are used: `const auth = useAuthStore();` (import `useAuthStore`).

Add the getter (alongside `parkedTickets`):

```typescript
  const myTickets = computed(() =>
    auth.user
      ? state.value.tickets.filter((t) => t.assigned_to?.id === auth.user!.id)
      : [],
  );
  const myQueueOnly = ref(false);
  function toggleMyQueueOnly() {
    myQueueOnly.value = !myQueueOnly.value;
  }
```

Add the actions (alongside `applyOverride` / `bulkRecategorize`), following the existing optimistic pattern:

```typescript
  async function assign(ticketId: string, userId: number | null) {
    const { assigned_to, assigned_at } = await api.assignTicket(ticketId, userId);
    const t = state.value.tickets.find((x) => x.id === ticketId);
    if (t) {
      t.assigned_to = assigned_to;
      t.assigned_at = assigned_at;
    }
  }

  async function bulkAssign(ids: string[], userId: number | null): Promise<BulkResult> {
    const result = await api.bulkAssign(ids, userId);
    for (const id of result.ok_ids) {
      const t = state.value.tickets.find((x) => x.id === id);
      if (t) {
        t.assigned_to = userId === null ? null : (t.assigned_to ?? null);
        t.assigned_at = userId === null ? null : new Date().toISOString();
      }
    }
    return result;
  }
```

Then fold `myQueueOnly` into the existing `facetVisibleTickets` filter (where `parkedOnly`/`reviewOnly` are applied):

```typescript
    .filter((t) => !myQueueOnly.value || t.assigned_to?.id === auth.user?.id)
```

Export `myTickets, myQueueOnly, toggleMyQueueOnly, assign, bulkAssign` from the store's return statement.

- [ ] **Step 5: Run test to verify pass**

Run: `npm test -- tickets`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/api/client.ts webapp/src/stores/tickets.ts webapp/src/stores/tickets.spec.ts
git commit -m "feat(assignment): tickets store myTickets/assign/bulkAssign + My-Queue toggle"
```

## Task 15: Webapp — `AssigneePicker` component + mount in flyout + card tag + Topbar toggle

**Files:**
- Create: `webapp/src/components/ticket/AssigneePicker.vue`
- Modify: `webapp/src/components/ticket/TicketResolution.vue` (mount the picker)
- Modify: `webapp/src/components/TicketCard.vue` (assignee tag)
- Modify: `webapp/src/components/Topbar.vue` (My Queue chip)
- Test: `webapp/src/components/ticket/AssigneePicker.spec.ts`

- [ ] **Step 1: Write the failing test** — `AssigneePicker.spec.ts`:

```typescript
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import AssigneePicker from './AssigneePicker.vue';

vi.mock('@/api/client', () => ({
  api: { listUsers: vi.fn().mockResolvedValue([{ id: 1, name: 'Alice' }, { id: 2, name: 'Bob' }]) },
}));

describe('AssigneePicker', () => {
  beforeEach(() => setActivePinia(createPinia()));
  it('lists users from the API', async () => {
    const wrapper = mount(AssigneePicker, { props: { ticketId: 't1', assignedTo: null } });
    await flushPromises();
    expect(wrapper.text()).toContain('Alice');
    expect(wrapper.text()).toContain('Bob');
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webapp && npm test -- AssigneePicker`
Expected: FAIL — component does not exist.

- [ ] **Step 3: Create the component** — `webapp/src/components/ticket/AssigneePicker.vue`:

```vue
<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '@/api/client';
import { useTicketsStore } from '@/stores/tickets';
import type { UserRef } from '@/types/api';

const props = defineProps<{ ticketId: string; assignedTo: UserRef | null }>();
const tickets = useTicketsStore();
const users = ref<UserRef[]>([]);

onMounted(async () => {
  users.value = await api.listUsers();
});

async function onChange(e: Event) {
  const raw = (e.target as HTMLSelectElement).value;
  await tickets.assign(props.ticketId, raw === '' ? null : Number(raw));
}
</script>

<template>
  <label class="assignee">
    Assigned
    <select :value="props.assignedTo?.id ?? ''" @change="onChange">
      <option value="">Unassigned</option>
      <option v-for="u in users" :key="u.id" :value="u.id">{{ u.name ?? `#${u.id}` }}</option>
    </select>
  </label>
</template>

<style scoped>
.assignee {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  font-size: 0.85rem;
}
</style>
```

- [ ] **Step 4: Mount it** — in `TicketResolution.vue`, import and place above the presets section:

```vue
    <AssigneePicker :ticket-id="ticket.id" :assigned-to="ticket.assigned_to" />
```

In `TicketCard.vue`, add an assignee tag in the `tags` block (after ResolutionChip):

```vue
    <span v-if="props.ticket.assigned_to" class="tag assignee">
      @{{ props.ticket.assigned_to.name ?? props.ticket.assigned_to.id }}
    </span>
```

In `Topbar.vue`, add a My-Queue chip near the existing review/parked chips:

```vue
    <button
      class="chip"
      :class="{ active: tickets.myQueueOnly }"
      @click="tickets.toggleMyQueueOnly()"
    >
      My Queue
    </button>
```

(Ensure `Topbar.vue` has `const tickets = useTicketsStore();` in its script.)

- [ ] **Step 5: Run tests to verify pass**

Run: `npm test -- AssigneePicker`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/components/ticket/AssigneePicker.vue webapp/src/components/ticket/AssigneePicker.spec.ts webapp/src/components/ticket/TicketResolution.vue webapp/src/components/TicketCard.vue webapp/src/components/Topbar.vue
git commit -m "feat(assignment): AssigneePicker + card tag + My-Queue toggle"
```

---

# PART 4 — Gates, docs, verification

## Task 16: Full quality gates

- [ ] **Step 1: Backend gate**

Run: `cd backend && .\.venv\Scripts\Activate.ps1 && ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
Expected: all green. Fix any positional-arg breakages in existing resolve/override/bulk tests (now keyword-only `resolved_by=`/`acted_by=`).

- [ ] **Step 2: Webapp gate**

Run: `cd webapp && npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`
Expected: all green.

- [ ] **Step 3: Commit any gate fixes**

Stage only the specific files you changed for the fix (NEVER `git add -A` — it would commit the local `.env.example` secrets):

```bash
git add <only the files you edited to satisfy the gates>
git commit -m "chore: satisfy backend + webapp quality gates"
```

## Task 17: Contract + charter docs

**Files:** `docs/contract/spec.md`, `docs/contract/plan.md`, `docs/contract/tasks.md`, `CLAUDE.md`

- [ ] **Step 1: spec.md** — add `US-040+`/`FR-063+` for attribution, assignment, My-Queue, and the security NFRs (refresh reuse-detection, per-IP+per-email login limit). Bump to v2.0.
- [ ] **Step 2: plan.md** — add `§19 Auth & multi-user` describing the token model, reuse-detection, attribution/assignment columns, and the board user-join.
- [ ] **Step 3: tasks.md** — add `T167` (auth core, done), `T168` (reuse-detection), `T169` (attribution), `T170` (assignment) with the traceability matrix.
- [ ] **Step 4: CLAUDE.md** — rewrite "Scope guardrails"/"Don't" (auth/users/hosting IN scope; multi-tenancy OUT) and add the five MHU invariants (auth required except allowlist; stateless-access/DB-backed-revocable-refresh w/ reuse-detection; attribution/assignment columns are board-state only, never on `HydratedTicket`; per-user followups/notes deferred to a later phase; no password stored/logged).
- [ ] **Step 5: Commit**

```bash
git add docs/contract CLAUDE.md
git commit -m "docs: spec v2.0 + plan §19 + tasks T167-T170 + charter pivot (attribution/assignment)"
```

## Task 18: End-to-end manual verification

- [ ] Boot backend (worktree venv) with `SESSION_JWT_SECRET` set; confirm boot. Remove it → confirm hard-fail.
- [ ] Webapp at `http://127.0.0.1:5173`: log in (real OnlySales creds or a mocked client) → board.
- [ ] Resolve a ticket → flyout shows "resolved by <me>"; `GET /tickets?resolved=true` returns `resolved_by:{id,name}`.
- [ ] Recategorize a ticket → `overrides.acted_by` set; board composes it.
- [ ] Assign a ticket to yourself → card shows `@you`; toggle **My Queue** → only your tickets show. Assign to null → tag clears.
- [ ] Bulk-assign ≤200 ids → `ok_ids` populated; >200 rejected by `MAX_BULK_IDS`.
- [ ] Refresh-token reuse: capture a refresh cookie, force a rotation, replay the old cookie → `401` and the session is revoked (subsequent refresh with the new cookie also `401`, forcing re-login).
- [ ] Login brute-force: 11 bad logins for one email across different IPs → `429`.

---

## Self-Review notes (carried into execution)

- **Order dependency:** Task 9 references `assigned_to` before Task 11 adds it — guarded with `getattr`, cleaned up in Task 11 Step 3. If executing strictly top-to-bottom this compiles; if reordering, do Task 11 before Task 9.
- **Existing-test breakage:** Tasks 8/12 make `resolved_by`/`acted_by`/assign args keyword-only. Existing `test_resolution*.py`/`test_bulk*.py` that call services positionally must be updated — Task 16 Step 1 catches these.
- **`UserRef` reuse:** the same `UserRef` schema backs both the embedded board actor and the `GET /users` list (Task 13) — one type, consistent shape `{id, name}`.
- **Invariant #2 intact:** all new fields live on `TicketSchema`/`Override`, never on `HydratedTicket` — the normalizer and the cross-package contract are untouched.
- **Migrations:** strictly chained 0021→0022→0023→0024; only this branch adds migrations (worktree doctrine). Each `python -m app.models` smoke must stay clean.

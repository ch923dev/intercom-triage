# Backend Review Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every gap from the 2026-05-27 backend review (`backend/REVIEW-2026-05-27.md`) — one crash bug, one logic bug, dependency CVEs, key rotation, and a set of hardening + test-coverage gaps.

**Architecture:** Two correctness bugs (C1, C2) live in the same helper `_maybe_auto_resolve_from_ai` and ship cross-package (backend schema/model/migration + webapp render layer) in **one PR** per invariant #10. The remaining items (H3/H4/M1/M2/M3/L2/L3/L4 + test gaps) are backend-only and each ship as their own commit.

**Tech Stack:** FastAPI · async SQLAlchemy 2.0 · SQLite + Alembic · Pydantic v2 · pytest-asyncio · Vue 3 (webapp render layer for C1).

**Decisions locked (from review Q&A):**
- C1 maps AI verdict `'resolved'` → new `resolved_source` value `'ai_resolved'` (not reuse of `manual`/`intercom_closed`).
- Scope = all findings.

**Quality gate (run from `backend/`, venv active) — the definition of done for every backend task:**
```
ruff check app tests && ruff format --check app tests && mypy app && pytest -q
```
Webapp gate (run from `webapp/`):
```
npm run lint && npm run format:check && npm run typecheck && npm test && npm run build
```

---

## File Structure

**PR 1 — C1 + C2 + webapp (cross-package, one PR):**
- Create: `backend/alembic/versions/0012_add_ai_resolved_source.py` — widen `tickets_resolved_source_check` to include `'ai_resolved'`.
- Create: `backend/alembic/versions/0013_add_resolution_cleared_at.py` — add `tickets.resolution_cleared_at` column.
- Modify: `backend/app/schemas.py:56` — add `'ai_resolved'` to `ResolvedSource`.
- Modify: `backend/app/models.py:505,522-526` — add column + widen CheckConstraint.
- Modify: `backend/app/services/tickets.py:146-174,220,229` — verdict→source map + reopen-stickiness guard + pass content signature.
- Modify: `backend/app/services/resolution.py:52-58` — stamp `resolution_cleared_at` on reopen.
- Modify: `backend/app/services/bulk.py:143-145` — stamp `resolution_cleared_at` on bulk drag-out reopen.
- Modify: `backend/tests/test_resolution_ingest.py` — fix dead mock (L2) + add C1 + C2 tests.
- Modify: `webapp/src/types/api.ts:20` — add `'ai_resolved'` to `ResolvedSource` union.
- Modify: `webapp/src/components/ticket/TicketResolution.vue:11-22` — add label case.
- Modify: `webapp/src/stores/tickets.ts:31-33` — update docstring comment.

**PR 2 — dependency CVEs (H3) + key rotation (H4), backend-only:**
- Modify: `backend/requirements.txt`, `backend/requirements-dev.txt`.
- Operator action: rotate OpenRouter key, edit `backend/.env`.

**PR 3 — hardening + nits (M1/M2/M3/L3/L4 + remaining test gaps), backend-only:**
- Modify: `backend/app/config.py` — `MAX_INGEST_TICKETS` constant.
- Modify: `backend/app/routers/tickets.py:59-73` — ingest batch cap.
- Modify: `backend/app/services/attachments.py:62,130-135` — offload blocking I/O.
- Modify: `backend/app/services/tickets.py:104-109` (set_override) — 404 on unknown ticket.
- Modify: `backend/app/services/tickets.py:350` — title truncation 120→200.
- Modify: `backend/app/routers/health.py:11,18` — `get_config` → `get_app_config`.
- Modify: tests for the above.

---

## PR 1 — Correctness bugs (C1 + C2) + webapp

### Task 1: C1 — widen `resolved_source` to add `'ai_resolved'` and map the verdict

**Files:**
- Modify: `backend/app/schemas.py:56`
- Modify: `backend/app/models.py:522-526`
- Create: `backend/alembic/versions/0012_add_ai_resolved_source.py`
- Modify: `backend/app/services/tickets.py:160,173-174`
- Test: `backend/tests/test_resolution_ingest.py`

- [ ] **Step 1: Write the failing test** (add to `backend/tests/test_resolution_ingest.py`)

Mirror the existing `test_ingest_auto_resolves_non_actionable_when_threshold_met` test, but with verdict `'resolved'`. (Reuse that test's fixtures/helpers for settings + payload; copy its shape exactly, changing only the verdict and the assertion.)

```python
async def test_ingest_auto_resolves_resolved_verdict_sets_ai_resolved(
    client, session, settings_ai_resolve_on
):
    # AI returns a high-confidence 'resolved' verdict; auto-resolve is enabled.
    # Previously this crashed the whole ingest batch with a CHECK-constraint
    # IntegrityError because resolved_source='resolved' is not a legal value.
    payload = _hydrated_payload_with_verdict(
        verdict="resolved", confidence=0.95
    )
    resp = await client.post("/api/tickets/ingest", json=payload)
    assert resp.status_code == 200

    row = await session.get(Ticket, payload[0]["id"])
    assert row.resolved_at is not None
    assert row.resolved_source == "ai_resolved"
```

If the existing non-actionable test wires the AI verdict via a stubbed pipeline / pytest-httpx mock rather than helper functions, replicate that exact wiring here. The two helper names above (`settings_ai_resolve_on`, `_hydrated_payload_with_verdict`) must match whatever the existing test uses — read that test first and reuse its real machinery; do not invent new fixtures.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_resolution_ingest.py -k resolved_verdict -v`
Expected: FAIL — `sqlite3.IntegrityError: CHECK constraint failed: tickets_resolved_source_check` raised from the ingest commit (this reproduces C1).

- [ ] **Step 3: Add `'ai_resolved'` to the `ResolvedSource` literal** (`schemas.py:56`)

```python
ResolvedSource = Literal["manual", "intercom_closed", "non_actionable", "ai_resolved"]
```

- [ ] **Step 4: Widen the model CheckConstraint** (`models.py:522-526`)

```python
        CheckConstraint(
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable','ai_resolved')",
            name="tickets_resolved_source_check",
        ),
```

- [ ] **Step 5: Create the migration** `backend/alembic/versions/0012_add_ai_resolved_source.py`

Copy the `0010` batch-alter pattern exactly:

```python
"""Add 'ai_resolved' to tickets.resolved_source CHECK constraint.

Fixes C1 (backend/REVIEW-2026-05-27.md): AI auto-resolve with a 'resolved'
verdict must write resolved_source='ai_resolved' (a legal value) instead of
the verdict literal 'resolved', which violated the CHECK constraint and
crashed the whole ingest batch.

Revision ID: 0012
Revises: 0011
Create Date: 2026-05-27 00:00:00.000000 UTC
"""

from __future__ import annotations

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable','ai_resolved')",
        )


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_constraint("tickets_resolved_source_check", type_="check")
        batch_op.create_check_constraint(
            "tickets_resolved_source_check",
            "resolved_source IS NULL OR resolved_source "
            "IN ('manual','intercom_closed','non_actionable')",
        )
```

- [ ] **Step 6: Map the verdict → source in `_maybe_auto_resolve_from_ai`** (`tickets.py:173-174`)

Replace the buggy assignment:

```python
    row.resolved_at = now
    row.resolved_source = (
        "ai_resolved" if result.ai_resolution_verdict == "resolved" else "non_actionable"
    )
```

(Line 160's guard already restricts verdict to `("resolved", "non_actionable")`, so the `else` branch is exactly `'non_actionable'`.)

- [ ] **Step 7: Run the test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_resolution_ingest.py -v`
Expected: PASS — both the new `resolved_verdict` test and the existing `non_actionable` test green.

- [ ] **Step 8: Verify migration applies cleanly**

Run: `.venv\Scripts\python -m alembic upgrade head` (against a scratch DB or `data/triage.db`), then `.venv\Scripts\python -m alembic downgrade -1` and back `upgrade head`.
Expected: no errors; head is `0012`.

- [ ] **Step 9: Commit** (do not push yet — C1+C2+webapp ship together)

```bash
git add backend/app/schemas.py backend/app/models.py backend/alembic/versions/0012_add_ai_resolved_source.py backend/app/services/tickets.py backend/tests/test_resolution_ingest.py
git commit -m "fix(backend): map AI 'resolved' verdict to resolved_source='ai_resolved' (C1)"
```

---

### Task 2: C2 — make manual reopen sticky against the next auto-resolve

**Files:**
- Create: `backend/alembic/versions/0013_add_resolution_cleared_at.py`
- Modify: `backend/app/models.py:507`
- Modify: `backend/app/services/tickets.py:104-109,146-174,220,229`
- Modify: `backend/app/services/resolution.py:52-58`
- Modify: `backend/app/services/bulk.py:143-145`
- Test: `backend/tests/test_resolution_ingest.py`

**Approach:** Add a nullable `tickets.resolution_cleared_at` timestamp, stamped whenever the operator clears a resolution (reopen, drag-out, bulk-reopen). `_maybe_auto_resolve_from_ai` skips re-resolving while the customer-visible thread hasn't advanced past that clear — exactly mirroring the `resolution_chip_dismissed_at >= updated_at` pattern already used by `_chip_state`. A genuinely new customer message (content signature later than the clear) lets auto-resolve fire again.

- [ ] **Step 1: Write the failing test** (add to `backend/tests/test_resolution_ingest.py`)

```python
async def test_reopen_is_sticky_until_thread_advances(
    client, session, settings_ai_resolve_on
):
    # Ingest a conversation the AI resolves; operator reopens it; a re-sync of
    # the SAME content must NOT bounce it back to Resolved. A later customer
    # message (new part timestamp) DOES let auto-resolve fire again.
    payload = _hydrated_payload_with_verdict(verdict="resolved", confidence=0.95)
    tid = payload[0]["id"]

    await client.post("/api/tickets/ingest", json=payload)
    assert (await session.get(Ticket, tid)).resolved_at is not None

    # Operator reopens.
    await client.post(f"/api/tickets/{tid}/reopen")
    await session.refresh(await session.get(Ticket, tid))
    row = await session.get(Ticket, tid)
    assert row.resolved_at is None
    assert row.resolution_cleared_at is not None

    # Re-sync identical content (cached verdict) — must STAY open.
    await client.post("/api/tickets/ingest", json=payload)
    assert (await session.get(Ticket, tid)).resolved_at is None

    # Customer sends a new message → content signature advances → auto-resolve
    # is allowed to fire again.
    advanced = _append_later_customer_part(payload)
    await client.post("/api/tickets/ingest", json=advanced)
    assert (await session.get(Ticket, tid)).resolved_at is not None
```

Reuse the real helpers from Task 1's test. `_append_later_customer_part` must produce the same conversation with one extra customer-visible part whose `created_at` is strictly later than the reopen time — model it on whatever part-builder the existing tests use.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_resolution_ingest.py -k sticky -v`
Expected: FAIL — `AttributeError`/no column `resolution_cleared_at`, or the re-sync assertion fails because the ticket bounces back to resolved (this reproduces C2).

- [ ] **Step 3: Add the model column** (`models.py:507`, directly after `resolution_chip_dismissed_at`)

```python
    resolution_chip_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution_cleared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
```

- [ ] **Step 4: Create the migration** `backend/alembic/versions/0013_add_resolution_cleared_at.py`

```python
"""Add tickets.resolution_cleared_at (reopen-stickiness marker).

Fixes C2 (backend/REVIEW-2026-05-27.md): records when an operator cleared a
resolution (reopen / drag-out) so AI auto-resolve does not re-resolve the
ticket on the next sync until the customer-visible thread advances past that
moment.

Revision ID: 0013
Revises: 0012
Create Date: 2026-05-27 00:00:13.000000 UTC
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | tuple[str, ...] | None = None
depends_on: str | tuple[str, ...] | None = None


def upgrade() -> None:
    op.add_column("tickets", sa.Column("resolution_cleared_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("tickets") as batch_op:
        batch_op.drop_column("resolution_cleared_at")
```

- [ ] **Step 5: Stamp `resolution_cleared_at` on single-id reopen** (`resolution.py:52-58`)

```python
def apply_reopen(row: Ticket) -> None:
    """Mutate a Ticket row to clear its resolution. Does NOT commit. 409 if
    the row is not currently resolved."""
    if row.resolved_at is None:
        raise HTTPException(status_code=409, detail="ticket is not resolved")
    row.resolved_at = None
    row.resolved_source = None
    row.resolution_cleared_at = naive_utcnow()
```

(`naive_utcnow` is already imported in `resolution.py:17`.)

- [ ] **Step 6: Stamp on drag-out reopen in `set_override`** (`tickets.py:106-108`)

```python
    ticket = await session.get(Ticket, ticket_id)
    if ticket is not None and ticket.resolved_at is not None:
        ticket.resolved_at = None
        ticket.resolved_source = None
        ticket.resolution_cleared_at = naive_utcnow()
```

- [ ] **Step 7: Stamp on bulk drag-out reopen** (`bulk.py:143-145`)

Read `bulk.py:143-145`; it clears `ticket.resolved_at`/`ticket.resolved_source` in the bulk recategorize drag-out. Add the same line right after, using `naive_utcnow()` (import it from `app.util` at the top of `bulk.py` if not already present):

```python
            ticket.resolved_at = None
            ticket.resolved_source = None
            ticket.resolution_cleared_at = naive_utcnow()
```

Also check `bulk.py`'s `bulk_reopen` path — it delegates to `resolution.apply_reopen` (fixed in Step 5), so no extra change needed there. Confirm by reading it.

- [ ] **Step 8: Add the stickiness guard + thread the content signature into `_maybe_auto_resolve_from_ai`** (`tickets.py:146-174`)

Change the signature to accept the content signature, and add the guard:

```python
def _maybe_auto_resolve_from_ai(
    row: Ticket,
    result: CategorizationResult,
    settings: FilterSettings,
    now: datetime,
    content_signature: datetime,
) -> None:
    """Stamp resolved_at + resolved_source when the AI verdict + settings agree.

    Skipped when the ticket is already resolved by any source — never override
    an existing resolution. Intercom-closed transitions take precedence at the
    caller site (this helper runs only when that branch did not fire).

    Also skipped when the operator explicitly cleared a resolution
    (`resolution_cleared_at`) and the customer-visible thread has not advanced
    past that moment — otherwise a re-sync of unchanged content would undo a
    manual reopen (C2). A genuinely newer customer message
    (`content_signature > resolution_cleared_at`) lets auto-resolve fire again.
    """
    if row.resolved_at is not None:
        return
    if row.resolution_cleared_at is not None and content_signature <= row.resolution_cleared_at:
        return
    if result.ai_resolution_verdict not in ("resolved", "non_actionable"):
        return
    if result.ai_resolution_confidence is None:
        return
    if result.ai_resolution_confidence < settings.ai_resolve_confidence_threshold:
        return
    effective = (
        row.ai_resolve_enabled
        if row.ai_resolve_enabled is not None
        else settings.ai_resolve_default
    )
    if not effective:
        return
    row.resolved_at = now
    row.resolved_source = (
        "ai_resolved" if result.ai_resolution_verdict == "resolved" else "non_actionable"
    )
```

- [ ] **Step 9: Pass the content signature at both call sites in `_upsert_ticket`** (`tickets.py:220,229`)

`_upsert_ticket` already has `hydrated`. Compute the signature once near the top of the function (after `row = await session.get(...)`, around line 197):

```python
    now = naive_utcnow()
    content_signature = _content_signature(hydrated)
```

Then update both calls:

```python
        else:
            _maybe_auto_resolve_from_ai(new_row, result, settings, now, content_signature)
```

```python
    else:
        _maybe_auto_resolve_from_ai(row, result, settings, now, content_signature)
```

- [ ] **Step 10: Run the C2 test to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_resolution_ingest.py -v`
Expected: PASS — sticky test green, all prior tests green.

- [ ] **Step 11: Run the full backend gate**

Run: `.venv\Scripts\ruff check app tests; .venv\Scripts\ruff format --check app tests; .venv\Scripts\mypy app; .venv\Scripts\python -m pytest -q`
Expected: all green, 239+ passed.

- [ ] **Step 12: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/0013_add_resolution_cleared_at.py backend/app/services/tickets.py backend/app/services/resolution.py backend/app/services/bulk.py backend/tests/test_resolution_ingest.py
git commit -m "fix(backend): keep manual reopen sticky against AI auto-resolve on re-sync (C2)"
```

---

### Task 3: Webapp — render the new `ai_resolved` source

**Files:**
- Modify: `webapp/src/types/api.ts:20`
- Modify: `webapp/src/components/ticket/TicketResolution.vue:11-22`
- Modify: `webapp/src/stores/tickets.ts:31-33`

Column placement: `ai_resolved` belongs in the **Resolved** column. The `pureResolvedTickets` getter already shows everything with `resolved_source !== 'non_actionable'`, so no filter change is needed.

- [ ] **Step 1: Extend the `ResolvedSource` union** (`api.ts:20`)

```typescript
export type ResolvedSource = 'manual' | 'intercom_closed' | 'non_actionable' | 'ai_resolved';
```

- [ ] **Step 2: Add the display label** (`TicketResolution.vue`, inside the `statusLabel` switch)

```typescript
    case 'ai_resolved':
      return 'Resolved · ai';
```

- [ ] **Step 3: Update the store docstring** (`tickets.ts:31-33`) to mention `'ai_resolved'` lands in the Resolved column alongside `'manual'`/`'intercom_closed'`.

- [ ] **Step 4: Run the webapp gate**

Run (from `webapp/`): `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`
Expected: all green. (The old Windows CRLF format:check failure was fixed in commit `a789ef9` via `.gitattributes` + prettier `endOfLine:auto`, so `format:check` is now part of the gate.)

- [ ] **Step 5: Commit + open the cross-package PR**

```bash
git add webapp/src/types/api.ts webapp/src/components/ticket/TicketResolution.vue webapp/src/stores/tickets.ts
git commit -m "feat(webapp): render resolved_source='ai_resolved' chip (C1)"
```

Then push the branch and open ONE PR carrying Tasks 1–3 (backend + webapp) — cross-package contract change ships together per invariant #10. PR description: links C1 + C2 in `backend/REVIEW-2026-05-27.md`, notes the new migrations 0012/0013 and the new `resolved_source` value.

---

## PR 2 — Dependency CVEs (H3) + key rotation (H4)

### Task 4: Bump CVE-bearing dependencies

**Files:**
- Modify: `backend/requirements.txt:2,18,21`
- Modify: `backend/requirements-dev.txt:5`

Current pins with CVEs: `fastapi==0.115.6` (pulls vulnerable `starlette 0.41.3`), `Pillow==11.0.0`, `python-multipart==0.0.20`, `pytest==8.3.4`.

- [ ] **Step 1: Resolve the latest compatible patched versions**

Run from `backend/` (venv active):
```
.venv\Scripts\pip index versions fastapi
.venv\Scripts\pip index versions starlette
.venv\Scripts\pip index versions python-multipart
.venv\Scripts\pip index versions pillow
.venv\Scripts\pip index versions pytest
```
Pick the lowest versions that clear the CVEs: `starlette >= 1.0.1` (choose the `fastapi` release that depends on it), `python-multipart >= 0.0.27`, `pillow >= 12.2`, `pytest` latest 8.x. Note FastAPI pins a `starlette` range — bump `fastapi` to the release whose range admits the patched `starlette`, rather than pinning `starlette` directly.

- [ ] **Step 2: Update the pins** (`requirements.txt`)

```
fastapi==<resolved>
...
Pillow==<resolved>
...
python-multipart==<resolved>
```
and (`requirements-dev.txt`):
```
pytest==<resolved>
```

- [ ] **Step 3: Reinstall and re-audit**

Run:
```
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python -m pip_audit
```
Expected: 0 CVEs for the four packages (or only un-fixable advisories explicitly documented).

- [ ] **Step 4: Run the full backend gate** (Starlette/multipart bumps can shift request/response behavior)

Run: `.venv\Scripts\ruff check app tests; .venv\Scripts\mypy app; .venv\Scripts\python -m pytest -q`
Expected: all green. If a Starlette behavior change breaks a test, fix the call site, not the test assertion, unless the behavior change is intended.

- [ ] **Step 5: Commit**

```bash
git add backend/requirements.txt backend/requirements-dev.txt
git commit -m "chore(backend): bump fastapi/starlette, pillow, python-multipart, pytest for CVE fixes (H3)"
```

### Task 5: Rotate the OpenRouter key + remove the orphan token line (H4)

This is an **operator action**, not a code change — irreversible/external, so the human runs it.

- [ ] **Step 1:** Operator rotates the OpenRouter API key in the OpenRouter dashboard (the current key in `backend/.env:8` is exposed via the review and must be treated as burned). Paste the new key into `backend/.env` `OPENROUTER_API_KEY=`.
- [ ] **Step 2:** Delete the `INTERCOM_ACCESS_TOKEN=` line from `backend/.env` (line ~4) — it contradicts invariant #1 and is absent from the tracked `.env.example`.
- [ ] **Step 3:** Confirm `.env` is still gitignored: `git check-ignore backend/.env` returns the path. Confirm `git status` shows no `.env` staged.
- [ ] **Step 4:** Restart the backend; hit `GET /health` and confirm `openrouter_configured: true`, `missing_secrets: []`.

(No commit — `.env` is gitignored.)

---

## PR 3 — Hardening + nits

### Task 6: M1 — cap the `/tickets/ingest` batch size

**Files:**
- Modify: `backend/app/config.py:22`
- Modify: `backend/app/routers/tickets.py:59-73`
- Test: `backend/tests/test_ingest_api.py`

- [ ] **Step 1: Write the failing test** (`test_ingest_api.py`)

```python
async def test_ingest_rejects_oversized_batch(client):
    from app.config import MAX_INGEST_TICKETS

    payload = [_minimal_hydrated(f"conv-{i}") for i in range(MAX_INGEST_TICKETS + 1)]
    resp = await client.post("/api/tickets/ingest", json=payload)
    assert resp.status_code == 413
```

Use the existing minimal-ticket builder from `test_ingest_api.py`; if none exists, build the smallest valid `HydratedTicket` dict the other tests in that file already post.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_ingest_api.py -k oversized -v`
Expected: FAIL — returns 200 (no cap today).

- [ ] **Step 3: Add the constant** (`config.py`, beneath `MAX_BULK_IDS`)

```python
# Cap on tickets accepted in one POST /tickets/ingest call. Bounds memory +
# per-request OpenRouter fan-out / token spend (review M1). Code constant for
# the same reasons as MAX_BULK_IDS — must not drift per environment.
MAX_INGEST_TICKETS: int = 500
```

- [ ] **Step 4: Enforce it in the router** (`routers/tickets.py`)

Add the import and a guard at the top of the `ingest_tickets` endpoint:

```python
from fastapi import APIRouter, Depends, HTTPException
from app.config import AppConfig, MAX_INGEST_TICKETS
```

```python
async def ingest_tickets(
    body: list[HydratedTicket],
    session: AsyncSession = Depends(get_session),
    openrouter: OpenRouterClient | None = Depends(get_openrouter),
    config: AppConfig = Depends(get_app_config),
) -> IngestResponse:
    """Receive conversations the Chrome extension fetched from the operator's
    Intercom session; categorize (cache-aware) and store them."""
    if len(body) > MAX_INGEST_TICKETS:
        raise HTTPException(
            status_code=413,
            detail=f"ingest batch too large: {len(body)} > {MAX_INGEST_TICKETS}",
        )
    return await svc.ingest_tickets(
        session=session,
        openrouter=openrouter,
        config=config,
        hydrated=body,
    )
```

- [ ] **Step 5: Run to verify it passes**

Run: `.venv\Scripts\python -m pytest tests/test_ingest_api.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/app/routers/tickets.py backend/tests/test_ingest_api.py
git commit -m "feat(backend): cap /tickets/ingest batch at MAX_INGEST_TICKETS (M1)"
```

### Task 7: M2 — offload blocking file/PIL I/O off the event loop

**Files:**
- Modify: `backend/app/services/attachments.py:62,115-136`

`anyio` ships with FastAPI/Starlette — no new dependency.

- [ ] **Step 1: Offload the file write in `upload_attachment`** (`attachments.py:61-62`)

Add `import anyio` to the imports, then:

```python
    if not abs_path.exists():
        await anyio.to_thread.run_sync(abs_path.write_bytes, data)
```

- [ ] **Step 2: Make thumbnail generation async + offloaded** (`attachments.py:115-136`)

Convert `get_or_make_thumb_path` to `async def` and run the PIL pipeline in a worker thread:

```python
async def get_or_make_thumb_path(config: AppConfig, row: NoteAttachment) -> Path | None:
    """Return the on-disk path to a 256px max-side WebP thumbnail for an image
    attachment. Generated on first request, cached. Returns None for non-images."""
    if not row.mime.startswith("image/"):
        return None
    thumbs_dir = config.attachments_dir / "thumbs"
    thumbs_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumbs_dir / f"{row.sha256}.webp"
    if thumb_path.exists():
        return thumb_path

    source_path = config.attachments_dir / row.stored_path
    if not source_path.exists():
        return None

    def _render() -> None:
        from PIL import Image

        with Image.open(source_path) as im:
            im = im.convert("RGB")
            im.thumbnail((256, 256))
            im.save(thumb_path, format="WEBP", quality=80)

    await anyio.to_thread.run_sync(_render)
    return thumb_path
```

- [ ] **Step 3: Await it at the call site** (`routers/attachments.py:107`)

```python
    thumb = await svc.get_or_make_thumb_path(config, row)
```

- [ ] **Step 4: Run the attachment tests + gate**

Run: `.venv\Scripts\python -m pytest tests/test_attachments_api.py tests/test_attachments_service.py -v; .venv\Scripts\mypy app`
Expected: PASS. If a service test called `get_or_make_thumb_path` synchronously, add `await` there too.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/attachments.py backend/app/routers/attachments.py backend/tests/test_attachments_service.py
git commit -m "perf(backend): offload attachment write + thumbnail render to worker thread (M2)"
```

### Task 8: M3 — `set_override` should 404 on an unknown ticket

**Files:**
- Modify: `backend/app/services/tickets.py:104-109`
- Test: `backend/tests/test_tickets_api.py`

- [ ] **Step 1: Write the failing test** (`test_tickets_api.py`)

```python
async def test_override_category_unknown_ticket_404(client, seeded_category_id):
    resp = await client.patch(
        "/api/tickets/does-not-exist/category",
        json={"category_id": seeded_category_id},
    )
    assert resp.status_code == 404
```

Use whatever fixture the file already uses for a valid active category id.

- [ ] **Step 2: Run to verify it fails**

Run: `.venv\Scripts\python -m pytest tests/test_tickets_api.py -k unknown_ticket -v`
Expected: FAIL — currently 200, creating an orphan override.

- [ ] **Step 3: 404 in `set_override`** (`tickets.py:105-108`)

```python
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"ticket {ticket_id!r} not found")
    if ticket.resolved_at is not None:
        ticket.resolved_at = None
        ticket.resolved_source = None
        ticket.resolution_cleared_at = naive_utcnow()
```

(This composes with Task 2 Step 6 — the drag-out branch keeps the `resolution_cleared_at` stamp.)

- [ ] **Step 4: Run the full ticket suite** — confirm no existing test depended on the orphan-create behavior.

Run: `.venv\Scripts\python -m pytest tests/test_tickets_api.py tests/test_bulk_api.py -v`
Expected: PASS. If a test posted an override for a never-ingested id, update it to ingest the ticket first (that was relying on a bug).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/tickets.py backend/tests/test_tickets_api.py
git commit -m "fix(backend): 404 on override for unknown ticket, matching bulk path (M3)"
```

### Task 9: L2 — fix the dead AI mock in the ingest test

**Files:**
- Modify: `backend/tests/test_resolution_ingest.py` (the line that sets `openrouter.classify = AsyncMock(...)`)

- [ ] **Step 1:** Read the mock setup. The real client method is `OpenRouterClient.complete`, not `classify`. Either (a) set `openrouter.complete = AsyncMock(return_value=...)` with a realistic JSON completion so the test exercises the real AI path, or (b) if the test's intent is the fallback path, pass `openrouter=None` and drop the mock. Pick whichever matches the test's name/intent after reading it.
- [ ] **Step 2:** Run: `.venv\Scripts\python -m pytest tests/test_resolution_ingest.py -W error::RuntimeWarning -v`
Expected: PASS with no `coroutine '...' was never awaited` warning.
- [ ] **Step 3: Commit**

```bash
git add backend/tests/test_resolution_ingest.py
git commit -m "test(backend): fix dead AI mock (classify->complete) in ingest test (L2)"
```

### Task 10: L3 — align title truncation with the schema cap

**Files:**
- Modify: `backend/app/services/tickets.py:350`

- [ ] **Step 1:** Confirm `TicketEdit.title` max_length in `schemas.py` (review reported 200). If it is 200, bump the service truncation to match:

```python
            row.title = stripped[:200]
```

(If the schema cap differs from 200, use that exact value so the stored cap equals the validated cap.)

- [ ] **Step 2:** Run: `.venv\Scripts\python -m pytest tests/test_tickets_api.py -v`
Expected: PASS.
- [ ] **Step 3: Commit**

```bash
git add backend/app/services/tickets.py
git commit -m "fix(backend): align edited-title truncation with schema max_length (L3)"
```

### Task 11: L4 — `/health` reads `app.state` config like every other router

**Files:**
- Modify: `backend/app/routers/health.py:11,18`

- [ ] **Step 1:** Swap the dependency:

```python
from app.config import AppConfig
from app.deps import get_app_config
```
```python
async def health(config: AppConfig = Depends(get_app_config)) -> HealthResponse:
```

- [ ] **Step 2:** Run: `.venv\Scripts\python -m pytest tests/test_health.py -v`
Expected: PASS. The `app` fixture wires config onto `app.state`, so `get_app_config` resolves it; if the test overrode `get_config` specifically, update the override to `get_app_config` or set `app.state.config` (it already does).
- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/health.py backend/tests/test_health.py
git commit -m "refactor(backend): /health reads app.state config via get_app_config (L4)"
```

### Task 12: Remaining test-coverage gaps

**Files:**
- Modify: `backend/tests/test_resolution_api.py` (chip `new_reply`)
- Modify: `backend/tests/test_tickets_api.py` (sync-state UTC `Z` suffix)

- [ ] **Step 1: Cover the `new_reply` chip branch** — add a test that resolves a ticket with AI off, re-ingests with a later `updated_at`, and asserts `resolution_chip_state == "new_reply"` (the `_chip_state` branch at `tickets.py:62`).

```python
async def test_chip_state_new_reply_when_ai_off_and_new_activity(client, session):
    # AI resolution off; a resolved ticket that gets new activity shows the
    # 'new_reply' chip (tickets.py:62 branch — previously untested).
    ...  # resolve, then ingest the same ticket with a newer updated_at + part
    tickets = (await client.get("/api/tickets?resolved=true")).json()
    assert tickets[0]["resolution_chip_state"] == "new_reply"
```

- [ ] **Step 2: Assert the `/sync-state` `Z` suffix** — add a test that ingests one ticket and asserts the `sync-state` value is a `Z`-suffixed ISO string (invariant #5 on that endpoint, `tickets.py:get_sync_state`).

```python
async def test_sync_state_emits_z_suffixed_utc(client):
    ...  # ingest one ticket
    state = (await client.get("/api/tickets/sync-state")).json()
    assert all(v.endswith("Z") for v in state.values())
```

- [ ] **Step 3:** Run: `.venv\Scripts\python -m pytest tests/test_resolution_api.py tests/test_tickets_api.py -v`
Expected: PASS.
- [ ] **Step 4: Commit**

```bash
git add backend/tests/test_resolution_api.py backend/tests/test_tickets_api.py
git commit -m "test(backend): cover chip new_reply + sync-state Z-suffix gaps"
```

---

## Final verification (before merging PR 3)

- [ ] Run the full backend gate one more time from `backend/`:
```
.venv\Scripts\ruff check app tests && .venv\Scripts\ruff format --check app tests && .venv\Scripts\mypy app && .venv\Scripts\python -m pytest -q
```
Expected: all green.
- [ ] Run the schema smoke: `.venv\Scripts\python -m app.models` — seeds an in-memory DB, prints categories, exercises the new constraint + column.
- [ ] Confirm `.venv\Scripts\python -m alembic upgrade head` is at revision `0013`.

---

## Self-review notes

- **Spec coverage:** Every review finding maps to a task — C1→T1, C2→T2, webapp→T3, H3→T4, H4→T5, M1→T6, M2→T7, M3→T8, L2→T9, L3→T10, L4→T11, test gaps (chip `new_reply`, sync-state)→T12. L1 (content-signature stale on timestamp regression) and L5/L6 (Retry-After date form, dead `fallback_category_id` field) are **intentionally deferred** — L1 is an accepted edge given immutable Intercom timestamps, L5 is documented-and-acceptable, L6 is dead code the principles say to flag-not-delete. Noted here so they aren't silently dropped.
- **Type consistency:** `_maybe_auto_resolve_from_ai` gains one param (`content_signature: datetime`) — both call sites in `_upsert_ticket` (T2 S9) are updated. `resolution_cleared_at` is the single name used in model, migration, both stamp sites, and the guard. `get_or_make_thumb_path` becomes `async` (T7) — its one caller (`routers/attachments.py:107`) is awaited.
- **Cross-package:** Tasks 1–3 are one PR (invariant #10); migrations 0012/0013 ship with the schema change. PR 2 and PR 3 are backend-only.

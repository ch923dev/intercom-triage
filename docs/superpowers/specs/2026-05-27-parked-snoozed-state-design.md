# Parked / Snoozed ticket state — design spec

> Roadmap **4.1** · task **T106** · created 2026-05-27.
> A third operator-driven ticket state: *deferred action* ("waiting on
> customer / third party / hold"). Distinct from **resolved** (nothing to do)
> and from **non-actionable** (no action was ever warranted). Distinct also
> from follow-up *snooze* (`Followup.due_at`, an alarm reminder) and from
> Intercom's own `snoozed` conversation state (not ingested as parked).

## Goal

Let the single operator defer a ticket until a chosen time, with a reason,
so it leaves the live queue but is not lost. When the wake time passes the
ticket **flags "ready to resume" and surfaces to the top of the parked view**
but is never silently re-injected into the queue — the operator unparks it
with one click (hybrid *wake + dwell* model).

## Decisions (locked during brainstorming)

| # | Decision | Choice |
|---|----------|--------|
| 1 | Wake behavior | **Hybrid wake+dwell.** Ticket stays parked; when `parked_until <= now` it flags ★ *ready* and sorts to top. Manual one-click unpark only. No background scheduler — "ready" is computed on read. |
| 2 | Board placement | **Filter chip (Layout B).** Parked tickets are excluded from category columns; a toolbar chip `⏸ Parked N` toggles a parked-only view, with a `★ M ready` badge. |
| 3 | Reason | **Structured enum** → `parked_reason` column: `waiting_on_customer` / `waiting_on_third_party` / `waiting_internal` / `other`. |
| 4 | Scope | **Full, all three packages:** backend model + API, webapp UI (single + **bulk** park/unpark), extension popup parity (single-ticket). |
| 5 | Data model | **Approach 1 — parallel state.** Park is orthogonal to resolution; mirrors the resolution XOR-constraint pattern. |

## Non-goals (v1)

- No background job / scheduler. "Ready" is derived, never a stored flag or a push.
- No auto-park (e.g. "park on send"). Parking is always an explicit operator action.
- No ingest of Intercom's `snoozed` state into the parked columns. Parked is app-only.
- No bulk park in the **extension popup** (the popup bulk bar is the separate, unbuilt roadmap 4.4). Popup gets single-ticket park/unpark + a Parked tab only.
- No change to follow-up snooze (`Followup.due_at`) — unrelated mechanism, left intact.

---

## 1 · Data model (backend)

Three new **nullable** columns on `tickets`:

| Column | Type | Meaning |
|--------|------|---------|
| `parked_at` | naive UTC datetime, NULL | when the ticket was parked (audit / "parked since") |
| `parked_until` | naive UTC datetime, NULL | wake time; `<= now` ⇒ *ready* |
| `parked_reason` | text, NULL | enum: `waiting_on_customer` \| `waiting_on_third_party` \| `waiting_internal` \| `other` |

Two `CheckConstraint`s, mirroring the resolution invariants (#10/#11):

- **`ck_parked_trio`** — all three NULL **or** all three non-NULL. No half-parked row.
  `(parked_at IS NULL) = (parked_until IS NULL) AND (parked_at IS NULL) = (parked_reason IS NULL)`
- **`ck_not_parked_and_resolved`** — `NOT (parked_at IS NOT NULL AND resolved_at IS NOT NULL)`. A ticket is never both parked and resolved.

**Ready is derived, never stored:** `ready := parked_at IS NOT NULL AND parked_until <= now`. Computed in getters (webapp) / response logic (backend). This is what removes the need for a scheduler.

**Migration** `0018_add_parked_columns` (alembic head `0017` → `0018`): additive, nullable, no backfill. Downgrade drops the three columns and both constraints.

## 2 · API (service + routes)

New atomic service functions, modeled on `apply_reopen` — they mutate the ORM row and **do not commit** (the caller owns the transaction):

- `apply_park(row, until_at, reason)` → `409` if already parked **or** resolved; sets the trio (`parked_at = now`, `parked_until = until_at`, `parked_reason = reason`).
- `apply_unpark(row)` → `409` if not parked; clears the trio.
- **Resolve clears park:** the existing resolve path additionally clears the parked trio in the same transaction (resolution wins, consistent with the atomic drag-out reopen, invariant #11).

Routes (tickets router), registered before `/{ticket_id}/*` wildcards:

| Method · path | Body | Response |
|---|---|---|
| `POST /tickets/{id}/park` | `{ until_at: datetime, reason: enum }` | parked ticket |
| `POST /tickets/{id}/unpark` | — | ok |
| `POST /tickets/bulk/park` | `{ ids: [...], until_at, reason }` | per-id outcomes |
| `POST /tickets/bulk/unpark` | `{ ids: [...] }` | per-id outcomes |

Bulk mirrors bulk-resolve: validate `ids` against **`MAX_BULK_IDS`** (#9), loop, single end-of-loop commit, per-id outcome. Request validation: `parked_until > now` (no parking into the past); `reason` ∈ enum. API takes an **absolute `until_at`**; the webapp computes it from duration presets.

## 3 · Cross-package contract (invariants #2, #8)

The `HydratedTicket` shape spans three packages — edit together or break ingest.

- **`backend/app/schemas.py`** — add `parked_at: UTCDatetime | None`, `parked_until: UTCDatetime | None`, `parked_reason: Literal[...] | None` to the ticket response schema.
- **`extension/intercom.js` `normalizeConversation`** — emit `parked_at: null, parked_until: null, parked_reason: null`. Intercom has no parked concept; these are app-only and set via the API, never via ingest.
- **Stickiness (#8 pattern):** `_upsert_ticket` must **not** overwrite the parked trio on re-sync. Ingest always sends null; parked is operator state and survives sync, exactly like `title_user_edited` / `summary_user_edited`.
- **`webapp/src/types/api.ts`** — add the three fields to the `Ticket` interface.

## 4 · Webapp UI (Layout B — filter chip)

Store (`stores/tickets.ts`):
- open category-column getters gain `&& parked_at === null` (parked tickets drop out of the live queue)
- new getter `parkedTickets` = `parked_at != null && resolved_at == null`
- derived `readyParkedCount` = parked where `parked_until <= now`
- actions `parkTicket(id, until_at, reason)` / `unparkTicket(id)` with optimistic update + rollback (mirror `markResolved` / `reopen`). Unpark clears the trio, so the ticket reappears in its category column automatically (the open getter picks it up once `parked_at === null`) — no separate "move back" step.

View:
- toolbar chip `⏸ Parked N` with a `★ M ready` badge → toggles a parked-only filtered board view (reuse existing filter / saved-views infra)
- parked view sorts **ready-first**, then `parked_until` ascending; each card shows the reason chip + a countdown ("ready in 3h" / "★ ready") and an Unpark button
- park action: a card menu with duration presets (**1h / 4h / 1d / 3d / custom datetime**) + reason select
- `BulkActionBar`: add **Park** (duration + reason) and **Unpark**

## 5 · Extension popup (parity)

`popup.js`: a **Parked** tab (mirrors the resolved / non-actionable tab split, invariant #10) listing parked tickets with single-ticket Park / Unpark buttons. Carries the three null fields in its `HydratedTicket` shape. No bulk in the popup (see non-goals).

## 6 · Error handling

- `409` — already parked, not parked, or park-while-resolved
- `422` — `parked_until` in the past, or `reason` not in enum
- bulk — per-id outcomes: `parked` / `skipped:already_parked` / `skipped:resolved`
- webapp — optimistic mutation rolls back on any non-2xx, re-inserting the ticket at its prior position (mirror existing resolve rollback; covered by the R.2 race pattern)

## 7 · Testing

- **backend (pytest):** `ck_parked_trio` rejects a half-parked insert; `apply_park` / `apply_unpark` happy + 409 paths; resolve-clears-parked; `ck_not_parked_and_resolved`; bulk park/unpark with `MAX_BULK_IDS` boundary; validation (past `until_at`, bad reason); **`_upsert_ticket` preserves the parked trio across a re-sync** (stickiness).
- **webapp (vitest):** parked excluded from category-column getters; `readyParkedCount`; park/unpark actions + rollback on failure; bulk park/unpark.
- **extension:** `normalizeConversation` emits the three null parked fields (R.1-style payload snapshot).
- **gates:** `qa-backend` + `qa-webapp` green; extension manual reload + verify checklist.

## 8 · Docs to update (per CLAUDE.md "Don't extend surface without spec/plan/tasks first")

The implementation plan must include:
- `spec.md` — add the parked-state requirement text (new `FR-*` / `US-*`), referenced by the matrix
- `plan.md` — note the parallel-state decision + the two new CheckConstraints
- `tasks.md` — mark **T106** with its implementation footprint; add the cross-package traceability row
- `CLAUDE.md` cross-package invariants — add a parked-stickiness note alongside #8, or extend #8

## Touch-point summary

| Package | Files |
|---|---|
| backend | `models.py` (+2 constraints), `alembic/versions/0018_add_parked_columns.py` (new), `schemas.py`, resolution service (`apply_park`/`apply_unpark` + resolve-clears-park), tickets router (+4 routes), bulk service, `_upsert_ticket` stickiness |
| webapp | `types/api.ts`, `stores/tickets.ts` (getters + actions), parked-view component, toolbar chip + badge, `BulkActionBar` |
| extension | `intercom.js` `normalizeConversation` (null fields), `popup.js` (Parked tab + park/unpark) |

This is a cross-package change → **ships as one PR** across all three packages (CLAUDE.md scope guardrails).

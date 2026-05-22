# Ticket Resolution — Design

**Date:** 2026-05-23
**Status:** approved — ready for implementation plan
**Implements:** new feature; extends `spec.md` v1.3, `plan.md` v1.3, `tasks.md` v1.3

---

## 1. Goal

Operator can mark a ticket *resolved* so it leaves the board's category columns. Resolved tickets live in a dedicated "Resolved" Kanban column. New activity on a resolved ticket surfaces a chip but never auto-reopens; the operator confirms every state change. When AI is enabled (already-existing `settings.use_ai`), the same categorization call also returns an advisory resolution verdict that drives chips on cards.

## 2. Approach

Orthogonal flag on `tickets`. Resolution is **not** a category, **not** a status enum, **not** an Intercom-state mirror. A resolved ticket keeps its category id, summary, follow-up, and notes. Three sources can set the flag:

| Source | Trigger | Auto-applies? |
|---|---|---|
| `manual` | Operator drag / card icon / flyout button | yes |
| `intercom_closed` | Ticket previously open, now `state=closed` during sync | yes (silent) |
| AI suggestion | AI verdict in categorization call says `resolved` | **no** — chip only |

The same logic flips in reverse — AI thinks an already-resolved ticket is no longer resolved → chip. Operator chooses to apply or dismiss. Plain "new reply" chip fills the same slot when AI is off.

## 3. Data model

All additions land via Alembic migration (Alembic already in use per `chore/alembic-migrations`).

### 3.1 `tickets` additions

```text
resolved_at                    datetime | null
resolved_source                text | null    check in ('manual','intercom_closed')
ai_resolve_enabled             boolean | null -- null = inherit settings.ai_resolve_default
resolution_chip_dismissed_at   datetime | null
```

Invariants:
- `resolved_at` and `resolved_source` are both null or both non-null. Enforced as one CHECK: `(resolved_at IS NULL) = (resolved_source IS NULL)`.
- `resolution_chip_dismissed_at` independent — operator can dismiss a chip on either open or resolved tickets; the chip stays gone until `tickets.updated_at` advances past it.

Indexes:
- `ix_tickets_resolved_at` partial on `resolved_at IS NOT NULL` — Resolved-column queries.

### 3.2 `ai_cache` additions

```text
ai_resolution_verdict       text | null    check in ('resolved','not_resolved')
ai_resolution_confidence    real | null    [0,1]
ai_resolution_reason        text | null    check length(reason) <= 120
```

Null-friendly: legacy cache rows (pre-feature) leave the three columns null. The pipeline treats a null verdict as "no opinion" and never surfaces a chip on it. New AI calls always populate the three columns; AI failure falls back to `(NULL, NULL, NULL)` alongside the existing category fallback.

### 3.3 `settings` additions

```text
ai_resolve_default                  boolean default false
ai_resolve_confidence_threshold     real    default 0.7
                                            check between 0.0 and 1.0
```

Reuses the existing `settings.use_ai` master switch — when `use_ai=false`, the resolution verdict is never computed and `ai_resolve_default` is effectively ignored.

## 4. AI prompt + pipeline

### 4.1 Prompt extension

Single call. The existing categorization prompt grows three additional output fields. Roughly +50 tokens system + ~40 tokens model output. Cost increase negligible.

JSON contract returned by the model:

```json
{
  "assignment": "existing" | "pending_proposal" | "new_proposal",
  "category_id":  3,                   // or proposal_id / proposed_name as before
  "summary":      "...",
  "confidence":   0.84,
  "resolution_verdict":    "resolved" | "not_resolved",
  "resolution_confidence": 0.78,
  "resolution_reason":     "customer confirmed working in last reply"
}
```

System prompt addition (sketch):

> Also decide whether the conversation appears resolved. A conversation is resolved when the customer's most recent message indicates the issue is fixed, they thanked the agent for a working solution, or the agent's last reply closed the loop and the customer has not replied since. A conversation is not resolved when the customer is waiting on the agent, has a new question, or expressed dissatisfaction. Return `resolution_verdict` ∈ {`resolved`, `not_resolved`}, `resolution_confidence` ∈ [0,1], and a one-line `resolution_reason` ≤ 120 chars.

### 4.2 Resolver + cache

`services.tickets.categorize_many` writes all three new fields into `ai_cache`. Cache hit on unchanged `ticket_updated_at` reuses the verdict — no second call. Cache miss recomputes both category and verdict together.

Fallback: parse failure / network error / schema violation → category falls back to "Other" with confidence 0 (existing behavior), and the resolution triple is `(NULL, NULL, NULL)`. The batch never fails.

### 4.3 Concurrency

Unchanged. Existing `asyncio.Semaphore(AI_CONCURRENCY)` already wraps the call.

## 5. Sync / ingest changes

### 5.1 Extension fetch

Two-pass list fetch:

1. **Open pass** (existing): `GET /ember/inbox/conversations/list?...&state=open&count=N`. Same as today.
2. **Closure pass** (new): the extension reads `GET /tickets/sync-state` to learn which open-state ids the backend currently tracks, then subtracts the ids returned by the open pass to get a candidate set of "possibly closed". It pages Intercom's list endpoint with `state=closed` newest-first until either every candidate id has been seen or it falls past the lookback floor (whichever happens first). For each candidate found on the closed list it issues the same `display_as=plaintext` detail fetch as the open path. Bounded by the candidate count, not the workspace's total closed volume — cheap.

Open tickets that vanish from both passes (no longer in Intercom's recent window) are **not** auto-resolved — they fall off the board naturally via the lookback filter.

### 5.2 Backend ingest

`POST /tickets/ingest` payload schema unchanged in shape; per-ticket logic gains one branch.

```python
# Pseudocode inside services.tickets.ingest_tickets
for incoming in hydrated:
    existing = await db.get(Ticket, incoming.id)
    if incoming.state == "closed" and existing is not None and existing.resolved_at is None:
        # Intercom-side closure of a ticket we already had as open → auto-resolve.
        incoming.resolved_at = now()
        incoming.resolved_source = "intercom_closed"
        # Skip AI verdict — closure is authoritative, no need to second-guess.
    # Otherwise proceed with normal categorization (AI may set resolution_verdict).
```

A ticket that arrives as `state=closed` for the first time (we never had it open) is simply not ingested — we already filter the open-pass to open-state convos.

### 5.3 `Ticket` response shape

The `Ticket` schema gains:

```text
resolved_at:                ISO8601 | null
resolved_source:            "manual" | "intercom_closed" | null
ai_resolve_enabled:         bool                       -- effective value after merging with settings.ai_resolve_default
ai_resolution_verdict:      "resolved" | "not_resolved" | null
ai_resolution_confidence:   float | null
ai_resolution_reason:       string | null
resolution_chip_state:      "ai_resolved" | "ai_reopened" | "new_reply" | null  -- computed by the server
```

`resolution_chip_state` is a server-computed convenience that encodes the rules in §6.3 so the front-end doesn't re-derive them.

## 6. UX surfaces

### 6.1 Resolved column

- Always rendered as the right-most column on the board.
- Ignores `include_category_ids` filter — column visibility is fixed.
- Header: "Resolved" + count chip in mono.
- Empty state: faint "Nothing resolved yet" placeholder.
- Sort: `resolved_at DESC` (newest at the top).
- Cannot be archived, renamed, recolored, or reordered. Categories admin page hides it from the editable list.

### 6.2 Resolve actions (all three live simultaneously)

| Surface | Open ticket | Resolved ticket |
|---|---|---|
| Drag-and-drop | Drag card into Resolved column → resolve | Drag card into a category column → reopen + apply that category as override |
| Card icon (top-right, next to deep-link) | ✓ icon, click → resolve | ↺ icon, click → reopen |
| Flyout button | "Mark resolved" + reason label | "Reopen" with `resolved_source` + relative time ("Manually resolved 3h ago" / "Intercom closed 1d ago") |

Drag out of Resolved into a category column is a single backend transaction: clear `resolved_at` + `resolved_source`, then call existing override path. The webapp's optimistic-update + rollback pattern from T031 stays.

### 6.3 Chips

Server computes `resolution_chip_state` per ticket. Rules:

- Open ticket, AI enabled (`use_ai` AND effective `ai_resolve_enabled`), verdict = `resolved`, confidence ≥ `ai_resolve_confidence_threshold`, chip not currently dismissed
  → `ai_resolved` → renders as `AI: resolved? · 0.82`
- Resolved ticket, AI enabled, verdict = `not_resolved`, confidence ≥ threshold, `updated_at > resolved_at` (new activity), chip not dismissed
  → `ai_reopened` → renders as `AI: reopened? · 0.78`
- Resolved ticket, AI **disabled** or no verdict, `updated_at > resolved_at`, chip not dismissed
  → `new_reply` → renders as `new reply`
- Otherwise → `null`, no chip.

Click chip → applies the suggestion (resolve or reopen). Dismiss button on each chip → `POST /tickets/{id}/dismiss-chip`, which sets `resolution_chip_dismissed_at = updated_at`. Chip re-appears the next time `updated_at` advances (new message arrives).

Hover / long-press shows `ai_resolution_reason` as tooltip.

### 6.4 Settings drawer — new "Auto-resolve" section

- Master toggle: "Let AI suggest resolution" — flips `settings.ai_resolve_default`. Disabled (and explanatory note shown) when `use_ai` is off.
- Confidence slider: 0.5 – 0.95, default 0.7, step 0.05. Controls when chips appear.
- Help text: "Suggestions appear as chips on cards. AI never moves tickets automatically; you confirm every change."

### 6.5 Per-ticket AI override

Flyout exposes a small tri-state toggle next to the "Mark resolved" button:

- `AI: default` (inherits `settings.ai_resolve_default`)
- `AI: on` (this ticket — yes, run resolution suggestions)
- `AI: off` (this ticket — never)

Stored as `tickets.ai_resolve_enabled` ∈ {true, false, null}. Future bulk multi-select sends one PATCH per selected id (no new endpoint needed).

### 6.6 Filter / state interplay

`GET /tickets` keeps its current return shape but applies a default `resolved_at IS NULL` filter — the board shows only unresolved tickets. The Resolved column hits the same endpoint with `?resolved=true`. Two requests fan out from the front-end on board load.

The `states` filter (open / snoozed / closed) remains independent. Manual-resolved tickets keep their original Intercom state; the resolved flag doesn't touch it.

Lookback window already drives ingestion; once `updated_at` falls outside lookback, a resolved ticket naturally drops out of every query. No explicit Resolved-column cap.

## 7. API

### 7.1 New endpoints

| Method | Path | Body | Response | Notes |
|---|---|---|---|---|
| POST | `/tickets/{id}/resolve` | `{}` (source implicit = `manual`) | updated `TicketSchema` | 404 on unknown id, 409 if already resolved |
| POST | `/tickets/{id}/reopen` | — | updated `TicketSchema` | 404 on unknown id, 409 if already open |
| PATCH | `/tickets/{id}/ai-resolve` | `{enabled: bool \| null}` | updated `TicketSchema` | `null` = inherit |
| POST | `/tickets/{id}/dismiss-chip` | — | `{ok: true}` | Idempotent |

### 7.2 Modified endpoints

| Method | Path | Change |
|---|---|---|
| GET | `/tickets` | Adds `?resolved=true\|false\|all` query (default `false`). Default behavior unchanged for existing callers. |
| PATCH | `/tickets/{id}/category` | When the ticket is currently resolved, the same transaction clears `resolved_at` + `resolved_source` before applying the override. (Drag-out path.) |
| POST | `/tickets/ingest` | Auto-resolves on `state` transition → closed (see §5.2). Embeds new resolution fields in cached AI output. |
| GET | `/settings` / PUT | Carries `ai_resolve_default` + `ai_resolve_confidence_threshold`. |

### 7.3 Error contract

- `409` on resolve-already-resolved or reopen-already-open. Keeps the front-end's optimistic-update rollback straightforward.
- `422` on out-of-range `ai_resolve_confidence_threshold`.
- `404` on unknown ticket id.

## 8. Front-end

### 8.1 Stores

- `tickets.ts` gains:
  - state: `resolvedTickets: Ticket[]` (separate from `tickets`).
  - actions: `markResolved(id)`, `reopen(id)`, `setAiResolve(id, enabled)`, `dismissChip(id)`.
  - Existing `applyOverride(id, categoryId)` learns that a drop from Resolved into a category column should call `reopen` then `applyOverride` in one optimistic batch.
- New `tweaks.ts` keys: none — `ai_resolve_default` + threshold are server-side `settings`.

### 8.2 Components

- `Board.vue` — append `<ResolvedColumn />` after the normal column loop, always rendered.
- `ResolvedColumn.vue` (new) — sibling of `Column.vue`, hard-coded category id, queries `tickets.resolvedTickets`. Drag target ↔ drag source same as normal columns.
- `TicketCard.vue` — render the resolve icon (open vs resolved variant), the new chip slot (`resolution_chip_state` → component), and pass through.
- `ResolutionChip.vue` (new) — renders the four chip variants, exposes apply + dismiss handlers.
- `TicketFlyout.vue` — add "Resolution" section: status pill ("Open" / "Resolved · manual · 3h"), Mark-resolved / Reopen button, AI tri-state toggle.
- `SettingsDrawer.vue` — add "Auto-resolve" section.

### 8.3 Chrome extension

Popup mirrors:
- Resolved column tab added to the cycling header tabs (still cycles full taxonomy; "Resolved" is one more tab).
- TicketCard inside the popup gets the same icon + chip surfaces.
- Background poll continues to call `GET /tickets`; switches between `?resolved=true` and the default open-only flavor by tab.
- Badge count remains "Urgent" — unchanged.

## 9. Migration plan

Single Alembic revision: `add_ticket_resolution_fields`. Operations:

1. Add the four columns to `tickets` with their CHECKs + the partial index.
2. Add the three columns to `ai_cache`.
3. Add the two columns to `settings` (singleton row backfills defaults).
4. Backfill: none required — existing rows default to "unresolved" with no AI verdict.

Downgrade: drop the additions. No data loss because the legacy state is "unresolved" everywhere.

## 10. Spec / plan / tasks updates (deferred to writing-plans)

This feature lands new user stories and FRs in `spec.md` (proposed US-015 manual-resolve, US-016 AI suggests resolution, US-017 Intercom-closed auto-resolve), corresponding FRs and `plan.md` sections, and ~8–10 tasks in `tasks.md` (Phase 11). The implementation plan will detail the exact task list, dependencies, and traceability matrix updates.

## 11. Out of scope

- Bulk multi-select resolve UI (future; per §6.5 the per-ticket PATCH is forward-compatible).
- Resolved-ticket analytics / time-to-resolve dashboard.
- Auto-resolve based on Intercom `snoozed` state — only `closed` transitions trigger silent resolve.
- Re-prompting the AI with a dedicated "is resolved?" prompt — bundling is the chosen path.

## 12. Testing focus

Backend:
- Ingest sets `resolved_source='intercom_closed'` exactly once on the open→closed transition; subsequent closed-state ingests of the same id do not bump `resolved_at`.
- AI verdict null on legacy cache rows does not surface a chip.
- `resolution_chip_dismissed_at = updated_at` suppresses the chip until `updated_at` advances.
- Drag-out-of-resolved (`PATCH /tickets/{id}/category` to a non-resolved category) atomically clears resolution and applies override.
- Resolve / reopen 409s match the optimistic-update rollback path.

Front-end:
- Resolved column renders even when `include_category_ids = []`.
- Chip dismissal survives reload (it's server-side).
- Drag out of Resolved triggers exactly one network round-trip from the user's perspective (optimistic, rollback on failure).
- AI tri-state toggle correctly reflects inherited vs explicit values.

Extension popup:
- Resolved tab visible; switching tab fires the new query.
- Closure pass in the sync flow doesn't double-count or re-fetch already-closed tickets.

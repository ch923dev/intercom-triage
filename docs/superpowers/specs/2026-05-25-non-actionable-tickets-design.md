# Non-Actionable Tickets — Design

**Date:** 2026-05-25
**Status:** approved — ready for implementation plan
**Implements:** new feature; extends `spec.md` v1.5, `plan.md` v1.5, `tasks.md` v1.5; depends on Phase 11 (ticket resolution)

---

## 1. Goal

Surface a distinct "non-actionable" state for tickets that need no operator response — auto-replies, out-of-office bounces, marketing, spam, bare "thanks" after an agent reply. AI suggests; operator confirms or marks manually. Non-actionable is a sub-state of resolved: same column, same machinery, different chip label and color. Operator can mark single tickets via flyout button or batches via the bulk action bar. Drag-out reopen works identically across sub-types.

Parked / snoozed (waiting on third party / customer / hold) is a sibling concept — out of scope for this spec, captured as a backlog stub.

## 2. Approach

Sub-state of resolved. No new ticket columns. Two CHECK constraints widen:

- `tickets.resolved_source ∈ {'manual', 'intercom_closed', 'non_actionable'}` (was: `'manual' | 'intercom_closed'`).
- `ai_cache.ai_resolution_verdict ∈ {'resolved', 'not_resolved', 'non_actionable'}` (was: `'resolved' | 'not_resolved'`).

A non-actionable ticket is a resolved ticket: `resolved_at` is set, the ticket leaves category columns, lives in the Resolved column. The `resolved_source` value discriminates the chip's label and color. Reopen (drag out, button, bulk) clears both `resolved_at` and `resolved_source` regardless of value — existing invariant continues to hold.

| Source | Trigger | Auto-applies? |
|---|---|---|
| `manual` | Operator marks resolved via drag / flyout / bulk | yes |
| `intercom_closed` | Conversation state transitions open → closed during sync | yes (silent) |
| `non_actionable` | Operator marks via flyout button or bulk action OR AI verdict + auto-resolve setting | yes (manual path), yes (AI path under existing toggle) |

AI emits one of three verdicts per ticket. The existing `ai_resolve_default` + `ai_resolve_confidence_threshold` + per-ticket `ai_resolve_enabled` settings cover both `resolved` and `non_actionable` auto-close decisions. The operator's single toggle gates both — there is no separate "auto-non-actionable" setting.

## 3. Data model

Single Alembic migration: `0010_non_actionable_verdict.py`. No new columns; only CHECK widening.

### 3.1 `tickets` constraint widening

```sql
ALTER TABLE tickets DROP CONSTRAINT tickets_resolved_source_check;
ALTER TABLE tickets ADD CONSTRAINT tickets_resolved_source_check
  CHECK (resolved_source IS NULL OR resolved_source
         IN ('manual','intercom_closed','non_actionable'));
```

On SQLite the migration uses `op.batch_alter_table(..., render_as_batch=True)` to rebuild the table — same pattern as migrations 0008/0009.

### 3.2 `ai_cache` constraint widening

```sql
ALTER TABLE ai_cache DROP CONSTRAINT ai_cache_resolution_verdict_check;
ALTER TABLE ai_cache ADD CONSTRAINT ai_cache_resolution_verdict_check
  CHECK (ai_resolution_verdict IS NULL OR ai_resolution_verdict
         IN ('resolved','not_resolved','non_actionable'));
```

### 3.3 Unchanged

- `resolved_at`, `ai_resolve_enabled`, `resolution_chip_dismissed_at` — unchanged.
- `ai_resolution_reason` (≤ 120 chars), `ai_resolution_confidence` — unchanged; carry the explanation regardless of verdict value.
- `settings.ai_resolve_default`, `settings.ai_resolve_confidence_threshold` — unchanged; cover both verdicts.

### 3.4 Invariants (cross-package list addendum)

Extends CLAUDE.md cross-package invariants:

- (existing) `resolved_at` ⇔ `resolved_source` — unchanged.
- (widened) `resolved_source ∈ {'manual','intercom_closed','non_actionable'}`.
- `intercom_closed` never auto-maps to `non_actionable`. Intercom-side closure stays `intercom_closed`. The Intercom open → closed transition does not consult the AI verdict; closure is authoritative (existing §5.2 ingest rule, unchanged).
- Drag-out reopen continues to clear both fields atomically — discriminator is `resolved_at IS NOT NULL`, not the source value.

## 4. AI pipeline

### 4.1 Prompt

`backend/app/ai/prompt.py` — widen the resolution verdict allowlist in `SYSTEM_PROMPT`. JSON contract returned by the model:

```json
{
  "assignment": "existing" | "pending_proposal" | "new_proposal",
  "category_id":  3,
  "summary":      "...",
  "confidence":   0.84,
  "resolution_verdict":    "resolved" | "non_actionable" | "not_resolved",
  "resolution_confidence": 0.78,
  "resolution_reason":     "auto-reply: out-of-office bounce"
}
```

System prompt addition (sketch):

> Decide whether the conversation appears resolved, non-actionable, or unresolved.
>
> - `resolved` — customer's question or issue answered and acknowledged; thread complete.
> - `non_actionable` — no operator response required. Examples: auto-reply (out-of-office, vacation responder, calendar notification), marketing / promotional email, spam, bare "thanks" after an agent reply with nothing else to do.
> - `not_resolved` — still needs a reply.
>
> Return `resolution_verdict` ∈ {`resolved`, `non_actionable`, `not_resolved`}, `resolution_confidence` ∈ [0,1], and a one-line `resolution_reason` ≤ 120 chars. Lead the reason with a short kind tag where applicable (e.g. `"auto-reply: ..."`, `"spam: ..."`, `"thanks: ..."`).

The lead-with-kind convention is non-binding — operators read the reason as free text. It exists to leave the door open for a future structured `non_actionable_kind` column (backlog candidate) without committing to one now.

### 4.2 Parser

`app/ai/pipeline.py:parse_response` — widen the verdict allowlist. Any value outside the three-way set → `ValueError` → fallback for that ticket (existing path). Batch never aborts.

### 4.3 Resolver + cache

`CategorizationResult.resolution_verdict` widens to the three-way literal. Cache write rules unchanged: skipped on `result.fallback`, otherwise the verdict / confidence / reason triple is written verbatim. Cache hit on unchanged `ticket_updated_at` (content signature, not Intercom `updated_at`) returns the cached verdict — no second AI call.

### 4.4 Auto-apply path

`services/tickets.ingest_tickets` after the categorization call:

```python
# Pseudocode
if (
    result.resolution_verdict in ("resolved", "non_actionable")
    and effective_ai_resolve_enabled(ticket, settings)
    and result.resolution_confidence >= settings.ai_resolve_confidence_threshold
    and existing.resolved_at is None
):
    existing.resolved_at = naive_utcnow()
    existing.resolved_source = result.resolution_verdict  # 'resolved' or 'non_actionable'
```

`effective_ai_resolve_enabled` is the existing tri-state merge (per-ticket `ai_resolve_enabled` overrides `settings.ai_resolve_default`). The verdict literal doubles as the `resolved_source` value — clean mapping.

Intercom-state closure still takes precedence (resolution spec §5.2 — the open → closed branch in `ingest_tickets`): if `state=closed` on the incoming payload, `resolved_source='intercom_closed'` and AI verdict is skipped.

## 5. API

### 5.1 New endpoints

| Method | Path | Body | Response | Notes |
|---|---|---|---|---|
| POST | `/tickets/{id}/non-actionable` | `{}` | updated `TicketSchema` | 404 on unknown id, 409 if already resolved (any source) |
| POST | `/tickets/bulk/non-actionable` | `BulkTicketIds` | `BulkResult` | Same envelope and `MAX_BULK_IDS=200` cap as bulk resolve. Single commit. Per-id failure rows. |

### 5.2 Unchanged endpoints (relevant)

| Method | Path | Behavior |
|---|---|---|
| POST | `/tickets/{id}/resolve` | Sets `resolved_source='manual'`. Unchanged. |
| POST | `/tickets/{id}/reopen` | Clears `resolved_at` + `resolved_source` for any source value. Already source-agnostic; verified, not changed. |
| POST | `/tickets/bulk/resolve` | `resolved_source='manual'`. Unchanged. |
| POST | `/tickets/bulk/reopen` | Source-agnostic reopen. Unchanged. |
| PATCH | `/tickets/{id}/category` | Drag-out from Resolved column still clears resolution atomically — source-agnostic. Unchanged. |
| POST | `/tickets/{id}/dismiss-chip` | Unchanged. The `resolution_chip_dismissed_at` field already gates chips for all verdicts. |
| GET | `/tickets` | `?resolved=true` returns all resolved tickets regardless of source. Default behavior (`?resolved=false`) excludes all resolved tickets. Unchanged. |
| GET | `/settings` / PUT | `ai_resolve_default` + `ai_resolve_confidence_threshold` now cover both verdicts. Wire shape unchanged; copy update only. |

### 5.3 Service layer

`services/resolution.py` gains:

```python
async def mark_non_actionable(session, ticket_id) -> Ticket
async def bulk_mark_non_actionable(session, ticket_ids) -> BulkResult
```

Reuses the `bulk_loop(ticket_ids, per_id)` helper from T075. Single commit at end. `HTTPException(404)` per unknown id and `HTTPException(409)` per already-resolved id land in `BulkResult.failed[]` with `{id, reason}`. Duplicate ids in the request are processed once (existing dedupe rule).

The AI auto-apply path in `services/tickets.ingest_tickets` writes `resolved_source='non_actionable'` directly without going through this service — it's a write inside the ingest transaction, not a user-initiated action.

### 5.4 Error contract

- `409` on `/tickets/{id}/non-actionable` when the ticket is already resolved with any source. Operator must reopen first.
- `404` on unknown ticket id.
- `422` on bulk envelope violations (empty array, > `MAX_BULK_IDS`, malformed body). Existing validators.

## 6. UX surfaces

### 6.1 Resolved column

No structural change. Single mixed list, sorted `resolved_at DESC` (existing). Chip per card distinguishes sub-type. Column header count chip includes non-actionable tickets — they're still resolved.

### 6.2 `ResolutionChip.vue`

Renders based on the ticket's resolved-state plus AI verdict (existing `resolution_chip_state` server-computed field). Variants:

| State / verdict | Chip label | Color |
|---|---|---|
| Resolved (manual / intercom_closed) | "Resolved" | green (existing) |
| Resolved (non_actionable) | "Non-actionable" | muted gray |
| Open, AI verdict = `resolved` (suggestion) | "AI: resolved? · 0.82" | existing accent |
| Open, AI verdict = `non_actionable` (suggestion) | "AI: non-actionable? · 0.81" | muted accent |
| Resolved, AI verdict = `not_resolved` (suggestion) | "AI: reopened? · 0.78" | existing accent |
| Open, no AI / new reply | existing rules | existing |

Muted gray token: `oklch(0.65 0.00 0)` — same value as the fallback "Other" category swatch (see `DEFAULT_CATEGORIES` in `backend/app/models.py`). Token alias `--chip-non-actionable` added to the design tokens (plan §8b palette).

Hover tooltip shows `ai_resolution_reason` (existing). Click on a suggestion chip applies the verdict (resolve or mark non-actionable, mirroring the existing "Click chip → applies suggestion" rule from §6.3 of the resolution spec). Dismiss button unchanged — sets `resolution_chip_dismissed_at = updated_at` server-side.

### 6.3 `TicketCard.vue`

No structural change. The card's existing chip slot renders the widened ResolutionChip. The card's existing resolve icon (top-right) shows the open-or-resolved variant; no separate non-actionable icon — the operator uses the flyout for the sub-type choice.

### 6.4 `TicketFlyout.vue` resolution section

Open ticket:

- "Mark resolved" button (existing) — sets `resolved_source='manual'`.
- "Mark non-actionable" button (new) — sibling to "Mark resolved". Calls `POST /tickets/{id}/non-actionable`.
- AI tri-state toggle (existing) — `default / on / off`. Covers both verdicts.

Resolved ticket:

- "Reopen" button replaces both. Same behavior regardless of source.
- Status line copy: `"Marked non-actionable 2h ago"` / `"Manually resolved 3h ago"` / `"Intercom closed 1d ago"` — derived from `resolved_source` + relative time.

### 6.5 `BulkActionBar.vue`

Add "Non-actionable" button alongside existing Resolve / Reopen / Move-to / Follow-up / Clear F/U / Dismiss chip. Disabled when any selected card is already resolved (any source). Click → `tickets.bulkMarkNonActionable(selection.asArray())`. Single summary toast.

The tickets store gains `bulkMarkNonActionable(ids)` — snapshot, optimistic mutate (move cards to Resolved column with non-actionable chip), call endpoint, rollback per id reported in `failed[]`, clear selection on success. Identical pattern to `bulkResolve`.

### 6.6 Drag-and-drop

No drag-modifier in this phase. Drag into Resolved column still calls `bulkResolve` (or single-ticket resolve), `resolved_source='manual'`. Operators who want non-actionable use the flyout button or the bulk-bar button.

### 6.7 Settings drawer

No new section. Existing "Auto-resolve" copy updated:

- Toggle label: "Let AI close resolved + non-actionable tickets" (was: "Let AI close resolved tickets").
- Help text: "When AI confidence ≥ threshold, tickets the AI judges resolved or non-actionable are closed automatically. AI never closes other tickets without your confirmation."

Confidence slider + per-ticket tri-state toggle unchanged.

## 7. Chrome extension (popup)

- Card chip per the same logic as webapp `ResolutionChip` (manual / intercom_closed → green "Resolved"; non_actionable → muted gray "Non-actionable").
- Per-card flyout / action menu gains "Mark non-actionable" sibling to "Mark resolved".
- No bulk action in this phase (popup bulk is deferred — backlog T105).
- Badge count math unchanged — non-actionable tickets are resolved, already excluded from the open count.

`extension/intercom.js:normalizeConversation` — no change. `HydratedTicket` shape unchanged. Closure detection (open → closed) still maps to `resolved_source='intercom_closed'`, never `non_actionable`.

## 8. Front-end stores + types

### 8.1 TypeScript

`webapp/src/types/api.ts`:

```ts
type ResolvedSource = 'manual' | 'intercom_closed' | 'non_actionable'
type AiResolutionVerdict = 'resolved' | 'not_resolved' | 'non_actionable'
```

Widens existing literal unions. No new types.

### 8.2 API client

`webapp/src/api/tickets.ts`:

```ts
markNonActionable(id: string): Promise<Ticket>
bulkMarkNonActionable(ids: string[]): Promise<BulkResult>
```

### 8.3 Tickets store

`stores/tickets.ts` gains two actions:

- `markNonActionable(id)` — optimistic single-card mutation: move card from category column to resolved list, set local `resolved_source='non_actionable'`, call endpoint, rollback on 4xx.
- `bulkMarkNonActionable(ids)` — snapshot, optimistic batch mutate, call endpoint, per-id rollback from `failed[]`, summary toast. Identical pattern to `bulkResolve`.

## 9. Migration sequence

Cross-package change ships in one PR (invariant #2 — `HydratedTicket` shape ships together, and so does the resolved-source contract).

1. Backend: migration `0010_non_actionable_verdict.py` + schemas (literal widen) + AI prompt + parser + resolver + service + endpoint + tests.
2. Webapp: types + API client + store + ResolutionChip variants + flyout button + BulkActionBar button + tests.
3. Extension: popup chip + per-card "Mark non-actionable" menu entry.
4. Docs: `spec.md` (new FR-037, US-019), `plan.md` (extend §6 / §8c with non-actionable sub-state), `tasks.md` (Phase 13 added — index entry + detail file `docs/tasks/phase-13-non-actionable.md`), CLAUDE.md cross-package invariants list (widen #10).

## 10. Testing focus

### 10.1 Backend (`pytest`)

- `tests/test_resolution_api.py`:
  - `POST /tickets/{id}/non-actionable` happy path — `resolved_at` set, `resolved_source='non_actionable'`.
  - 409 when ticket is already resolved (any source).
  - 404 on unknown id.
  - `POST /tickets/{id}/reopen` clears non-actionable state — round-trip back to open with original category preserved.
- `tests/test_bulk_api.py`:
  - `POST /tickets/bulk/non-actionable` — happy, partial, cap (422), empty (422), unknown id (in `failed[]`).
  - `MAX_BULK_IDS` enforcement parity with other bulk endpoints.
- `tests/test_ai.py`:
  - Parser accepts `non_actionable` verdict.
  - Parser rejects out-of-set verdict → fallback path.
  - Cache round-trips the new verdict value.
- `tests/test_tickets_ingest.py`:
  - AI verdict `non_actionable` with confidence ≥ threshold + auto-resolve enabled → `resolved_source='non_actionable'`.
  - Same verdict with confidence below threshold → ticket stays open, chip surfaces.
  - Same verdict with auto-resolve disabled (per-ticket `ai_resolve_enabled=false`) → ticket stays open, chip surfaces.
  - Verdict `non_actionable` cached; fallback still never cached.
  - Intercom-state closure ingest preserves `intercom_closed`; AI verdict is not consulted in that branch.

### 10.2 Webapp (Vitest)

- `ResolutionChip.spec.ts` — renders correct label + color per `resolved_source` and per AI verdict suggestion variant.
- `tickets.store.spec.ts` — `markNonActionable` + `bulkMarkNonActionable` optimistic + rollback on `failed[]`.
- `BulkActionBar.spec.ts` — Non-actionable button disabled state when selection includes resolved card.
- `TicketFlyout.spec.ts` — Mark-non-actionable button visible on open ticket, hidden on resolved ticket (Reopen takes the slot).

### 10.3 Extension (manual smoke)

- Reload unpacked extension, open popup, mark a ticket non-actionable from card menu, refresh popup → chip persists.
- Trigger a sync that closes a ticket on Intercom side → chip reads "Intercom closed", not "Non-actionable".

## 11. Out of scope

- Parked / snoozed state (deferred — backlog T106).
- Per-kind classification column (`non_actionable_kind` enum) — captured as backlog candidate; not in this phase.
- Popup bulk actions (already deferred — backlog T105).
- Separate AI threshold / setting for non-actionable distinct from resolved (rejected during brainstorm — shared toggle wins on simplicity).
- Auto-resolve based on Intercom `snoozed` state — Phase 11 out-of-scope holds.
- Analytics / time-to-non-actionable dashboard.

## 12. Backlog stub

Add to `docs/tasks/backlog.md`:

```
- **T106** — Parked / snoozed state. Operator-chosen "waiting on third party / customer /
  hold." Distinct from non-actionable (Phase 13): non-actionable = nothing to do; parked =
  deferred action. Likely new `parked_at` + `parked_until` columns, separate column on the
  board OR a parked-filter chip on category columns. UI shape TBD.
- **T107** — Structured `non_actionable_kind` column on tickets + ai_cache (auto_reply /
  thanks / spam / out_of_office / other). Enables per-kind filtering + analytics. AI prompt
  already leads `ai_resolution_reason` with a kind tag — additive migration when needed.
```

## 13. Spec / plan / tasks updates (deferred to writing-plans)

- `spec.md`: new FR-037 (Non-actionable verdict + manual / AI mark / bulk), new US-019 (operator marks non-actionable ticket, bulk + single).
- `plan.md`: §6 widen resolved sub-states; §8c add non-actionable chip variant; §11 widen metrics counter label space.
- `tasks.md`: Phase 13 added — index entry plus detail file `docs/tasks/phase-13-non-actionable.md` with ~8–10 tasks (migration, schemas, prompt, parser, resolver, ingest, service, endpoints, webapp types + API client, ResolutionChip + flyout + BulkActionBar, store, extension popup, tests, docs).
- CLAUDE.md root + `backend/CLAUDE.md`: widen cross-package invariant #10 with the new source value.

Implementation plan (writing-plans skill) will detail the exact task list, dependencies, and traceability matrix updates.

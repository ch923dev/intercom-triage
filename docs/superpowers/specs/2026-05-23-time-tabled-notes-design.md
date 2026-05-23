# Time-tabled notes — design spec

**Status:** approved (brainstorm) — implementation plan pending
**Date:** 2026-05-23
**Author:** Christian + Claude

## Summary

Replace the per-ticket scratchpad (`ticket_notes.body` textarea) with an
append-only timeline of timestamped entries. Each entry may optionally carry a
timer (in minutes) and a follow-up reason. When an entry has a timer, it
upserts the ticket's existing `followups` row so the current alarm loop,
banner, and bucket board keep working unchanged.

Legacy scratchpad notes stay readable but become read-only after migration.
New writes always go to entries.

## Motivation

Today's notes feature is a single textarea per ticket — no history, no link
to the follow-up timer. The operator writes "investigating webhook timeout",
sets a separate follow-up reminder, and 15 minutes later overwrites the note
with the finding. Context is lost; the alarm reason and the investigation
narrative live in two unrelated rows.

The new model supports the actual workflow:

> "I'm going to investigate this." → add entry, arm 15-minute timer.
> Alarm fires. Snooze. Investigate more. Find the cause. Add entry with the
> finding; timer cleared.

Each step lands in the timeline with a timestamp. Past entries are immutable.

## Decisions (from brainstorm)

1. **Investigation log + one active timer per ticket** — not multiple parallel
   timers, not "each entry owns its timer".
2. **No fixed taxonomy** — entries are freeform `(timestamp, body)`. Earlier
   draft proposed `investigate | finding | blocked | …`; simplified away.
3. **Optional per-entry timer + reason** — entry body is required; timer
   minutes and reason are optional.
4. **New timer entry replaces prior timer** — latest entry wins. Old followup
   row overwritten in place (no FK; soft link by `ticket_id`).
5. **Append-only with soft-delete** — past entries cannot be edited. A typo
   gets a correcting entry. Hard mistakes use `deleted_at`.
6. **Alarm banner unchanged** — current chips (Snooze 5/15/30/60m, Open,
   Dismiss). No auto-snooze escalation, no inline quick-note.
7. **Both views kept** — existing follow-up bucket board stays. New
   investigation log lives inside the flyout.

## Data model

### New table — `note_entries`

```python
class NoteEntry(Base):
    __tablename__ = "note_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticket_id: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    timer_min: Mapped[int | None] = mapped_column(Integer)         # optional
    reason: Mapped[str | None] = mapped_column(Text)               # optional, ≤80
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=text("CURRENT_TIMESTAMP"), nullable=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (
        CheckConstraint("length(body) > 0", name="note_entries_body_nonempty"),
        CheckConstraint(
            "reason IS NULL OR length(reason) <= 80",
            name="note_entries_reason_len_check",
        ),
        CheckConstraint(
            "timer_min IS NULL OR timer_min BETWEEN 1 AND 1440",
            name="note_entries_timer_range_check",
        ),
        Index("ix_note_entries_ticket", "ticket_id"),
        Index("ix_note_entries_created", "created_at"),
    )
```

No FK to `tickets` — matches `followups` convention (ticket IDs owned by
Intercom; rows can outlive a ticket purge).

### Kept tables

- **`ticket_notes`** — unchanged. Becomes read-only legacy scratchpad
  after migration. New writes never touch it.
- **`followups`** — unchanged. Driven by `note_entries` rows whose
  `timer_min` is non-null.

### Soft link contract

When `POST /notes/entries` runs with `timer_min` set, the service:

1. Inserts the `note_entries` row.
2. Upserts `followups[ticket_id]` to `(due_at = now + timer_min, reason)`.
3. Commits both in a single transaction. Rollback both on either failure.

When the operator clicks "Clear timer" on the flyout, the service deletes the
`followups` row only. Entries are never mutated by timer clears.

## API

```
GET    /notes/entries                       list all entries (for store seed)
GET    /notes/entries/{ticket_id}           entries for one ticket, asc by created_at
POST   /notes/entries                       {ticket_id, body, timer_min?, reason?}
DELETE /notes/entries/{id}                  soft-delete (sets deleted_at)
```

Response shape:

```json
{
  "id": 42,
  "ticket_id": "abc",
  "body": "Investigating webhook timeout",
  "timer_min": 15,
  "reason": "check retry policy",
  "created_at": "2026-05-23T10:42:00"
}
```

Legacy `GET /notes`, `PUT /notes/{id}` kept untouched.

## Frontend

### Store — `webapp/src/stores/noteEntries.ts`

New Pinia store, parallel to `notes.ts`:

```ts
useNoteEntriesStore:
  map:  Record<ticket_id, NoteEntry[]>           // asc by created_at
  load()                                         // GET /notes/entries
  addEntry(ticketId, body, timer_min?, reason?)  // optimistic insert + followup upsert
  deleteEntry(id)                                // soft-delete
  entriesOf(ticketId): NoteEntry[]
  countOf(ticketId): number                      // non-deleted count
```

Card chip `Notes (N)` = `noteEntries.countOf(ticketId)` + (legacy `body`
non-empty ? 1 : 0). No card layout change.

### Flyout — `Next-step notes` section rewrite

```
┌─ Next-step notes ─────────────────────────────┐
│ [ Legacy note ▸ ]   (collapsed if body empty) │
│                                               │
│ ─ Timeline ─                                  │
│  10:42  Investigating webhook timeout         │
│         ⏱ 15m · "check retry policy"      [×] │
│  10:58  Found bad cron schedule               │
│  11:03  Pushed fix, watching logs             │
│         ⏱ 30m                              [×]│
│                                               │
│ ─ New entry ─                                 │
│ [ textarea ]                                  │
│ Timer: [off][5m][15m][30m][1h][custom]        │
│ Reason: [ input ≤80 ]                         │
│ [Add entry]                                   │
└───────────────────────────────────────────────┘
```

- Entries render newest-at-bottom (chronological log).
- Timer chip on entry shows minutes + reason. `[×]` clears the ticket's
  active followup. Only renders on the most-recent entry that still owns
  the active timer (compare entry timestamp to `followups[ticket_id]`).
- `Add entry` button — not debounced. Explicit commit (appending to a log,
  not editing a scratchpad).
- Existing `Follow-up` section in flyout stays as a quick "set timer without
  a log entry" path. Useful for ping-back without explanation.

## Migration

Single Alembic revision:

1. Create `note_entries` table + indices.
2. No data migration. Legacy `ticket_notes` rows kept readable.
3. `downgrade` drops `note_entries`. Legacy notes untouched.

## Tests

### Backend

- `tests/test_note_entries.py`
  - CRUD: insert, list-by-ticket, list-all, soft-delete.
  - Timer→followup upsert is atomic (both committed or both rolled back).
  - New timer entry overwrites prior `followups.due_at` + `reason`.
  - `reason` length check (≤80) enforced at DB layer.
  - `timer_min` range check (1..1440).
  - `body` non-empty constraint.
- `tests/test_note_entries_router.py`
  - Route shape matches spec.
  - 404 on missing entry id.
  - List filtered by `ticket_id`.
- Existing `tests/test_notes.py` + `tests/test_followups.py` unchanged —
  verifies legacy untouched.

### Webapp

- `noteEntries.ts` unit tests:
  - Optimistic add inserts immediately, rolls back on server failure.
  - `countOf` excludes soft-deleted entries.
  - Card chip includes legacy `body` when non-empty.

### Quality gates

```
backend: ruff check && ruff format --check && mypy app && pytest -q
webapp:  npm run typecheck && npm run build
```

## Rollout

- Single PR. Backend + webapp + Alembic migration in one branch.
- No feature flag. Local single-operator tool — no live users to gate.
- README API table updated (`/notes/entries` endpoints).

## Out of scope (YAGNI)

- Bulk add/delete entries (single-operator workflow; not needed).
- Edit entries — append-only by design. Typo = correcting entry.
- Entry kinds / taxonomy (`investigate`, `finding`, etc.) — earlier draft
  proposed, dropped for simplicity.
- Multi-timer per ticket — one active timer is the invariant.
- Auto-snooze escalation (15→30→60→manual) — earlier draft, dropped.
- Migration of legacy `ticket_notes.body` into entries — operator can
  copy-paste if desired.
- Chrome extension changes — extension does not surface notes today.

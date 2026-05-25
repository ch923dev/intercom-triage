# Phase 10 — Follow-ups, alarms, notes

Back to [tasks.md](../../tasks.md).

### T045 ✓ — `followups` + `ticket_notes` tables + `settings.mute_alarms`
**Depends on:** T006
**Implements:** FR-019, FR-023, FR-024, plan §5
**Description:** Add two SQLAlchemy models (`Followup`, `TicketNote`) and a `mute_alarms` column on `Settings`. Length check on `Followup.reason` (≤ 80). `init_db` already idempotent — schema add lands via `create_all`; existing DBs need a one-time `ALTER TABLE settings ADD COLUMN mute_alarms BOOLEAN DEFAULT 0` (documented in the task PR; later schema changes graduate to Alembic per T104).
**Acceptance:**
- Fresh boot creates both tables.
- Existing DB after migration has the `mute_alarms` column with default 0.
- Inserting a `Followup` with a 100-char reason is rejected.

### T046 ✓ — Follow-up endpoints
**Depends on:** T045
**Implements:** FR-019, FR-022, US-012
**Description:** `GET /followups`, `PUT /followups/{ticket_id}`, `POST /followups/{ticket_id}/snooze` (`{minutes:int}`), `POST /followups/{ticket_id}/mark-fired`, `DELETE /followups/{ticket_id}`. PUT upserts; snooze recomputes `due_at = now + minutes` and clears `fired`.
**Acceptance:**
- PUT then GET returns the row.
- Snooze updates `due_at` and clears `fired`.
- mark-fired sets `fired=true` without touching `due_at`.
- DELETE removes the row; subsequent DELETE returns 200 (idempotent).

### T047 ✓ — Notes endpoints
**Depends on:** T045
**Implements:** FR-023, US-014
**Description:** `GET /notes`, `PUT /notes/{ticket_id}` (`{body:str}`). Empty body deletes the row and returns `{ok, deleted:true}`.
**Acceptance:**
- PUT with non-empty body → row stored.
- PUT with empty body → row gone.
- GET returns only non-empty rows.

### T048 ✓ — `GET /tickets` composes follow-up + note + mute
**Depends on:** T025, T046, T047
**Implements:** plan §8a
**Description:** Extend the `Ticket` response shape with `followup: Followup | null` and `note: TicketNote | null` joined from the two new tables by `ticket_id`. The `mute_alarms` flag is exposed through `GET /settings`.
**Acceptance:**
- Reading a ticket with a stored follow-up returns the embedded record.
- Settings response carries `mute_alarms`.

### T049 ✓ — Webapp tokens + dark mode + accent picker
**Depends on:** T029
**Implements:** plan §8b
**Description:** CSS variables for the light + dark palettes per plan §8b. Geist + JetBrains Mono loaded from Google Fonts in `index.html`. Tweaks store persists dark mode, accent swatch, density, show-summary, show-confidence — server side via existing `settings` row (extended with these fields). Pulse / ring / slide keyframes injected once.
**Acceptance:**
- Toggling dark mode flips `<html data-theme>`.
- Picking an accent re-paints the page within one frame.

### T050 ✓ — Follow-up store + chip + pin-to-top
**Depends on:** T031, T046
**Implements:** US-012, FR-019, plan §8a
**Description:** Pinia `followupsStore` with `setFollowup`, `clearFollowup`, `snooze`, `markFired`. `TicketCard` renders the chip per plan §8b. Column-grouping sorter pins due tickets to the top.
**Acceptance:**
- Setting a follow-up via the flyout renders a chip immediately (optimistic).
- A due card sorts to the top of its column.

### T051 ✓ — Alarm loop + banner stack + mute
**Depends on:** T050, T027
**Implements:** US-013, FR-020, FR-021, FR-022, FR-024
**Description:** Once-per-second tick. On transition to due: push a banner record, play WebAudio ping unless `mute_alarms` is set, `POST .../mark-fired`. Banner exposes Open / Snooze 15 m / Snooze 1 h / Dismiss. Top-bar status pill shows pending count + flips to accent-pulse when at least one is firing.
**Acceptance:**
- Setting a +12 s follow-up triggers banner + audio at the right moment.
- Muting suppresses audio but not the banner.
- Snooze repositions the alarm; Dismiss leaves the row alone.

### T052 ✓ — Notes section in flyout
**Depends on:** T031, T047
**Implements:** US-014, FR-023
**Description:** Textarea bound to `PUT /notes/{ticket_id}` debounced 400 ms. Seven preset chips append `\n• <preset>` bullets. Card surface shows `Notes (N)` chip when body has non-empty lines.
**Acceptance:**
- Typing then waiting 400 ms persists.
- Emptying the textarea deletes the row server-side.

### T053 ✓ — Popup mirror — due banner + chip
**Depends on:** T041, T046
**Implements:** US-013 popup mirror
**Description:** Popup reads `GET /followups` on open, runs the same tick loop. Renders a due banner at the top when at least one follow-up is due. Each list row shows the countdown chip; due rows get a 2 px accent left-bar.
**Acceptance:**
- Opening the popup while a follow-up is due shows the banner.
- Closing + reopening preserves state.

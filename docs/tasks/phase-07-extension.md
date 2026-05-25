# Phase 7 — Chrome extension

Back to [tasks.md](../../tasks.md).

### T040 ✓ — MV3 manifest + popup shell
**Depends on:** T001
**Implements:** US-006
**Description:** `manifest.json` (MV3), `popup.html`, minimal popup script. Permissions: `storage`. `host_permissions` for `http://localhost:8000/*`. Icons at 16/32/48/128.
**Acceptance:** Loads as unpacked without warnings; popup renders.

### T041 ✓ — Popup mini-board
**Depends on:** T040, T025, T026
**Implements:** US-006
**Description:** Column-tab UI cycling through the full taxonomy (including pending proposals). TicketCard reused or recreated more compact. Tap-to-move override action suitable for popup size (a button list rather than full DnD).
**Acceptance:**
- All categories selectable.
- Override action works inside the popup and survives close/reopen.
- "Open full board" button opens `http://localhost:5173/`.

### T042 ✓ — Background poll + badge
**Depends on:** T041, T027
**Implements:** US-006
**Description:** Service worker re-runs the Intercom session scrape + `POST /tickets/ingest` on the configured interval (read from server settings, off by default). Badge text shows the Urgent count.
**Acceptance:**
- Interval set → badge updates after next poll.
- Interval off → no background calls.

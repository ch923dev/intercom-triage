# Phase 6 — Webapp

Back to [tasks.md](../../tasks.md).

### T029 ✓ — Vite + Vue 3 + TS scaffold
**Depends on:** T001
**Implements:** —
**Description:** Initialize `webapp/` with Vite. Add Pinia, `vuedraggable@next`, ESLint, Prettier.
**Acceptance:** `npm run dev` serves the scaffold against the backend.

### T030 ✓ — Typed API client
**Depends on:** T029, T025, T026, T027
**Implements:** —
**Description:** `src/api.ts` exposing typed clients for every endpoint in plan §4. Errors surface as typed exceptions, not silent rejections.
**Acceptance:** Functions compile against the backend's OpenAPI schema; 502 raises a typed error.

### T031 ✓ — Tickets + categories stores (Pinia)
**Depends on:** T030
**Implements:** —
**Description:** Stores: `categoriesStore`, `ticketsStore`, `settingsStore`. Actions include `applyOverride(id, category_id)` with optimistic update + rollback on failure.
**Acceptance:** `applyOverride` updates immediately; reverts on a mocked failed PATCH.

### T032 ✓ — Kanban layout, dynamic columns
**Depends on:** T031
**Implements:** US-002, US-009, FR-013
**Description:** Columns rendered from `categoriesStore`, including pending proposals as live columns with a distinct visual treatment. Independent vertical scroll. Empty / loading / error states per column.
**Acceptance:**
- Fresh DB shows seven seeded columns.
- A pending proposal appears as a column with a "proposal" badge until resolved.

### T033 ✓ — TicketCard
**Depends on:** T032
**Implements:** US-003, US-005
**Description:** Title, customer, `time-ago`, summary, confidence indicator, deep-link icon (new tab, `rel="noopener noreferrer"`), override badge when applicable.
**Acceptance:** All fields render; deep-link opens in a new tab.

### T034 ✓ — Drag-and-drop override
**Depends on:** T033, T031
**Implements:** US-004, FR-009
**Description:** `vuedraggable` between columns. On drop, call `applyOverride` (optimistic + rollback).
**Acceptance:** Drag persists after refresh; failed PATCH snaps back with a toast.

### T035 ✓ — Settings drawer
**Depends on:** T031
**Implements:** US-001, US-007, FR-011, FR-012
**Description:** Drawer for lookback unit/value, states, included categories. Reads/writes via `/settings`. Apply on change.
**Acceptance:** Reloading the page restores settings from server; changing the filter triggers a refresh.

### T036 ✓ — Toolbar + keyboard nav
**Depends on:** T032
**Implements:** NFR-007
**Description:** Refresh button, last-refreshed timestamp, arrow keys to scroll columns, `r` to refresh.
**Acceptance:** Keyboard-only flow works; refresh button disables in-flight.

### T037 ✓ — Category management page
**Depends on:** T031, T018, T019, T020
**Implements:** US-011, FR-017
**Description:** A page that lists active categories with inline rename/recolor/reorder, an archive button, and a "Merge into…" action.
**Acceptance:** All four mutations work end-to-end against the API.

### T038 ✓ — Proposals review page
**Depends on:** T031, T022, T023, T024
**Implements:** US-010, FR-016
**Description:** Lists pending proposals with example tickets. Approve, "Merge into…", and Reject actions.
**Acceptance:**
- Each action calls the matching endpoint and refreshes the board.
- Rejected proposal's name no longer triggers a fresh proposal in the next fetch.

### T039 ✓ — Extension discovery callout
**Depends on:** T029
**Implements:** plan §2
**Description:** Persistent but dismissible callout on the webapp pointing to the extension folder + install instructions.
**Acceptance:** Callout appears until dismissed; dismissal persists.

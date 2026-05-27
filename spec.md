# Intercom Triage — Specification

**Status:** ready · **Version:** 1.6 · **Sibling docs:** `plan.md`, `tasks.md`

This document defines **what** the system does. It contains no technology choices, no library names, no code structure — all such decisions live in `plan.md`. Every requirement here is traced by at least one task in `tasks.md`.

**Changes from v1.5:** backfilled definitions for two capabilities already shipped in code and traced in `tasks.md` but missing from this spec. Added the **non-actionable tickets** capability — US-019 / FR-037 let the operator (or AI ingest) mark spam / thank-you / out-of-scope tickets as a non-actionable sub-state of resolved, split out at the view layer. Also documented the **reusable playbooks** capability already present as US-020 / FR-038..FR-041.

**Changes from v1.4:** added the **bulk actions** capability. US-018 lets the operator select multiple tickets at once and apply resolve / reopen / recategorize / set-follow-up / clear-follow-up / dismiss-chip as one action. FR-032..FR-036 cover the transient selection set, bulk endpoints with per-id result reporting, in-column range-select, bulk drag (dragging one selected card moves all selected), and the per-request id cap.

**Changes from v1.3:** added the **ticket resolution** capability. US-015 lets the operator mark a ticket resolved; US-016 surfaces an AI advisory chip when the AI thinks a ticket's resolution state has changed; US-017 auto-resolves tickets that flip to `state=closed` in Intercom. Added FR-025..FR-031 covering the orthogonal resolution flag, resolution sources, server-computed chip state, four new endpoints, the per-ticket AI-resolve tri-state, settings persistence, and the extension closure pass.

**Changes from v1.2:** added the **follow-up / alarm / notes** capability surfaced by the design (`Intercom Triage.html`). US-012 lets the operator pin a follow-up reminder on a ticket; US-013 fires a visible + audible alarm when the reminder comes due; US-014 lets the operator capture how-to-proceed notes per ticket. Surfaces a status pill in both the webapp and the popup. No removals.

**Changes from v1.1:** multi-tenant scope removed. The system is a single-user local tool: one Intercom workspace, one taxonomy, one operator. Authentication, tenant isolation, and managed identity are out. The dynamic-category proposal flow is kept — it's useful even for one user. Persona collapses to a single operator role.

---

## 1. Purpose

Reduce the time spent triaging Intercom conversations. The native Intercom UI requires opening each conversation to learn its nature; this system pre-categorizes and pre-summarizes a recency-windowed slice of the inbox so I can scan and route in a single view. The category taxonomy is mine to curate and grows over time as the AI surfaces patterns the existing taxonomy doesn't cover.

## 2. Scope

In scope: a local tool with a backend, a webapp surface, and a Chrome extension surface. Intercom integration via the operator's logged-in browser session (extension-driven; no API token). AI categorization and summarization against a curated taxonomy. AI proposal flow for new categories. Manual category override that persists. Dynamic category curation.

Out of scope: multi-user collaboration, multi-tenant SaaS, authentication, hosted deployment, replying to tickets from the tool, long-term analytics, helpdesks other than Intercom, mobile-native surfaces, webhook-driven live updates (backlog).

## 3. Personas

A single **operator** — the person running the tool on their own machine. They sign in to Intercom in Chrome, install the extension, triage tickets daily, and curate categories as the taxonomy evolves.

## 4. User stories with acceptance criteria

### US-001 — Recency-filtered ticket list
I can choose a recency threshold and see only conversations updated within that window.

Acceptance:
- The threshold accepts a unit ∈ {hours, days} and an integer in [1, 720].
- No ticket with `updated_at` older than `now − threshold` appears in the list.
- Changing the threshold without reloading the surface refreshes the list.
- The threshold persists across reloads.

### US-002 — Auto-categorized board
Every ticket is assigned to exactly one column from my current taxonomy without manual action.

Acceptance:
- Every returned ticket carries either an active category id or a pending proposal id.
- Categorization happens before tickets appear on the board.
- If AI categorization fails for a ticket, the ticket still appears, assigned to the fallback category ("Other," seeded on first run).

### US-003 — Per-ticket summary and confidence
I can read a 1–2 sentence summary on each card and see how confident the AI was, without opening the conversation.

Acceptance:
- Each card displays a summary of ≤ 280 characters.
- The summary captures the customer's intent and any named entity (feature, error, plan).
- Each card displays a confidence indicator derived from the AI's score in [0.0, 1.0].
- If AI summarization fails, the card displays the conversation title or a sensible fallback and confidence 0.

### US-004 — Manual category override
I can move a ticket to a different column, and that placement survives refreshes until the ticket has new activity.

Acceptance:
- Moving a ticket between columns is supported through a direct interaction.
- After moving, refreshing the board keeps the ticket in the new column.
- The override is dropped when the ticket's `updated_at` advances past the moment the override was set.
- Overridden cards display a visual marker.

### US-005 — Deep link to Intercom
I can jump from a card to the original Intercom conversation in one click.

Acceptance:
- Each card exposes a link that opens the corresponding Intercom conversation in a new tab.

### US-006 — Genuine mini-board in the Chrome extension
I can use a compact but fully functional triage board from the Chrome popup without leaving my current tab.

Acceptance:
- The popup loads in under 2 seconds on a warm cache.
- The popup renders the full taxonomy as switchable column tabs.
- An override action works inside the popup.
- The popup includes a one-click handoff to the full webapp.
- The popup and the webapp share filter settings.

### US-007 — Configurable filter
I can choose which ticket states and which categories appear on the board.

Acceptance:
- States can be any subset of {open, snoozed, closed}; the default is {open}.
- Included categories can be any subset of the active taxonomy; the default is all active.
- Filter changes are reflected on the next fetch.
- Filter is persisted.

### US-008 — Local credentials, never in client surfaces
My Intercom and AI provider credentials live in a local config file and are never sent to either client surface.

Acceptance:
- Credentials are loaded from a `.env` file the backend reads at startup.
- Neither the webapp nor the extension ever receives the credentials.
- Rotating a credential takes effect after a backend restart.

### US-009 — AI proposes new categories
When a ticket does not fit any existing category, I see it grouped under an AI-proposed category instead of being forced into "Other."

Acceptance:
- The AI may return a proposal `{name, description}` instead of an existing category id when no existing category fits with reasonable confidence.
- Tickets matching the same proposal cluster under that proposal on the board.
- A proposal carries the same summary, confidence, and override capability as a normal category.

### US-010 — I curate proposals
I can review AI-proposed categories and resolve each one: approve as a new category, merge into an existing category, or reject.

Acceptance:
- A "Proposals" view lists every pending AI proposal with example tickets.
- Approving creates a new active category; tickets currently grouped under the proposal move to that category automatically.
- Merging picks an existing category; tickets currently grouped under the proposal move there.
- Rejecting moves the affected tickets to the fallback category and records the proposal name so the AI does not re-propose it.
- Pending proposals appear on the board as distinct columns until resolved.

### US-011 — I manage the active taxonomy
I can create, rename, recolor, reorder, archive, and merge categories at any time.

Acceptance:
- Archiving a category hides it from the board; cached tickets pointing at it are reassigned to the fallback on next fetch.
- Renaming preserves the category id; existing tickets keep their assignment.
- Merging moves all tickets from the source category to the target and archives the source.
- The fallback category cannot be archived.

### US-012 — Per-ticket follow-up reminders
I can pin a follow-up reminder on a ticket with a relative duration, and see a live countdown on the card.

Acceptance:
- I can set a reminder using a preset (`15m`, `1h`, `4h`, `EOD`, `24h`) or a custom duration in minutes.
- A follow-up records an optional short reason string (≤ 80 chars).
- I can clear a follow-up at any time.
- A ticket has at most one active follow-up at any time; setting a new one overwrites the old.
- The follow-up survives reloads of both surfaces until cleared or its ticket's `updated_at` advances past `dueAt` AND the reminder has fired.
- The card displays a follow-up chip: `F/U in 15m` while pending, `Follow up · due now` once due.
- Due tickets pin to the top of their column.

### US-013 — Audible + visible alarm when a follow-up comes due
When a follow-up reaches its due time, the surface raises an alarm I can act on without leaving the board.

Acceptance:
- An alarm banner appears top-right of the webapp board and at the top of the popup.
- A short audio cue plays once per newly-firing alarm.
- I can mute the audio cue from a single control in the top bar; the muted state persists across reloads.
- Each alarm banner exposes actions: open the ticket flyout, snooze 15 m, snooze 1 h, dismiss.
- Snoozing reschedules the follow-up by the chosen interval.
- Dismissing hides the banner but leaves the follow-up record in place (the card still shows `due now`).
- The top-bar status pill shows the count of pending follow-ups, and flips to an accent-pulse state when at least one alarm is firing.

### US-014 — Per-ticket next-step notes
I can capture how-to-proceed notes on a ticket and append common actions in one click.

Acceptance:
- The flyout exposes a freeform notes textarea per ticket.
- A row of one-click chips appends preset actions (`Page @on-call`, `Reply with workaround`, `Escalate to AE`, `Ask for repro / logs`, `Wait for customer`, `Route to Eng triage`, `Refund / credit`) as bullets into the textarea.
- Notes persist across reloads and across both surfaces.
- The card displays a `Notes (N)` chip where N is the number of non-empty bullet lines.
- Clearing the textarea removes the notes record server-side.

### US-015 — Manual ticket resolution
I can mark a ticket as resolved; resolved tickets leave the category columns and
live in a dedicated Resolved column that is always shown.

Acceptance:
- A "Mark resolved" action is available on every open ticket from three surfaces:
  drag into the Resolved column, the card-level ✓ icon, and the flyout button.
- Resolved tickets disappear from category columns and appear in the Resolved
  column, sorted most-recently-resolved first.
- The Resolved column is always visible regardless of `include_category_ids`.
- I can reopen a resolved ticket via drag, icon, or flyout; reopening returns
  it to its category column.

### US-016 — AI suggests resolution
When the AI thinks a ticket appears resolved (or that a resolved ticket is no
longer resolved), I see an advisory chip on the card. The AI never moves a
ticket automatically.

Acceptance:
- The same AI categorization call returns `resolution_verdict`,
  `resolution_confidence`, and `resolution_reason`.
- A chip appears on a card only when the effective AI-resolve flag is on for
  that ticket, the verdict is opposite to current state, confidence ≥
  the configured threshold, and the chip has not been dismissed since the
  ticket's last update.
- Clicking the chip applies the suggestion.
- Dismissing the chip hides it until the ticket has new activity.

### US-017 — Intercom-closed tickets auto-resolve
A ticket I previously had as open that flips to `state=closed` in Intercom is
silently resolved with `source='intercom_closed'`.

Acceptance:
- The extension's sync flow includes a closure pass: it diffs tracked ids
  against the open list and pulls just the missing ids from Intercom's closed
  list.
- The backend `_upsert_ticket` stamps `resolved_at` + `resolved_source` only
  on the open→closed transition (not on every closed-state sync).
- No AI call is made for the closure event.

### US-018 — Bulk actions on selected tickets
I can select multiple tickets at once and apply a single action to all of them
— resolve, reopen, recategorize, set or clear a follow-up, dismiss a resolution
chip — without clicking through each card.

Acceptance:
- I can toggle a ticket in or out of the selection with Cmd/Ctrl+click.
- I can extend the selection with Shift+click across a contiguous range
  **within the same column** (sorted card order). Shift+click in a different
  column toggles that one ticket only.
- A column header exposes a "Select all (N)" affordance that adds every card
  in that column to the selection.
- Clicking the empty background, pressing Escape, or switching surfaces
  clears the selection.
- When the selection is non-empty, an action bar appears showing the count
  and the available bulk actions; actions that don't apply to the current
  selection (e.g. Reopen when not all selected are resolved) are disabled.
- Dragging one selected card into a different column or the Resolved column
  moves every selected ticket along with it.
- A bulk action reports per-id success and failure; partial failure does not
  block the rest of the batch.
- A single bulk request is bounded by a configurable maximum (default 200).
  Selecting more than the cap surfaces a warning and asks me to split the
  action.

### US-019 — Mark tickets non-actionable
I can mark a ticket that needs no reply — spam, a thank-you, an auto-reply, an
out-of-scope message — as non-actionable, so it leaves my active board without
being counted as a real resolution. The AI can also flag obvious non-actionable
tickets for me during ingest.

Acceptance:
- I can mark a ticket non-actionable from the flyout, and apply the same action
  across a multi-ticket selection in one step.
- A non-actionable ticket is a sub-state of resolved: it carries `resolved_at`
  with `resolved_source = non_actionable`. Reopening it clears both.
- Non-actionable tickets are split from genuinely resolved ones at the view
  layer — their own Kanban column in the webapp and their own popup tab — while
  storage stays unified under the resolution flag.
- When the AI's verdict is non-actionable with confidence at or above the shared
  resolution threshold, ingest auto-marks the ticket; a fallback verdict never
  does.

### US-020 — Reusable playbooks per category
As the operator, when I solve a ticket I can save a reusable
"playbook" (a next-steps recipe) scoped to its category, optionally drafted
by AI from that ticket, and see it on every other ticket in the same
category so I handle repeat issues consistently.

## 5. Functional requirements

| ID | Requirement | Stories |
|---|---|---|
| FR-001 | The system fetches Intercom conversations filtered by `updated_at > now − threshold`. | US-001 |
| FR-002 | The fetch result is bounded by a configurable maximum count per request. | US-001 |
| FR-003 | Each fetched conversation has its full message thread hydrated and converted to plain text before AI input. | US-002, US-003 |
| FR-004 | Every ticket returned to a client carries either an active category id or a pending proposal id. | US-002, US-009 |
| FR-005 | Every ticket returned to a client carries a summary string. | US-003 |
| FR-006 | Every ticket returned to a client carries a confidence score in [0.0, 1.0]. | US-003 |
| FR-007 | AI failures degrade to `category = fallback`, `summary = title-or-fallback`, `confidence = 0`. The batch always completes. | US-002, US-003 |
| FR-008 | Re-fetching a ticket whose `updated_at` has not advanced reuses the prior AI result. | NFR-002 |
| FR-009 | A user override on a ticket is persisted and supersedes AI categorization until the ticket's `updated_at` advances past the override time. | US-004 |
| FR-010 | The system exposes a per-ticket deep-link URL to the Intercom conversation. | US-005 |
| FR-011 | The system accepts filter settings per request: recency, states, included categories. | US-001, US-007 |
| FR-012 | Filter settings are persisted and read by both surfaces. | US-006, US-007 |
| FR-013 | Tickets returned to a client are sorted by `updated_at` descending. | — |
| FR-014 | External credentials are loaded from local config and never transmitted to a client. | US-008 |
| FR-015 | The AI may return a proposal instead of an existing category when no existing category fits with reasonable confidence; the system persists the proposal and groups matching tickets under it. | US-009 |
| FR-016 | I can approve, merge, or reject proposals; resolution reassigns affected tickets accordingly. | US-010 |
| FR-017 | I can create, rename, recolor, reorder, archive, and merge active categories. | US-011 |
| FR-018 | The system seeds a default taxonomy on first run: Urgent, Bug, Feature Request, Question, Billing, Complaint, Other. "Other" is the non-archivable fallback. | US-002, US-011 |
| FR-019 | Each ticket may carry at most one active follow-up record with `due_at`, optional `reason`, and a `fired` flag. | US-012 |
| FR-020 | A surface evaluates follow-up due-ness on a once-per-second tick; a follow-up is "due" when `due_at ≤ now`. | US-013 |
| FR-021 | A surface plays an audio cue and shows an alarm banner exactly once when a follow-up transitions from pending to due. The mute toggle suppresses the audio cue but not the banner. | US-013 |
| FR-022 | Snoozing an alarm sets `due_at = now + snooze_minutes` and clears `fired`. Dismissing the alarm does not reschedule the follow-up. | US-013 |
| FR-023 | Each ticket may carry one notes record with a free-text body. Empty body deletes the record. | US-014 |
| FR-024 | Settings include a `mute_alarms` boolean; both surfaces read and write through the existing settings endpoint. | US-013 |
| FR-025 | Tickets carry `resolved_at` and `resolved_source` as an orthogonal resolution flag, independent of category assignment and Intercom state. | US-015, US-016, US-017 |
| FR-026 | Resolution source is one of three values: `manual` (operator action), `intercom_closed` (sync auto-resolve), or implied by an AI-suggested chip the operator confirms. | US-015, US-016, US-017 |
| FR-027 | The backend computes `resolution_chip_state` (`ai_resolved` \| `ai_reopened` \| `new_reply` \| `null`) server-side from settings + ticket + AI cache, and includes it in every ticket response. | US-016 |
| FR-028 | The system exposes `POST /tickets/{id}/resolve`, `POST /tickets/{id}/reopen`, `PATCH /tickets/{id}/ai-resolve`, and `POST /tickets/{id}/dismiss-chip`. `GET /tickets` accepts `?resolved=true\|false`; default excludes resolved tickets. | US-015, US-016 |
| FR-029 | Each ticket carries a per-ticket AI-resolve tri-state override (`true` / `false` / `null`); `null` means inherit `settings.ai_resolve_default`. | US-016 |
| FR-030 | Settings persist `ai_resolve_default` (bool) and `ai_resolve_confidence_threshold` (float 0..1); both are read and written through the existing settings endpoint. | US-016 |
| FR-031 | On each sync the extension performs a closure pass: it compares tracked ticket ids against the open list returned by Intercom and fetches the closed-conversation list for any ids that have gone missing, then ingests them so the backend auto-resolves via the open→closed transition. | US-017 |
| FR-032 | The webapp maintains a transient client-side selection set of ticket ids. The set is cleared on view change, on Escape, on an empty-background click, and after every successful bulk action. | US-018 |
| FR-033 | The backend exposes bulk endpoints that accept `{ticket_ids: string[]}` arrays and return `{ok_ids: string[], failed: [{id, reason}]}`. A per-id failure does not abort the rest of the batch. | US-018 |
| FR-034 | Shift+click extends the selection across the contiguous range of cards in the same column (in displayed sort order). Shift+click in a different column toggles only the clicked card. | US-018 |
| FR-035 | Dragging any selected card propagates the drop to every card in the selection set. Dropping into a category column reassigns all of them; dropping into the Resolved column resolves all of them. | US-018 |
| FR-036 | A single bulk request is bounded by `MAX_BULK_IDS` (configurable, default 200). The webapp warns and refuses to submit a bulk action over the cap; the backend rejects oversize requests with 422. | US-018 |
| FR-037 | A ticket may be marked non-actionable, a sub-state of resolved that sets `resolved_at` with `resolved_source = non_actionable` (XOR-constrained against the other resolution sources). The system exposes `POST /tickets/{id}/non-actionable` and `POST /tickets/bulk/non-actionable`; ingest auto-applies the verdict when the AI returns `non_actionable` at or above the shared resolution-confidence threshold, never on a fallback verdict. Non-actionable tickets are surfaced as their own view (Kanban column / popup tab) while storage stays unified; reopen clears the flag. | US-019 |
| FR-038 | Playbooks are stored in a dedicated `playbooks` table (category_id, label, body, optional source_ticket_id, soft-archive). They are operator-owned and survive ingest / re-sync untouched (never content-keyed). | US-020 |
| FR-039 | The flyout lists active playbooks for a ticket's *effective* category (override beats AI). Uncategorized tickets show none. | US-020 |
| FR-040 | `POST /playbooks/draft` returns an ephemeral AI-drafted body from the ticket's customer-visible `parts` + operator notes. It MUST NOT read `internal_notes` (FR-005 / invariant #4). 503 when AI is unconfigured. | US-020 |
| FR-041 | A library page lists playbooks grouped by category with edit, archive, and restore (including an archived view); new playbooks are captured from a ticket flyout (FR-039/FR-040). | US-020 |

## 6. Non-functional requirements

| ID | Requirement |
|---|---|
| NFR-001 | A cold fetch of 50 tickets completes in ≤ 15 s end-to-end. |
| NFR-002 | A warm fetch of 50 tickets (AI cache hot) completes in ≤ 3 s. |
| NFR-003 | One failing ticket categorization does not block or fail the batch. |
| NFR-004 | All cross-request state lives in a single persistent store on disk. |
| NFR-005 | External secrets are loaded from a local config file, not from source. |
| NFR-006 | External calls (Intercom, AI provider) emit structured logs carrying latency and outcome. Ticket bodies are never logged. |
| NFR-007 | The webapp surface is keyboard-navigable for column scrolling, refresh, and override. |
| NFR-008 | The backend runs from a single command (`uvicorn` or equivalent) with no external services required beyond the local database file. |

## 7. Decisions

All open questions are resolved.

- **Deployment scope:** single user, local-only. No cloud services. Runs from one command.
- **Multi-tenancy:** none.
- **Authentication:** none. The backend listens on `localhost` only; absence of auth is acceptable given the threat model (single-user machine).
- **Storage backend:** SQLite by default. Swappable to PostgreSQL by changing one config string; schema is portable.
- **Update mechanism:** poll-on-open for v1. Webhook deferred to backlog.
- **Taxonomy mutability:** dynamic. AI may propose, operator curates. "Other" is permanent and non-archivable.
- **Extension popup depth:** genuine mini-board with override support. The webapp surfaces a callout for installing the extension.
- **Low-confidence handling:** confidence is displayed on every card; no separate review column.

## 8. Success metrics

- Time-to-clear-inbox is at least 3× faster than the Intercom-native flow.
- ≥ 80% of AI categorizations require no manual override.
- p95 fetch latency under 8 seconds with cache warm.
- ≥ 70% of AI-proposed categories are either approved or merged (not rejected), measured after the first 30 days of use.

# Intercom Triage — Specification

**Status:** ready · **Version:** 1.8 · **Sibling docs:** `plan.md`, `tasks.md`

This document defines **what** the system does. It contains no technology choices, no library names, no code structure — all such decisions live in `plan.md`. Every requirement here is traced by at least one task in `tasks.md`.

**Changes from v1.7:** ingestion pivot — the backend now fetches Intercom conversations directly from the official `api.intercom.io` REST API using a workspace Access Token, replacing the former Chrome-extension session scrape. A background poller + `POST /tickets/sync` drive ingestion; the extension becomes a read-only mini-board. Rewrote FR-001 + FR-031 and added NFR-010 (Intercom token is a server-side secret). No board behavior removed.

**Changes from v1.6:** reconciliation backfill — the forward roadmap (`docs/ROADMAP.md`) was executed in full through Phase 3 + 4.1, but the shipped capability landed in code ahead of this spec. This version writes the source-of-truth requirements for the 19 shipped-but-undocumented features: triage facets (US-022), aging indicators (US-023), keyboard triage (US-024), saved views (US-025), priority-sorted queue (US-026), stats dashboard (US-027), cost meter (US-028), snippets (US-029), bulk pre-flight diff (US-030), reliable structured AI output (US-031), model cascade (US-032), needs-review lane (US-033), local embedding layer (US-034), few-shot categorization (US-035), RAG draft replies (US-036), recurring-issue clustering (US-037), playbook-gap detection (US-038), playbook auto-match (US-039). Adds FR-043..FR-061 and NFR-009. No capability removed; no behavior changed — code and spec are now in sync.

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
- A non-actionable ticket carries an optional structured kind (auto_reply / thanks / spam / out_of_office / other); the AI sets it on auto-mark, manual marks leave it null, reopen clears it.

### US-020 — Reusable playbooks per category
As the operator, when I solve a ticket I can save a reusable
"playbook" (a next-steps recipe) scoped to its category, optionally drafted
by AI from that ticket, and see it on every other ticket in the same
category so I handle repeat issues consistently.

### US-021 — Park / snooze a ticket
As the operator, I can park a ticket I'm waiting on (customer, third party, or
internal) until a chosen time with a reason, so it leaves my live queue without
being lost; when the wake time passes it flags "ready to resume" and I unpark it
in one click.

### US-022 — Triage facets on every card
Beyond a category, I see the AI's read of each ticket's priority, the customer's
sentiment, and a few free-form labels, so I can work the queue by urgency and
tone — not just by topic.

Acceptance:
- The same categorization call returns `priority` (low / normal / high / urgent),
  `sentiment` (negative / neutral / positive), and zero or more short `labels`.
- The facets are cached alongside the categorization result and reused on warm
  fetches without re-calling the AI.
- Facets add no second AI call and do not change the cache key — internal
  teammate notes still don't bust the cache.
- Cards display a priority badge and (where shown) sentiment; tickets predating
  this capability simply carry no facets.

### US-023 — Aging indicators on cards
I can see at a glance how long a ticket has gone without a customer reply, so
stale tickets stop silently rotting.

Acceptance:
- Each card carries an age tier derived from time since its last
  customer-visible message.
- The tier is shown as a visual treatment (e.g. a colored stripe), tiered by
  configurable thresholds held in one place.
- Aging is presentation only — it never changes stored state or ordering by
  itself.

### US-024 — Keyboard-driven triage
I can run a full triage loop from the keyboard without reaching for the mouse.

Acceptance:
- `j` / `k` move focus between cards; `e` resolves the focused ticket; a digit
  key moves it to the Nth category; `/` focuses the search box.
- Shortcuts never fire while a text input, textarea, or contenteditable is
  focused.
- The focused card is visibly indicated.

### US-025 — Saved views / smart filters
I can save a named filter preset (category, age, urgency, resolution source) and
recall it in one click — e.g. "my morning queue."

Acceptance:
- I can save the current filter facets as a named view and re-apply it later.
- Saved views persist locally across reloads.
- Applying a view sets the active filter; clearing returns to the default board.
- Saving a view requires no backend change — the board already returns the
  fields a view filters on.

### US-026 — Priority-sorted queue
I can sort or group the board by the AI priority facet so I drain the most
urgent tickets first.

Acceptance:
- A toggle orders cards within each column by priority (urgent → low), falling
  back to recency within a priority band.
- The setting is remembered across reloads.
- With the toggle off, the existing recency / follow-up-due ordering is
  unchanged.

### US-027 — Stats dashboard
I can see how the queue is performing: category breakdown, volume trend,
resolution-source mix, and how long tickets take to resolve.

Acceptance:
- A dashboard renders the four success metrics (spec §8) over a trailing window
  I can choose (in days).
- The numbers are aggregated server-side over the local store; no new ingest is
  required.
- Resolution mix distinguishes manual / intercom_closed / non_actionable /
  ai-confirmed sources.

### US-028 — Token / cost meter
I can see how much I'm spending on the AI provider per day, since I pay for my
own calls.

Acceptance:
- Per-day OpenRouter token usage and an estimated USD cost are tracked,
  bucketed by date and model.
- The current day's spend is visible in the webapp.
- The estimate is best-effort from token counts × model pricing; it resets on
  backend restart (in-process counters) and is never billed-against.

### US-029 — Snippets / canned responses
I can keep short reusable reply snippets with fill-in placeholders, lighter than
a full playbook, for high-frequency answers.

Acceptance:
- I can create, edit, archive, and restore snippets, each a title plus a body.
- A body may contain `{{variable}}` placeholders; substitution happens
  client-side from the ticket I'm viewing.
- Snippets are durable operator knowledge — they survive ingest / re-sync and
  are never content-keyed.

### US-030 — Bulk pre-flight diff
Before I apply a bulk action I see how many tickets it will actually affect and
how many will be skipped, so the bulk path stays legible.

Acceptance:
- Selecting a bulk action previews a count, e.g. "12 will resolve, 3 skipped
  (already resolved)."
- The preview respects the `MAX_BULK_IDS` cap and warns before a selection over
  the cap.
- The preview is computed client-side from already-loaded ticket state.

### US-031 — Reliable structured AI output
The AI's categorization output is structurally valid so the board doesn't fall
back to "Other" because of a malformed `{...}` response.

Acceptance:
- The categorization call requests a schema-enforced JSON object.
- A response that doesn't satisfy the schema is rejected and degrades to the
  fallback for that one ticket — the batch never aborts (FR-007 unchanged).

### US-032 — Model cascade (opt-in)
To cut cost, easy tickets can be categorized by a cheap model and only
low-confidence ones escalated to the strong model.

Acceptance:
- A cheap model handles the first pass; when its self-reported confidence is
  below a configurable threshold (or the cheap call fails / is malformed), the
  ticket escalates to the strong model.
- The cascade is off by default — out-of-the-box behavior is a single
  strong-model call.
- The escalation trigger reuses the same confidence the needs-review lane reads.

### US-033 — Needs-review lane
Low-confidence categorizations surface in a dedicated review lane instead of
silently committing, so I can confirm the AI's guesses.

Acceptance:
- An open, non-overridden ticket whose categorization confidence is below a
  calibrated threshold appears in a "needs review" lane.
- The lane is a view-layer split over the existing confidence value — not a
  stored ticket state.
- Confirming a ticket (writing an override) removes it from the lane.

### US-034 — Local embedding layer
The tool can embed ticket text locally and offline, providing the vector
substrate for few-shot, RAG, clustering, and auto-match — with no data leaving
the machine.

Acceptance:
- Customer-visible `parts[]` (+ title / operator notes) are embedded with a
  local CPU model; `internal_notes[]` are never embedded.
- Embeddings are computed on ingest and stored in the local database; computing
  them never busts the AI content-signature cache.
- The layer can be disabled (e.g. low-RAM machines); disabled means the ingest
  hook is a no-op and the dependent features degrade gracefully.

### US-035 — Few-shot categorization from confirmed overrides
The categorizer learns from my confirmed category overrides by showing the AI
the nearest confirmed examples, improving consistency on repeat issues.

Acceptance:
- When categorizing an uncached ticket, the nearest confirmed-override
  neighbours are retrieved and injected into the prompt as examples.
- The number of examples is configurable; zero disables injection and matches
  the cold-corpus prompt exactly.
- Retrieval is gated on the embedding layer — no embeddings, no neighbours.

### US-036 — RAG draft replies
I can ask for a draft customer reply grounded in our own resolved tickets and
playbooks, so drafts match my voice and prior resolutions rather than being
generic.

Acceptance:
- A draft is grounded in the nearest resolved tickets (customer-visible content
  only) plus the ticket's effective-category playbooks.
- The draft is ephemeral — never persisted as ticket state — and exposes what
  it was grounded in (ticket ids, playbook ids) for transparency.
- `internal_notes[]` never reach a draft.

### US-037 — Recurring-issue clustering
The tool groups resolved tickets into recurring-issue clusters so I can see
which problems repeat.

Acceptance:
- An offline periodic job clusters resolved tickets' embeddings and labels each
  cluster with its top terms drawn from customer-visible text only.
- Clustering runs in the background (not per request) and outliers are flagged,
  not force-fit into a cluster.
- The cluster snapshot is read-only over the API; a manual recompute is
  available.

### US-038 — "What should I build a playbook for"
I can see which recurring-issue clusters have no matching playbook yet, ranked
by frequency, so I know where a playbook would pay off most.

Acceptance:
- Clusters whose dominant effective category has no active playbook are listed,
  ranked most-recurring-first.
- Each entry names the category to write a playbook for and the support behind
  the suggestion.
- The ranking is read-only local logic over the cluster snapshot + playbooks.

### US-039 — Playbook auto-match on ticket open
When I open a ticket, the most relevant playbooks for it are suggested
automatically rather than my scanning a category-filtered list.

Acceptance:
- On open, the ticket's effective-category playbooks are ranked by semantic
  similarity to its customer-visible text, most-relevant-first.
- Suggestions are ephemeral and scoped to the effective category (override beats
  AI); an uncategorized ticket or one with no in-category playbooks shows none.
- Computing suggestions never busts the AI cache.

## 5. Functional requirements

| ID | Requirement | Stories |
|---|---|---|
| FR-001 | The backend fetches Intercom conversations directly from the official `api.intercom.io` REST API using a workspace Access Token, driven by a background poller and a manual `POST /tickets/sync`. Conversations already stored unchanged are skipped without a detail fetch (server-side skip-known). | US-001 |
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
| FR-026 | Resolution source is one of four stored values: `manual` (operator action), `intercom_closed` (sync auto-resolve), `non_actionable` (FR-037), or `ai_resolved` (AI auto-close confirmed under the operator's auto-resolve setting). | US-015, US-016, US-017 |
| FR-027 | The backend computes `resolution_chip_state` (`ai_resolved` \| `ai_reopened` \| `new_reply` \| `null`) server-side from settings + ticket + AI cache, and includes it in every ticket response. | US-016 |
| FR-028 | The system exposes `POST /tickets/{id}/resolve`, `POST /tickets/{id}/reopen`, `PATCH /tickets/{id}/ai-resolve`, and `POST /tickets/{id}/dismiss-chip`. `GET /tickets` accepts `?resolved=true\|false`; default excludes resolved tickets. | US-015, US-016 |
| FR-029 | Each ticket carries a per-ticket AI-resolve tri-state override (`true` / `false` / `null`); `null` means inherit `settings.ai_resolve_default`. | US-016 |
| FR-030 | Settings persist `ai_resolve_default` (bool) and `ai_resolve_confidence_threshold` (float 0..1); both are read and written through the existing settings endpoint. | US-016 |
| FR-031 | On each sync the backend performs a closure pass: it compares tracked-open ticket ids against the active conversation search and re-fetches any that have gone missing, then ingests them so `_upsert_ticket` auto-resolves via the open→closed transition (`resolved_source='intercom_closed'`). | US-017 |
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
| FR-042 | A ticket may be parked: `parked_at` + `parked_until` + `parked_reason` (`waiting_on_customer` \| `waiting_on_third_party` \| `waiting_internal` \| `other`), the trio XOR-constrained (all-set or all-null) and never co-existing with `resolved_at`; every resolve path clears it. Park is orthogonal to resolution and category. An optional free-text `parked_note` (≤200 chars, cleared with the trio) elaborates the reason — surfaced as a text box when the reason is `other`. The system exposes `POST /tickets/{id}/park`, `POST /tickets/{id}/unpark`, `POST /tickets/bulk/park`, `POST /tickets/bulk/unpark` (`until_at` must be future; bulk bounded by `MAX_BULK_IDS`). Parked tickets are excluded from the live category columns and surfaced via a parked-only filter chip; "ready to resume" (`parked_until ≤ now`) is derived on read, never stored. Parked state is operator-owned and survives ingest / re-sync untouched. | US-021 |
| FR-043 | The categorization call also returns `priority` (`low`\|`normal`\|`high`\|`urgent`), `sentiment` (`negative`\|`neutral`\|`positive`), and a list of short free-form `labels`. These facets are cached with the categorization result, reused on warm fetches, add no second AI call, and do not change the cache key. Pre-existing rows carry null facets / empty labels. | US-022 |
| FR-044 | Every ticket returned to a client carries the triage facets (`ai_priority`, `ai_sentiment`, `ai_labels`); the board surfaces a priority badge. | US-022, US-026 |
| FR-045 | Each ticket exposes an age derived from its last customer-visible message timestamp; the webapp tiers cards by configurable thresholds held in one constant. Presentation only — no stored state. | US-023 |
| FR-046 | The webapp is keyboard-operable for triage: `j`/`k` move card focus, `e` resolves the focused ticket, a digit key recategorizes it, `/` focuses search. No shortcut fires while a text input/textarea/contenteditable is focused. | US-024 |
| FR-047 | The webapp persists named filter presets ("saved views") locally over the facets the board already returns (category, age, urgency, resolution source). Applying a view sets the active filter; the backend is untouched. | US-025 |
| FR-048 | The webapp can order cards within a column by `ai_priority` (urgent→low), falling back to the existing recency / follow-up-due ordering within a band. The toggle is remembered locally; off restores the default order. | US-026 |
| FR-049 | The system exposes `GET /stats?window_days=N` returning, over the trailing window by `created_at`: total count, category breakdown, volume trend, resolution-source mix, and a time-to-resolve distribution + median. Aggregated server-side over the local store; no migration. | US-027 |
| FR-050 | The system accumulates per-(UTC-date, model) OpenRouter token usage and an estimated USD cost (tokens × model pricing), exposed via `GET /metrics`. In-process counters; reset on restart. | US-028 |
| FR-051 | Snippets are stored in a dedicated `snippets` table (title, body, soft-archive). The body is served verbatim with `{{variable}}` placeholders intact; substitution is client-side. CRUD + archive/restore endpoints. Operator-owned and durable (never content-keyed). | US-029 |
| FR-052 | Before submitting a bulk action the webapp previews the affected vs skipped counts from already-loaded ticket state and refuses selections over `MAX_BULK_IDS`. | US-030 |
| FR-053 | The categorization call requests a schema-enforced JSON object; a response that fails the schema degrades to the fallback for that ticket only (FR-007 unchanged). | US-031 |
| FR-054 | An opt-in model cascade categorizes with a configurable cheap model first and escalates to the strong model when cheap-model confidence is below `cascade_escalate_below` (or the cheap call fails/malformed). Off by default; reuses the categorization confidence as the escalation signal. | US-032 |
| FR-055 | An open, non-overridden ticket whose categorization confidence is below a configurable, calibrated `review_confidence_threshold` is surfaced in a webapp "needs review" lane — a view-layer split over the stored confidence, not a stored state. Writing an override clears it. The threshold is exposed on `GET /health`. | US-033 |
| FR-056 | The backend computes local, offline embeddings of customer-visible text (`parts[]` + title / operator notes; never `internal_notes[]`) on ingest and stores them in the local DB. Computing embeddings never busts the content-signature cache (FR-008). The layer is toggleable; disabled = the ingest hook is a no-op and dependent features degrade. | US-034 |
| FR-057 | When categorizing an uncached ticket, the system retrieves the nearest confirmed-override neighbours via embeddings and injects up to `fewshot_examples` of them into the prompt. Zero disables injection. Gated on the embedding layer. | US-035 |
| FR-058 | The system exposes `POST /playbooks/draft-reply` returning an ephemeral RAG-grounded customer reply built from the nearest resolved tickets (customer-visible content only) + the ticket's effective-category playbooks, reporting `grounding_ticket_ids` + `playbook_ids`. Never reads `internal_notes[]` (invariant #4); 503 when AI is unconfigured. | US-036 |
| FR-059 | An offline periodic background job clusters resolved tickets' embeddings (gated on the embedding layer), labels each cluster with c-TF-IDF top terms over customer-visible text only, flags outliers rather than force-fitting, and persists a snapshot. `GET /clusters` reads the snapshot; `POST /clusters/recompute` forces a refresh. Never touches `ai_cache` (invariant #6). | US-037 |
| FR-060 | `GET /clusters/gaps` ranks recurring-issue clusters whose dominant effective category (override beats AI, invariant #13) has no active playbook, most-recurring-first, naming the category to write a playbook for. Read-only local logic over the cluster snapshot + playbooks. | US-038 |
| FR-061 | `GET /playbooks/suggested?ticket_id=` ranks the ticket's effective-category playbooks by embedding similarity to its customer-visible text, most-relevant-first. Ephemeral; empty when uncategorized or no in-category playbooks; never busts the cache. | US-039 |
| FR-062 | A non-actionable ticket may carry a structured `non_actionable_kind` (`auto_reply`\|`thanks`\|`spam`\|`out_of_office`\|`other`, nullable) on `tickets` + `ai_cache`. The categorization call returns it (only for the `non_actionable` verdict; null otherwise; missing/invalid → `other`); ingest stamps it on AI auto-mark, manual marks leave it null; every reopen path clears it (XOR with `resolved_source='non_actionable'`). Surfaced on `TicketSchema` (not `HydratedTicket`); the webapp filters the non-actionable view by it and both surfaces label the chip. | US-019 |

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
| NFR-009 | External-call latency is sampled into in-process histograms; `GET /metrics` exposes per-key p50 / p95 / max over a bounded sample window. Single-operator scope — not a metrics exporter. |
| NFR-010 | The Intercom Access Token is a server-side secret loaded from the local config file (alongside the AI key); it never reaches the webapp/extension bundle, logs, or error responses. A missing token is reported by `/health`, not fatal at startup. |

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

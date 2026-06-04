# Intercom Triage — Feature Knowledge Base

> **The canonical catalog of what this product does.** Every shipped feature,
> grouped by capability area, with where it lives in code and which surface(s)
> expose it. Built so any future session has instant context on the feature set
> without re-deriving it from code.
>
> Orientation + architecture: [`PROJECT.md`](./PROJECT.md). Requirements/IDs:
> `spec.md` (US-*/FR-*/NFR-*). Per-change rules + the 14 invariants: root
> [`CLAUDE.md`](../CLAUDE.md). When this catalog and code disagree, code wins —
> fix this file.

## How to read an entry

`**Feature** — what it does. (surface · code anchor · spec IDs / invariants)`

- **surface**: `backend` (HTTP) · `ai` (OpenRouter/embeddings) · `webapp` · `extension` · `both` (webapp+extension)
- **status**: everything below is **shipped to `main`** unless tagged **[OPEN]**.
- Counts: ~66 backend endpoints · 20 AI/ML features · ~50 user-facing UI features.

---

## A. Categorization & taxonomy

The core loop: ingest → AI categorize against the operator's taxonomy → board.

- **AI ticket categorization** — classifies each ingested ticket into one existing category, one pending proposal, or a brand-new proposal, against the operator's active taxonomy. (ai · `ai/pipeline.py:categorize_many` + `services/tickets.py:ingest_tickets` · US-002/US-009, FR-004/FR-015, inv #4/#6)
- **Structured JSON output** — the categorization call uses `response_format: json_object`; `SYSTEM_PROMPT` fully specifies the output shape and `parse_response` extracts + validates it defensively, so a malformed response degrades per-ticket and never aborts the batch. (A strict `json_schema`/`oneOf` form was tried but the default Anthropic model rejects it — `oneOf` and numeric `min`/`max` are unsupported — so it 400'd every call into fallback; reverted 2026-06-04.) (ai · `ai/prompt.py:CATEGORIZATION_RESPONSE_FORMAT`, `ai/pipeline.py:parse_response` · US-031/FR-053)
- **New-category proposals + dedup** — proposes a new category when nothing fits; dedupes by normalized signature so repeats reuse one proposal id. (ai/backend · `ai/pipeline.py:resolve`, `models.py:CategoryProposal` · US-009/US-010, FR-015/FR-016)
- **Rejected-signature suppression** — a rejected proposal name is remembered so the AI never re-proposes it. (backend · `services/proposals.py:reject_proposal`, `models.py:RejectedProposalSignature`)
- **Manual category override** — operator reassigns a ticket's category; the override beats AI while `tickets.updated_at ≤ override.set_at`. (backend/webapp · `PATCH /tickets/{id}/category` → `services/tickets.py:set_override` · US-? FR-, inv #11)
- **Category CRUD** — create, rename, recolor, reorder active categories. (backend/webapp · `POST /categories`, `PATCH /categories/{id}` · T018)
- **Category archive (sweep to fallback)** — archiving a category moves its tickets + overrides to the fallback in one transaction. (backend/webapp · `POST /categories/{id}/archive` · T018/T019)
- **Category merge** — absorb one category's tickets into another, then archive the source. (backend/webapp · `POST /categories/{src}/merge-into/{dst}` · T020)
- **Proposal review (approve / merge / reject)** — promote a proposal to a category, merge it into an existing one, or reject it. (backend/webapp · `POST /proposals/{id}/{approve|merge-into|reject}` · T021–T024)
- **Seven seeded default categories** — first boot seeds Urgent, Bug, Feature Request, Question, Billing, Complaint, Other + the singleton settings row. (backend · `models.py:DEFAULT_CATEGORIES`/`init_db` · inv #12)

## B. Resolution & workflow state

- **Manual resolve** — mark a ticket resolved (`resolved_source='manual'`); clears any parked state. (both · `POST /tickets/{id}/resolve` → `services/resolution.py:resolve`)
- **Reopen (atomic)** — clears `resolved_at` + `resolved_source` + `non_actionable_kind` + stamps `resolution_cleared_at` in one transaction. (both · `POST /tickets/{id}/reopen` · inv #11)
- **Mark non-actionable** — resolve as a non-actionable sub-state (spam/thanks/auto-reply/out-of-office/other); its own board column / popup tab. (both · `POST /tickets/{id}/non-actionable` · US-019/FR-037, inv #10)
- **Intercom-closed auto-resolve** — the backend closure pass (in `run_sync_cycle`) detects open→closed in Intercom; ingest stamps `resolved_source='intercom_closed'`. (backend · `services/sync.py`, `services/tickets.py:_upsert_ticket`)
- **AI auto-resolve** — under the operator's toggle + confidence threshold, a high-confidence `resolved`/`non_actionable` verdict auto-resolves (`resolved_source='ai_resolved'`); never overrides an existing resolution. (ai/backend · `services/tickets.py:_maybe_auto_resolve_from_ai` · US-016, FR-026/FR-029/FR-030, inv #10)
- **Per-ticket AI-resolve toggle (tri-state)** — `null` inherits the global default; `true`/`false` override per ticket. (both · `PATCH /tickets/{id}/ai-resolve` → `services/resolution.py:set_ai_resolve`)
- **Resolution chip + dismiss** — server-computed advisory chip (`ai_resolved`/`ai_reopened`/`new_reply`); dismissible until the customer-visible thread advances. (backend/webapp · `services/tickets.py:_chip_state`, `POST /tickets/{id}/dismiss-chip`, `ResolutionChip.vue` · US-016/FR-027)
- **Parked / snoozed state** — defer a ticket "waiting on customer / third party / internal / other" with a wake time + optional note; XOR-locked trio, never co-resolved, "ready to resume" derived on read (no scheduler). (both · `POST /tickets/{id}/{park|unpark}` → `services/resolution.py`, `ParkMenu.vue` · roadmap 4.1/T106, inv #14)
- **Operator title/summary edits (sticky)** — edited title + summary survive re-syncs; empty value clears the edit. (backend/webapp · `PATCH /tickets/{id}` → `edit_ticket` · inv #8)

## C. Bulk operations (cap 200/request, per-id ok/failed)

Every bulk endpoint returns `{ok_ids, failed:[{id, reason}]}` — a per-id failure never aborts the batch. Cap = `MAX_BULK_IDS=200` (inv #9).

- **Bulk resolve / reopen** — (both · `POST /tickets/bulk/{resolve|reopen}` → `services/bulk.py`)
- **Bulk recategorize** — assign one category to N tickets via overrides; atomically reopens resolved rows (drag-out). (both · `PATCH /tickets/bulk/category`)
- **Bulk mark non-actionable** — (both · `POST /tickets/bulk/non-actionable`)
- **Bulk park / unpark** — park N until a wake time with reason + note; unpark N. (webapp · `POST /tickets/bulk/{park|unpark}`)
- **Bulk dismiss chip** — (both · `POST /tickets/bulk/dismiss-chip`)
- **Bulk follow-up set / clear** — apply or clear one follow-up across N tickets. (webapp · `PUT|DELETE /followups/bulk`)
- **Multi-select + bulk drag** — Cmd/Ctrl-click toggles selection, Shift-click range within a column, dragging one selected card moves the whole set. (webapp · `selection.ts`, `Column.vue`, `BulkActionBar.vue`)
- **Pre-flight diff** — "N will resolve, M skipped" on hover, with an over-cap warning past 200. (webapp · `utils/bulkPreview.ts` · US-030/FR-036)

## D. Follow-ups & alarms

- **Set / snooze / clear follow-up** — per-ticket reminder (`due_at` + reason); snooze reschedules + re-arms; clear is idempotent. (both · `PUT /followups/{id}`, `POST /{id}/snooze`, `DELETE /{id}` · T046)
- **Mark-fired guard** — a rung alarm is flagged so a client reload doesn't re-ring it. (backend · `POST /followups/{id}/mark-fired`)
- **Live countdown chip (1 Hz)** — per-card "F/U in 15m" → "due now" tick. (both · `TicketCard.vue`, `popup.js`)
- **Alarm banners** — stacked top-right banners on fire: open / snooze (15m, 1h) / dismiss, with an audio ping (gated by `mute_alarms`) and desktop notification (gated by `tweaks.desktopNotifications`). (both · `AlarmBanners.vue`, `popup.js`)
- **Follow-ups page (5 time buckets)** — overdue / within 1h / today / later / fired; cards re-bucket live. (webapp · `FollowupBoard.vue`/`FollowupColumn.vue`)
- **Timer-triggered follow-up from a note** — adding a note entry with `timer_min` upserts the follow-up in the same transaction. (backend · `services/note_entries.py:add_entry`)

## E. Notes & attachments

- **Per-ticket note (legacy)** — single free-text body; empty body deletes the row. (backend/webapp · `PUT /notes/{id}`, `TicketLegacyNote.vue` · T047)
- **Time-tabled note entries** — append-only investigation log with optional timer + reason; soft-delete. (backend/webapp · `POST|DELETE /notes/entries`, `TicketEntryTimeline.vue`)
- **Attachments** — multipart upload, content-addressed dedup by sha256, image thumbnails (256px WebP), soft-delete + nightly GC of orphaned bytes. Raw bytes served `attachment`-disposition + `nosniff` for non-images (XSS defense). (backend/webapp · `POST /attachments`, `GET /{id}/raw|thumb`, `attachments.py`, `AttachmentDropzone.vue`)

## F. Durable operator knowledge

Survives ingest / re-sync; never content-signature-keyed (inv #13).

- **Playbooks** — category-scoped response recipes: list (by ticket's effective category / by category / all), create, edit, archive, restore; capture from the flyout. (backend/webapp · `/playbooks*`, `PlaybooksPage.vue`/`TicketPlaybooks.vue`)
- **AI-drafted playbook** — generate a 3–6 step recipe from a resolved ticket (customer-visible parts + operator notes only). (ai · `POST /playbooks/draft` · US-020/FR-040, inv #4)
- **Snippets** — global canned replies with `{{variable}}` placeholders (client-side substitution); CRUD + archive/restore. (backend/webapp · `/snippets*`, `SnippetsPage.vue` · roadmap 1.5)

## G. AI & ML (local-first, offline embeddings)

All enforce inv #4 (never feed/embed `internal_notes`) and inv #6 (embeddings live in a separate store, never bust the content-signature cache). Heavy features are opt-in via config flags.

- **Content-signature cache** — categorization cached on the last customer-visible part timestamp, so teammate notes/assignments don't re-run the AI. TTL `CACHE_TTL_SECONDS` (300s). (ai · `services/tickets.py:_content_signature`, `services/cache.py` · FR-008, inv #6)
- **Fallback never cached** — AI-unavailable/garbage → per-ticket fallback (catch-all, conf 0); never cached (would pin the ticket). (ai · `ai/pipeline.py:_fallback`, ingest guard · FR-007, inv #7)
- **Multi-facet triage** — same call returns priority (low/normal/high/urgent), sentiment, and ≤3 labels; cached with the categorization. (ai · `ai/pipeline.py:_parse_triage` · US-022/FR-043/FR-044)
- **Non-actionable kind inference** — AI tags spam/thanks/auto-reply/out-of-office/other on a non-actionable verdict. (ai · `ai/pipeline.py:_parse_non_actionable_kind` · US-019/FR-037/FR-062, inv #10)
- **Model cascade [opt-in]** — cheap model first (Haiku), escalate to the strong model (Sonnet 4.5) below the confidence bar. Off by default (`cascade_enabled`). (ai · `ai/pipeline.py:_call`, `config.py` · US-032/FR-054)
- **Confidence + needs-review lane** — low-confidence (< `review_confidence_threshold`, 0.65) open/non-overridden tickets surface in a review lane; an override clears them. (ai/webapp · `config.py`, `tickets.ts:needsReviewTickets` · US-033/FR-055)
- **Local embedding layer** — `all-MiniLM-L6-v2` (384-dim, CPU, sentence-transformers) embeds customer-visible text into a `sqlite-vec` table; lazy-loads (~80 MB). Toggle `embeddings_enabled`. (ai · `ai/embeddings.py` · US-034/FR-056, inv #4/#6)
- **Few-shot categorization** — injects the k nearest confirmed-override neighbours as in-context examples (`FEWSHOT_EXAMPLES`=3). (ai · `ai/fewshot.py` · US-035/FR-057)
- **RAG draft replies** — ephemeral reply grounded in the current ticket + k nearest resolved tickets + effective-category playbooks; cites precedent ids; never persisted. (ai/webapp · `POST /playbooks/draft-reply`, `TicketDraftReply.vue` · US-036/FR-058)
- **Recurring-issue clustering** — offline HDBSCAN over resolved-ticket embeddings, c-TF-IDF labels, outliers excluded; periodic background job + on-demand recompute. (ai · `ai/clustering.py`, `POST /clusters/recompute` · US-037/FR-059)
- **Playbook-gap detection** — ranks recurring-issue clusters whose dominant effective category has no active playbook ("what should I build a playbook for"). (ai/backend · `services/clusters.py:rank_gaps`, `GET /clusters/gaps` · US-038/FR-060)
- **Playbook auto-match** — ranks a ticket's effective-category playbooks by embedding similarity on open. (ai · `GET /playbooks/suggested`, `services/playbooks.py:suggest_playbooks` · US-039/FR-061)
- **Operator notes as embedding context** — local operator notes enrich embeddings/RAG queries (never `internal_notes`). (ai · `ai/embeddings.py:build_embedding_text`)
- **OpenRouter client w/ retry+jitter** — exponential backoff + jitter on 429/5xx/transient, honors `Retry-After`, records token usage. (ai · `clients/openrouter.py` · plan §7/NFR-006)

## H. Insights & observability

- **Stats dashboard** — category breakdown, volume trend (gap-filled per-day), resolution-source mix, time-to-resolve distribution; trailing window. (backend/webapp · `GET /stats`, `StatsPage.vue` · roadmap 1.3)
- **Token / cost meter** — per-model token usage + estimated USD spend (today + per lookback window). (backend/webapp · `GET /metrics` usage buckets, `pricing.py`, `DrawerCostSection.vue` · roadmap 1.4/T102/T148)
- **Metrics + latency histograms** — in-process counters + p95 latency over the ingest/categorize path. (backend · `metrics.py`, `GET /metrics` · T043/T160/R.4)
- **Clusters list** — recurring-issue snapshot (label, top terms, size, members), largest first. (backend/webapp · `GET /clusters`)
- **Health / degraded boot** — version, model, `openrouter_configured`, `missing_secrets`, review threshold; degraded (no key) still boots. (backend · `GET /health` · T005)

## I. Board & triage UX (webapp)

- **Kanban board** — category + pending-proposal columns; optional priority sort + follow-up-due pinning; hide-empty-categories toggle. (webapp · `Board.vue`/`Column.vue` · roadmap 1.2)
- **Resolved / non-actionable / parked split** — fixed resolved column, separate non-actionable column with per-kind filter chips, parked surfaced via a filter chip with a "ready to resume" count. (webapp · `ResolvedColumn.vue`/`NonActionableColumn.vue`, `Topbar.vue`)
- **Ticket card** — mono id + age, aging stripe (fresh→critical color by time since last customer message), title/summary, meta (customer, priority/sentiment chips, message count, confidence%), tag row (parked/closed/labels/awaiting/notes/follow-up/resolution chip). (webapp · `TicketCard.vue`, `utils/aging.ts` · US-023/roadmap 0.3)
- **Ticket flyout** — 10 sections: header + title/summary edit, conversation thread (customer/admin/internal-note lanes), user data, category picker, follow-up, playbooks, RAG draft reply, resolution controls, notes timeline, attachments. (webapp · `TicketFlyout.vue` + `components/ticket/*`)
- **Keyboard triage** — `j`/`k` navigate, `e` resolve, `1`–`9` recategorize, `r` refresh, `/` search, `←/→` scroll, `Esc` clear/close. (webapp · `useKeyboardTriage.ts`, `App.vue` · US-024/NFR-007/roadmap 0.4)
- **Full-text search** — filters visible tickets by title + parts + summary; narrows columns live. (webapp · `tickets.ts:visibleTickets`, `Topbar.vue`)
- **Saved views / smart filters** — persisted filter presets (e.g. "urgent + unresolved + >4h"); create/edit/delete in the drawer. (webapp · `savedViews.ts`, `DrawerSavedViewsSection.vue` · US-025/roadmap 1.1)
- **Optimistic updates + auto-sync** — every mutation snapshots→mutates→rolls back on failure; a silent background refresh (configurable interval) is guarded against in-flight mutations (race fix R.2). (webapp · `tickets.ts:mutating`/`mutationGen`, `App.vue`)
- **Display tweaks** — dark mode, accent color, density (normal/compact/comfy), show-summary, show-confidence; client-only `localStorage`. (webapp · `tweaks.ts`, `DrawerDisplaySection.vue`)
- **Extension callout** — empty state ("operator hasn't synced") vs backend-unreachable error; never mocks data. (webapp · `ExtensionCallout.vue`)
- **Admin pages** — Categories (CRUD/recolor/reorder/archive/merge), Proposals (approve/merge/reject), Playbooks, Snippets, Stats. (webapp · `CategoriesPage.vue` etc.)
- **Settings drawer (7 sections)** — Display, Filters (lookback/states/keywords/hide-empty), AI (categorize toggle, auto-resolve, confidence threshold), Notifications (mute alarms, desktop notifs), Cost meter, Sync interval, Saved views. (webapp · `SettingsDrawer.vue` + `settings/*` · T027)

## J. Intercom ingestion (backend)

- **Official API client** — async client over `api.intercom.io` with a workspace Access Token: conversation search (cursor-paginated), detail fetch, TTL-cached contact fetch; retry + rate-limit (`X-RateLimit-Reset`) aware. (backend · `clients/intercom.py` · inv #1)
- **Normalizer** — maps the official payload to `HydratedTicket`: `part_type` (`comment`→`parts[]`, `note`→`internal_notes[]`, events skipped), `source` as the first part, priority coercion, HTML strip, `[attachment: …]` fallback (R.5), customer panel fields from the contact. (backend · `services/intercom_normalizer.py` · inv #2/#3/#4, R.1/R.5)
- **Sync cycle** — `run_sync_cycle`: server-side skip-known (internal `get_sync_state`), search → detail/contact fetch for changed/new, closure pass for open→closed, then the existing cache-aware ingest. (backend · `services/sync.py`)
- **Poller + manual sync** — background poller (interval-gated, default off) + `POST /tickets/sync` (503 without a token); returns `{received, categorized, skipped_known, closed_detected}`. (backend · `main:_intercom_poll_loop`, `routers/tickets.py`)

## K. Extension (Chrome MV3 popup)

- **Popup mini-board** — category/proposal/resolved/non-actionable/parked tabs with counts; same taxonomy as the webapp. Read-only over the backend (no Intercom access). (extension · `popup.js`)
- **Popup per-ticket actions** — move category, resolve, reopen, non-actionable, park, unpark; follow-up countdown chip + due banner with snooze. (extension · `popup.js`)
- **Refresh** — reload the stored board from the backend. (extension · `popup.js`)
- **Background badge poll** — optional interval poll (off by default) that badges the toolbar with the Urgent count from the backend board (no Intercom fetch). (extension · `background.js`)

## L. Platform & ops

- **Naive-UTC-in-DB / Z-on-wire** — Pydantic `UTCDatetime`/`NaiveUTCDatetime` enforce the timestamp contract JS clients depend on. (backend · `schemas.py` · inv #5)
- **Singleton settings** — one `Settings` row, `CHECK (id = 1)`, inserted on first boot. (backend · `models.py` · inv #12)
- **Forward-only migrations** — Alembic chain `0001…0020`. (backend · `alembic/versions/`)
- **Secret-scan guard** — pre-commit file-name + content scan (gitleaks or regex fallback); allowlists `docs/_archive/` + test/fixture paths. (ops · `.githooks/pre-commit`, `.gitleaks.toml`)
- **One-command dev launcher** — `scripts/dev.ps1` boots backend + webapp in a Windows Terminal split-pane. (ops · `scripts/dev.ps1`)
- **Invariant guard hook** — `scripts/check-invariants.ps1` greps for cross-package invariant violations on edits. (ops)

---

## Open backlog (not yet shipped)

- **[OPEN] Webhook + SSE live updates** — `conversation.user.created`/`replied` → push to webapp + popup instead of poll-on-open. The heaviest deferred feature. (roadmap 4.3 / T100)
- **[OPEN] Bulk actions in the extension popup** — mirror the webapp bulk bar; deferred for popup ergonomics. (roadmap 4.4 / T105)

---

*Maintenance: when you ship a feature, add a one-line entry here in the right
area and flip any `[OPEN]` tag. Keep entries one line; deep design rationale
belongs in `docs/superpowers/specs/`, requirements in `spec.md`.*

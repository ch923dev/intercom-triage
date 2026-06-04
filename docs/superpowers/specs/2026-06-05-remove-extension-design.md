# Design — Remove the Chrome extension (collapse to a two-package repo)

**Date:** 2026-06-05 · **Status:** approved (design) · **Author:** Christian + Claude
**Type:** scope-reduction / cross-package removal · **Spec impact:** spec → v1.9

---

## 1. Context

The repo ships three packages: `backend/` (FastAPI ingestion + API), `webapp/`
(Vue 3 Kanban board), and `extension/` (Chrome MV3 popup mini-board + toolbar
badge).

PR #8 (`7647ee2`, "backend-direct Intercom ingestion via Access Token") moved
the entire Intercom ingestion path server-side. The backend now polls
`api.intercom.io` with a workspace Access Token; the extension was stripped of
Intercom access (T165) and reduced to a **read-only** mini-board + badge over
the backend's `GET /tickets`.

Since that pivot the extension is a pure convenience surface — it duplicates the
webapp's board in a popup and badges the toolbar with the Urgent count. It is
**not** an ingestion path and shares its entire API surface with the webapp.

## 2. Goal & motivation

**Cut maintenance and scope.** Drop the third package so there is no third stack
to keep coherent across every invariant change, schema change, and doc edit. The
badge + popup convenience is not worth the upkeep cost; the webapp on `:5173`
covers the workflow.

This is a deliberate charter change: the project goes from three packages to
two. The root `CLAUDE.md` "three packages, three stacks, intentionally" guardrail
is rewritten accordingly.

## 3. Non-goals

- No behavior change to the backend ingestion path or the webapp board.
- No new feature. This is removal-only plus one corrective UI replacement
  (the empty-state, see §6).
- Not bundled: the other repo-hygiene items (gitignore `canvas.json`, the
  `.claude/settings.json` hook removal, the PROJECT.md `v1.7 → v1.8` stale
  reference). Those are tracked separately.

## 4. Feasibility (why this is a clean cut)

A footprint scan confirmed the extension is **fully isolated**:

- **No backend code is extension-only.** Every endpoint the extension calls
  (`GET /tickets`, `/categories`, `/followups`, `/settings`,
  `PATCH /tickets/{id}/category`, `POST /tickets/{id}/{resolve,reopen,non-actionable}`,
  `PUT /followups/{id}`, `POST /followups/{id}/mark-fired`) is also called by the
  webapp. The only backend coupling is one CORS allowance.
- **No shared code, no monorepo build, no codegen.** Deleting `extension/`
  cannot ripple into the webapp or backend.
- **One webapp coupling:** `ExtensionCallout.vue`, which is *already stale* — its
  empty-state copy still claims "the Chrome extension is the only path that
  reaches Intercom — the backend has no Access Token" and instructs the operator
  to load the extension and press **Sync**. Both statements are false since
  PR #8. Removing it fixes a live bug.

## 5. Approach decision

Chosen: **A — clean delete.** `git rm extension/`, strip it from the active
docs/contract/invariants, replace the stale empty-state, drop the CORS allowance
and extension-only tooling. Git history preserves the extension for resurrection;
a spec changelog entry + one `tasks.md` tombstone record the decision.

Rejected:
- **B — archive to `docs/_archive/`.** Keeps ~1,500 LOC of dead code in-tree and
  a heavier doc footprint. Git already gives recoverability, so an archive copy
  is redundant and fights the cut-scope goal.
- **C — deprecate in place.** Leaves the code and all invariants standing; cuts
  no actual scope. Contradicts the motivation.

## 6. Change inventory

### 6.1 Delete (`git rm`)

- `extension/` (whole dir): `manifest.json`, `popup.{html,js,css}`,
  `background.js`, `api.js`, `package.json`, `CLAUDE.md`, `README.md`,
  `icons/` (~1,500 LOC).
- `webapp/src/components/ExtensionCallout.vue` (replaced — see §6.3).
- `.claude/commands/qa-extension.md`.

### 6.2 Backend / tooling code edits (the only functional changes)

- `backend/app/main.py` — remove the CORS `allow_origin_regex=r"chrome-extension://…"`
  entry. Webapp origins (`localhost:5173` / `127.0.0.1:5173`) stay. This tightens
  CORS.
- `backend/CLAUDE.md` — drop the `+ chrome-extension://` note on the `main.py`
  CORS line.
- `scripts/check-invariants.ps1` — delete the extension-only guard rules (the
  manifest `host_permissions` widening check and the `importScripts` check). Keep
  the invariant-#1 backend-ownership check.
- `scripts/dev.ps1` — drop the "load the extension manually" comment (no
  functional change; the launcher only starts backend + webapp).
- `.claude/commands/qa-all.md` — remove the extension leg if it chains one.
- `.gitignore` — drop any `extension/dist|build` entries if present.

### 6.3 Empty-state replacement (corrective)

`ExtensionCallout.vue` is dual-mode: a top discovery **banner** ("install the
extension") and the **empty-board** placeholder. Both are removed. Replace only
the empty-board with a small native component (e.g. `EmptyBoard.vue`) built from
`DESIGN.md` tokens (`var(--*)`, no hardcoded hex/px):

- Copy, accurate to the current architecture: *"No tickets yet — run a sync
  (`POST /tickets/sync`) or enable the backend poller. If the board stays empty,
  check `/health` (`intercom_configured`)."*
- `webapp/src/App.vue` — remove the `ExtensionCallout` import and both usages;
  mount `EmptyBoard` on `tickets.isEmpty`. Drop the banner usage entirely.
- `webapp/CLAUDE.md` "Data-flow pivot" section — update the
  `ExtensionCallout mode="empty"` reference and the "copy may still mention the
  extension" note.

### 6.4 Invariants (count stays 14 — none are removed, three lose a clause)

In root `CLAUDE.md` "Cross-package invariants" (and the PROJECT.md §7 index):

- **#1** — drop "**The extension no longer touches Intercom** — it is a read-only
  mini-board + badge … the extension `ember/` path is gone." Keep "Backend owns
  Intercom ingestion via an Access Token."
- **#10** — drop "/ its own popup tab (extension)"; keep "its own Kanban column
  (webapp)".
- **#14** — drop "so the extension's `normalizeConversation` does not carry
  them"; keep the `HydratedTicket`/board-state point.
- **#2** — the "produced by the backend normalizer … not the extension" aside
  stays true; optionally tidy the wording.

### 6.5 Root `CLAUDE.md` prose

Sub-package guide link; repo-map tree row; the quality-gates table row
(extension); "Scope guardrails" ("Three packages, three stacks, intentionally" →
two; the `chrome-extension://…` localhost line); the "Don't add a SECOND Intercom
integration … don't give the extension … Intercom access" Don't; any
parallel-sessions/worktree references to the extension.

### 6.6 `docs/PROJECT.md`

§2 three-package table → two; §3 architecture diagram + the "popup mini-board"
reader arrow; §5 stack table extension row; §10 backlog (T100 retarget, T105
drop); §11 gates table row; the "Extension is loaded once manually …" install
note; glossary entries naming the popup.

### 6.7 `docs/FEATURES.md`

- Legend (line 17): drop `extension` and `both` from the surface list.
- Retag the ~12 `(both · …)` entries to `(webapp · …)` (resolution, reopen,
  non-actionable, ai-resolve, park, bulk resolve/reopen/non-actionable/dismiss,
  follow-up set/snooze/clear).
- Drop the `popup.js` code anchors on the live-countdown chip and alarm-banners
  entries.
- Delete **§K (Extension)** entirely (popup mini-board, per-ticket actions,
  refresh, badge poll).
- Drop the `[OPEN]` "Bulk actions in the extension popup" backlog line; retarget
  the SSE line to webapp-only.

### 6.8 Contract docs (source of truth — changelog convention)

`docs/contract/spec.md` → **bump to v1.9** with a "Changes from v1.8" entry
recording the extension removal. Edits:

- §2 Scope (line 29): drop "and a Chrome extension surface" and the false
  "Intercom integration via the operator's logged-in browser session
  (extension-driven; no API token)" clause.
- §3 Personas (line 35): drop "They sign in to Intercom in Chrome, install the
  extension".
- **US-006 (lines 80–88) — delete the whole "Genuine mini-board in the Chrome
  extension" story.**
- Line 104: "Neither the webapp nor the extension ever receives the credentials"
  → "The webapp never receives the credentials."
- Line 150: alarm banner — drop "and at the top of the popup".
- Line 201: the closure pass is backend (`run_sync_cycle`), not "the extension's
  sync flow" — correct this stale line.
- Line 245: non-actionable — drop "their own popup tab"; keep the webapp column.
- NFR-010 (line 550): "never reaches the webapp/extension bundle" → "never
  reaches the webapp bundle".
- Line 562: delete the "Extension popup depth … callout for installing the
  extension" note.
- (Historical changelog lines 7/17 stay — they record past versions.)

`docs/contract/plan.md`:

- Stack table (line 32): delete the Extension row.
- Deploy (line 36): drop "extension side-loaded".
- Line 48: delete the "The Chrome extension is a Manifest V3 extension …"
  paragraph.
- Line 324: keep "ingestion is entirely backend-side"; drop the extension clause.
- Alarm section (lines 366/368/384): "webapp + popup" → "webapp"; drop "lets the
  popup raise alarms" and "Webapp + popup must match".
- Line 477: drop the "popup ergonomics too cramped for multi-select" rationale.
- Lines 546/585: "both surfaces GET /settings" → the webapp.
- Line 555: delete the `# extension: chrome://extensions → load unpacked` line.
- Lines 619–620: drop "Extension popup gains …".
- Lines 709–710: drop the "(the extension/`HydratedTicket` shape is untouched …"
  parenthetical.
- (Historical changelog line 11 stays.)

`docs/contract/tasks.md`:

- **T100 (line 208)** — "push channel (SSE) to webapp and extension" → "to the
  webapp".
- **T105 (line 212)** — delete (bulk actions in the extension popup; obsolete).
- Add one **tombstone task** (next free `Txxx`, e.g. `T166`): "Remove the Chrome
  extension entirely — delete `extension/`, the CORS `chrome-extension://` regex,
  `ExtensionCallout.vue`, `qa-extension`, and all active-doc references; replace
  the empty-state with `EmptyBoard.vue`. Continuation of T165. inv #1/#10/#14."
- Phase 7 + the other completed extension tasks (T039–T053, T070/T071, T094,
  T106, T165) are a historical ledger of shipped work — **leave them**; they
  record what happened.

### 6.9 `README.md` (root)

Title ("Backend + webapp + Chrome extension" → "Backend + webapp"); the layout
tree; prerequisites; quickstart §3 (extension install); the dev-launcher note.

## 7. Verification

- `qa-backend` — CORS change (`ruff` + `mypy` + `pytest`).
- `qa-webapp` — `EmptyBoard` added, `ExtensionCallout` removed
  (`lint` + `format:check` + `typecheck` + `vitest` + `build`). No extension gate
  remains.
- `check-invariants.ps1` still runs green after the rule deletions.
- Final grep sweep across the repo: `extension`, `chrome-extension`, `popup`,
  `\bMV3\b`, `badge`, `mini-board` → **zero** hits outside `docs/_archive/`, the
  historical changelog lines, the spec v1.9 changelog entry, and the `tasks.md`
  tombstone. ("badge" survives only as the webapp *priority badge* on cards —
  that is not the extension toolbar badge and stays.)

## 8. Sequencing (one PR — cross-package, per repo invariant)

Branch `refactor/remove-extension` (optionally an isolated worktree per the
parallel-session doctrine). Order:

1. `git rm extension/` + delete `qa-extension`.
2. Backend CORS + tooling edits (§6.2).
3. Empty-state replacement (§6.3) — `EmptyBoard.vue` + `App.vue` + webapp
   CLAUDE.md.
4. Invariants + root `CLAUDE.md` + PROJECT.md + FEATURES.md (§6.4–6.7).
5. Contract docs spec/plan/tasks (§6.8) — including the spec v1.9 bump.
6. README (§6.9).
7. Grep sweep (§7) → fix stragglers.
8. `qa-backend` + `qa-webapp` green.

## 9. Rollback

The extension lives in git history at `cc5176b` and earlier; `git revert` of the
removal commit (or `git checkout <sha> -- extension/`) restores it. The CORS
regex and `ExtensionCallout.vue` come back with it. No data migration is
involved — the extension stored nothing server-side beyond `chrome.storage.local`
on the operator's machine.

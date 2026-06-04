# Remove the Chrome Extension — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete the `extension/` package and every reference to it, collapsing the repo from three packages to two (backend + webapp), while replacing the stale extension-oriented empty-state with a backend-oriented one.

**Architecture:** The extension is fully isolated — no backend code is extension-only, no shared code, no build coupling. Removal is `git rm extension/` plus one CORS line, one Vue component swap, deletion of three dead invariant-guard rules, and doc/contract edits. Design record: `docs/superpowers/specs/2026-06-05-remove-extension-design.md`.

**Tech Stack:** FastAPI (backend), Vue 3 + Pinia + Vitest (webapp), PowerShell tooling, Markdown docs.

**Branch:** `refactor/remove-extension` (already created; the design doc is committed on it).

**Ground rules:**
- One PR, ordered tasks, frequent commits.
- After the code tasks, run `qa-backend` (`ruff check app tests && ruff format --check app tests && mypy app && pytest -q` from `backend/` with `.venv` active) and `qa-webapp` (`npm run lint && npm run format:check && npm run typecheck && npm test && npm run build` from `webapp/`).
- Commit messages: conventional, normal English (not caveman).
- Line numbers below are point-in-time anchors from 2026-06-05. If a file shifted, locate by the quoted text, not the number.

---

### Task 1: Delete the extension package + its QA skill

**Files:**
- Delete: `extension/` (entire directory)
- Delete: `.claude/commands/qa-extension.md`

- [ ] **Step 1: Confirm nothing outside `extension/` imports from it**

Run: `git grep -n "extension/" -- webapp backend | grep -iv "chrome://extensions\|extension is\|extension/CLAUDE\|extension/manifest\|extension-ingested\|extension callout\|extension or another"`
Expected: no source `import` statements that resolve into `extension/`. (Hits are doc/comment strings only — handled in later tasks.) The webapp never imports extension modules.

- [ ] **Step 2: Remove the directory and the QA skill**

```bash
git rm -r extension
git rm .claude/commands/qa-extension.md
```

- [ ] **Step 3: Verify the working tree**

Run: `test ! -d extension && echo GONE`
Expected: `GONE`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: delete the Chrome extension package + qa-extension skill"
```

---

### Task 2: Drop the extension CORS allowance + dead invariant-guard rules

**Files:**
- Modify: `backend/app/main.py:287-295`
- Modify: `backend/CLAUDE.md` (Layout block, the `main.py` line)
- Modify: `scripts/check-invariants.ps1:61-104`

- [ ] **Step 1: Remove the `chrome-extension://` CORS regex in `backend/app/main.py`**

Replace:

```python
    # CORS — webapp on 5173 + Chrome extension origin.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_origin_regex=r"chrome-extension://[a-z]{32}",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

with:

```python
    # CORS — webapp on 5173.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
```

- [ ] **Step 2: Fix the CORS note in `backend/CLAUDE.md`**

Replace the Layout line:

```
├── main.py              lifespan + create_app + CORS (localhost:5173 + chrome-extension://)
```

with:

```
├── main.py              lifespan + create_app + CORS (localhost:5173)
```

- [ ] **Step 3: Delete the three extension-only rules in `scripts/check-invariants.ps1`**

Rules 1, 4, and 5 are all path-filtered to `^extension/` files — with the package gone they can never fire. Delete the **Rule 1** block (lines ~61-67), the **Rule 4** block (lines ~82-86), and the **Rule 5** block (lines ~88-104). Renumber the survivors so the file reads:

```powershell
# Rule 1: No datetime.utcnow() in backend (Invariant #5).
Test-StagedPattern `
    -Pattern "datetime\.utcnow\(" `
    -PathFilter "^backend/app/.*\.py$" `
    -Message "Invariant #5: Use app.util.naive_utcnow(), not datetime.utcnow()"

# Rule 2: No Base.metadata.create_all outside init_db.
Test-StagedPattern `
    -Pattern "Base\.metadata\.create_all" `
    -PathFilter "^backend/" `
    -Message "Use Alembic migrations, not Base.metadata.create_all" `
    -ExcludePaths @("^backend/app/models\.py$")

# Rule 3: defence-in-depth — never commit secrets / DB / local settings.
$forbidden = git diff --cached --name-only --diff-filter=ACMR 2>$null | Where-Object {
    $_ -match "(^|/)\.env(\.|$)" -or
    $_ -match "\.db(-journal|-wal|-shm)?$" -or
    $_ -match "^\.claude/settings\.local\.json$" -or
    $_ -match "^backend/data/"
}
foreach ($f in $forbidden) {
    $violations += "[forbidden file staged] $f -- must never be committed"
}
```

(Leave the stdin-parsing, `Test-StagedPattern` function, and the report/exit block untouched.)

- [ ] **Step 4: Verify the script still parses**

Run: `powershell -NoProfile -ExecutionPolicy Bypass -Command "& { . ./scripts/check-invariants.ps1 }" < /dev/null; echo "exit=$?"`
Expected: `exit=0` (empty stdin → early `exit 0`; no parse error).

- [ ] **Step 5: Run the backend gate**

Run (from `backend/`, `.venv` active): `ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
Expected: all green. (Existing CORS-agnostic tests unaffected; no test asserts the `chrome-extension` regex.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/main.py backend/CLAUDE.md scripts/check-invariants.ps1
git commit -m "refactor: drop extension CORS allowance + dead invariant-guard rules"
```

---

### Task 3: Replace `ExtensionCallout` with a backend-oriented `EmptyBoard`

**Files:**
- Create: `webapp/src/components/EmptyBoard.vue`
- Create: `webapp/src/components/EmptyBoard.spec.ts`
- Delete: `webapp/src/components/ExtensionCallout.vue`
- Modify: `webapp/src/App.vue:12`, `:50-51`, `:245`, `:253`

- [ ] **Step 1: Write the failing test**

Create `webapp/src/components/EmptyBoard.spec.ts`:

```ts
import { mount } from '@vue/test-utils';
import { describe, expect, it } from 'vitest';
import EmptyBoard from './EmptyBoard.vue';

describe('EmptyBoard', () => {
  it('shows the no-tickets heading and points at the backend sync path', () => {
    const wrapper = mount(EmptyBoard);
    const text = wrapper.text();
    expect(text).toContain('No tickets yet');
    expect(text).toContain('POST /tickets/sync');
    expect(text).toContain('INTERCOM_POLL_INTERVAL_SECONDS');
  });

  it('does not mention the Chrome extension', () => {
    expect(mount(EmptyBoard).text().toLowerCase()).not.toContain('extension');
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `webapp/`): `npx vitest run src/components/EmptyBoard.spec.ts`
Expected: FAIL — `Failed to resolve import './EmptyBoard.vue'`.

- [ ] **Step 3: Create the component**

Create `webapp/src/components/EmptyBoard.vue` (styles lifted from the old callout's `.empty` block — already `DESIGN.md`-token compliant):

```vue
<!-- Empty-board placeholder. Shown on the board view when zero tickets are
     stored. Ingestion is backend-side (POST /tickets/sync or the poller), so
     the copy points there — not at any client surface. -->
<script setup lang="ts">
import Mono from './Mono.vue';
</script>

<template>
  <div class="empty">
    <Mono :size="11">No tickets yet</Mono>
    <p class="lead">The board fills once the backend ingests conversations from Intercom.</p>
    <ol class="steps">
      <li>Trigger one cycle now: <code>POST /tickets/sync</code> (503 if no token is set).</li>
      <li>
        Or set <code>INTERCOM_POLL_INTERVAL_SECONDS</code> in <code>backend/.env</code> to run the
        background poller.
      </li>
      <li>
        Still empty? Check <code>/health</code> — <code>intercom_configured</code> flags a missing
        token.
      </li>
    </ol>
  </div>
</template>

<style scoped>
.empty {
  flex: 1;
  align-self: center;
  margin: 60px auto;
  max-width: 520px;
  padding: 24px 28px;
  border: var(--hairline) solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--ink-2);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.empty .lead {
  margin: 0;
  font-size: 13px;
  color: var(--ink);
  line-height: 1.5;
}
.empty .steps {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.55;
}
.empty .steps li {
  margin-bottom: 4px;
}
code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--chip-bg);
  padding: 1px 4px;
  border-radius: 2px;
  color: var(--ink);
}
</style>
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `webapp/`): `npx vitest run src/components/EmptyBoard.spec.ts`
Expected: PASS (both cases).

- [ ] **Step 5: Swap the component in `App.vue` and delete the old one**

In `webapp/src/App.vue`:

Replace the import (line 12):
```
import ExtensionCallout from '@/components/ExtensionCallout.vue';
```
with:
```
import EmptyBoard from '@/components/EmptyBoard.vue';
```

Replace the onMounted comment (lines 50-51):
```
  // An unreachable backend leaves the board empty + raises an inline error;
  // the empty-state callout points the operator at the extension to sync.
```
with:
```
  // An unreachable backend leaves the board empty + raises an inline error;
  // the empty-state points the operator at the backend sync path.
```

Delete the top-banner usage (line 245 — remove the whole line):
```
    <ExtensionCallout />
```

Replace the empty-state usage (line 253):
```
        <ExtensionCallout v-if="tickets.isEmpty" mode="empty" />
```
with:
```
        <EmptyBoard v-if="tickets.isEmpty" />
```

Then delete the old component:
```bash
git rm webapp/src/components/ExtensionCallout.vue
```

- [ ] **Step 6: Verify the webapp gate**

Run (from `webapp/`): `npm run typecheck && npm run lint && npm test && npm run build`
Expected: all green. `git grep -n ExtensionCallout webapp` returns nothing.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(webapp): replace ExtensionCallout with backend-oriented EmptyBoard"
```

---

### Task 4: Clean stale extension references in webapp source + guide

**Files:**
- Modify: `webapp/src/api/client.ts:91`
- Modify: `webapp/src/types/api.ts:248`
- Modify: `webapp/src/stores/settings.ts:71`
- Modify: `webapp/src/stores/tickets.ts:4,6`
- Modify: `webapp/src/stores/tweaks.ts:4`
- Modify: `webapp/src/components/settings/DrawerSyncSection.vue:25`
- Modify: `webapp/CLAUDE.md` ("Data-flow pivot" section)

These are all already stale (they describe the pre-PR-#8 extension-ingest model). Correct them to the backend-ingest reality.

- [ ] **Step 1: `webapp/src/api/client.ts` — fix the `GET /tickets` doc comment (line 91)**

Replace:
```
  /** The stored board — extension-ingested + categorized tickets.
```
with:
```
  /** The stored board — backend-ingested + categorized tickets.
```

- [ ] **Step 2: `webapp/src/types/api.ts` — drop the popup mention (line 248)**

Replace:
```
  mute_alarms: boolean; // FR-024 — shared by webapp + popup
```
with:
```
  mute_alarms: boolean; // FR-024 — server-side so it persists across reloads
```

- [ ] **Step 3: `webapp/src/stores/settings.ts` — fix the comment (line ~71)**

Replace the phrase `so the popup` in the `mute flag lives in the server settings row` comment so it reads (full sentence):
```
  /** FR-024 — the mute flag lives in the server settings row so it persists
```
(adjust the continuation line to drop any "the popup shares it" clause; keep the FR-024 rationale otherwise intact).

- [ ] **Step 4: `webapp/src/stores/tickets.ts` — fix the header comment (lines 4-6)**

Replace:
```
// stored `tickets` table the Chrome extension ingests into (`GET /tickets`).
```
with:
```
// stored `tickets` table the backend ingests into (`GET /tickets`).
```
and replace:
```
// extension callout instead of mock data.
```
with:
```
// empty-state instead of mock data.
```

- [ ] **Step 5: `webapp/src/stores/tweaks.ts` — fix the comment (line 4)**

Replace the clause `so the popup shares it` with `so it persists server-side` in the FR-024 comment.

- [ ] **Step 6: `webapp/src/components/settings/DrawerSyncSection.vue` — fix user-facing copy (line 25)**

Replace:
```
      Refreshes the board silently when the extension or another browser session ingests new
```
with:
```
      Refreshes the board silently when the backend poller ingests new
```
(Keep the rest of the sentence; verify it still reads grammatically — e.g. "…ingests new tickets.")

- [ ] **Step 7: `webapp/CLAUDE.md` — rewrite the "Data-flow pivot" bullet**

Replace the bullet:
```
- Empty DB → `ExtensionCallout mode="empty"` tells the operator the board is empty. The actionable cause is now "no token / nothing synced yet" (`/health.intercom_configured`), not "open the extension and sync." Never mock data. (Copy may still mention the extension as a quick-glance board — it's no longer the ingestion path.)
```
with:
```
- Empty DB → `EmptyBoard` tells the operator the board is empty. The actionable cause is "no token / nothing synced yet" (`/health.intercom_configured`); run `POST /tickets/sync` or enable the poller. Never mock data.
```

- [ ] **Step 8: Verify the webapp gate**

Run (from `webapp/`): `npm run typecheck && npm run lint && npm run format:check && npm test && npm run build`
Expected: all green. `git grep -ni "popup\|chrome extension\|extension-ingested\|extension ingests\|extension callout" webapp/src` returns nothing.

- [ ] **Step 9: Commit**

```bash
git add webapp
git commit -m "refactor(webapp): scrub stale extension references from comments + copy"
```

---

### Task 5: Rewrite root `CLAUDE.md` (invariants + scope + map)

**Files:**
- Modify: `CLAUDE.md` (root)

- [ ] **Step 1: Sub-package guide list (top of file)**

Delete the line:
```
> - [`extension/CLAUDE.md`](./extension/CLAUDE.md) — Chrome MV3 popup + service worker
```

- [ ] **Step 2: Repo-map tree**

Delete the line:
```
├── extension/      Chrome MV3 popup + background service worker            ← see extension/CLAUDE.md
```

- [ ] **Step 3: Quality-gates table**

Delete the `extension` row (the `Reload unpacked in chrome://extensions …` row).

- [ ] **Step 4: Invariant #1**

In the "Cross-package invariants" section, edit invariant #1 to remove the extension clauses. Replace:
```
1. **Backend owns Intercom ingestion via an Access Token.** The backend polls the official `api.intercom.io` REST API with a workspace Bearer token from `backend/.env` (`INTERCOM_ACCESS_TOKEN`), normalizes payloads in `backend/app/services/intercom_normalizer.py`, and ingests them through `run_sync_cycle` (`backend/app/services/sync.py`). A background poller (interval-gated, default off) + `POST /tickets/sync` drive it. **The extension no longer touches Intercom** — it is a read-only mini-board + badge over the backend. (This reverses the former session-scrape model; the extension `ember/` path is gone.)
```
with:
```
1. **Backend owns Intercom ingestion via an Access Token.** The backend polls the official `api.intercom.io` REST API with a workspace Bearer token from `backend/.env` (`INTERCOM_ACCESS_TOKEN`), normalizes payloads in `backend/app/services/intercom_normalizer.py`, and ingests them through `run_sync_cycle` (`backend/app/services/sync.py`). A background poller (interval-gated, default off) + `POST /tickets/sync` drive it. The backend `IntercomClient` is the only ingestion path; no client surface touches Intercom.
```

- [ ] **Step 5: Invariant #2 aside (optional tidy)**

Invariant #2's "produced by the backend normalizer …, not the extension" remains true; if it reads awkwardly now, change "not the extension" to "not any client surface". No functional change.

- [ ] **Step 6: Invariant #10**

Remove the popup-tab clause. Replace:
```
Non-actionable renders as its own Kanban column (webapp) / its own popup tab (extension) — split from Resolved at the view layer (`tickets.nonActionableTickets` / `pureResolvedTickets` getters); storage stays unified.
```
with:
```
Non-actionable renders as its own Kanban column (webapp) — split from Resolved at the view layer (`tickets.nonActionableTickets` / `pureResolvedTickets` getters); storage stays unified.
```

- [ ] **Step 7: Invariant #14**

Remove the extension clause. Replace:
```
    `parked_until` / `parked_reason` live on `TicketSchema` (the board
    response), never on `HydratedTicket` — so the extension's
    `normalizeConversation` does not carry them (invariant #2 untouched). The
```
with:
```
    `parked_until` / `parked_reason` live on `TicketSchema` (the board
    response), never on `HydratedTicket` (invariant #2 untouched). The
```

- [ ] **Step 8: Scope guardrails**

Replace:
```
- Three packages, three stacks, intentionally. **Don't merge them.** Extension = plain ES modules (MV3); webapp = Vue 3 + Vite (SPA); backend = FastAPI (HTTP). No monorepo tool, shared package, codegen step.
```
with:
```
- Two packages, two stacks, intentionally. **Don't merge them.** webapp = Vue 3 + Vite (SPA); backend = FastAPI (HTTP). No monorepo tool, shared package, codegen step.
```

Replace:
```
- `localhost:4000` (backend) + `localhost:5173` (webapp dev) + `chrome-extension://…` (popup). Vite proxies `/api/*` → `127.0.0.1:4000`. No reverse proxy, Docker, nginx.
```
with:
```
- `localhost:4000` (backend) + `localhost:5173` (webapp dev). Vite proxies `/api/*` → `127.0.0.1:4000`. No reverse proxy, Docker, nginx.
```

- [ ] **Step 9: "Don't" section**

Replace:
```
- Don't add a SECOND Intercom integration. The backend `IntercomClient` (`backend/app/clients/intercom.py`) is the only ingestion path; don't give the extension or webapp Intercom access again.
```
with:
```
- Don't add a SECOND Intercom integration. The backend `IntercomClient` (`backend/app/clients/intercom.py`) is the only ingestion path; don't give the webapp Intercom access.
```

- [ ] **Step 10: "Parallel sessions & worktrees" section**

In the bullet describing the `HydratedTicket` contract, replace "A shape change touches the schema, the normalizer, and the webapp type" context that names the extension — specifically change:
```
  produced by
  `backend/app/services/intercom_normalizer.py` (invariant #2). A shape change touches the
  schema, the normalizer, and the webapp type; don't split it across parallel
  sessions.
```
(if the existing text mentions the extension here, drop that mention). Scan the whole section for any remaining `extension` token and remove it.

- [ ] **Step 11: Verify**

Run: `git grep -ni "extension\|popup\|mv3\|chrome-extension\|mini-board" CLAUDE.md`
Expected: no hits. (If "extension" survives only inside an unrelated word, re-check; there should be none.)

- [ ] **Step 12: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: drop the extension from root CLAUDE.md (invariants, scope, map)"
```

---

### Task 6: Update `docs/PROJECT.md`

**Files:**
- Modify: `docs/PROJECT.md`

- [ ] **Step 1: §2 three-package table** — delete the `extension/` row; change the intro sentence "Three packages, three stacks" to "Two packages, two stacks" and "Three stacks intentionally — **do not merge them.**" → "Two stacks intentionally — **do not merge them.**"

- [ ] **Step 2: §3 architecture diagram** — in the ASCII diagram, remove the `GET /tickets (popup mini-board)` reader branch so only the webapp reads the board; keep both mutation arrows as the webapp. Specifically collapse:
```
                          ┌──────┴──────┐
                          ▼             ▼
                  GET /tickets     GET /tickets
                   (webapp)        (popup mini-board)
```
to:
```
                                ▼
                          GET /tickets
                            (webapp)
```

- [ ] **Step 3: §5 stack table** — delete the row:
```
| extension | Plain ES modules, MV3, no build step, no dependencies |
```

- [ ] **Step 4: §7 invariant index** — edit the one-line index entries #1, #10, #14 to match the root CLAUDE.md rewrites:
  - #1: `Backend owns Intercom ingestion via an Access Token (`api.intercom.io`); the backend client is the only ingestion path.`
  - #10: drop `non_actionable_kind` line's popup reference if any; the index line for #10 stays about the XOR. (Leave as-is if it does not name the popup.)
  - #14: `Parked is board-state (trio on the board response, not `HydratedTicket`), XOR-locked.` (already extension-free — leave).

- [ ] **Step 5: §10 feature/roadmap status** — update the spec-version reference and backlog. Change `feature-complete against `contract/spec.md` v1.7` → `v1.9` (this change bumps the spec; see Task 8). In the **Open backlog** table: edit the T100 row to drop "+ popup" / "extension" from the SSE target, and **delete the T105 row** (Bulk actions in the extension popup).

- [ ] **Step 6: §11 quality-gates table** — delete the `extension` row.

- [ ] **Step 7: §4 run-the-stack** — delete the paragraph:
```
Extension is loaded once manually: `chrome://extensions` → Developer mode →
Load unpacked → select `extension/`. Reload it after every code change.
```
and remove the trailing sentence about entering the workspace `app_id` "in the popup setup screen … (`chrome.storage.local.intercomAppId`)" from the First-boot paragraph (the backend reads the token from `.env`; there is no popup setup).

- [ ] **Step 8: §12 glossary + §13 docs map** — remove the "popup tab" mention from the **non-actionable** glossary entry; in §13's docs table, drop the `extension/` mention from the `CLAUDE.md (+ …)` row.

- [ ] **Step 9: Verify**

Run: `git grep -ni "extension\|popup\|mv3\|mini-board" docs/PROJECT.md`
Expected: no hits.

- [ ] **Step 10: Commit**

```bash
git add docs/PROJECT.md
git commit -m "docs: collapse PROJECT.md to two packages, drop extension references"
```

---

### Task 7: Update `docs/FEATURES.md`

**Files:**
- Modify: `docs/FEATURES.md`

- [ ] **Step 1: Surface legend (line 17)** — replace:
```
- **surface**: `backend` (HTTP) · `ai` (OpenRouter/embeddings) · `webapp` · `extension` · `both` (webapp+extension)
```
with:
```
- **surface**: `backend` (HTTP) · `ai` (OpenRouter/embeddings) · `webapp`
```
Also update the counts line ("~50 user-facing UI features") only if it names the extension; otherwise leave.

- [ ] **Step 2: Retag `(both · …)` → `(webapp · …)`** on every feature entry that uses the `both` surface tag (lines ~40, 41, 42, 45, 47, 54, 55, 56, 58, 65, 67, 68). `both` meant webapp+extension; with the extension gone these are webapp-only.

- [ ] **Step 3: Drop `popup.js` code anchors** — on the **Live countdown chip** entry (line 67) change `(both · `TicketCard.vue`, `popup.js`)` → `(webapp · `TicketCard.vue`)`; on the **Alarm banners** entry (line 68) change `(both · `AlarmBanners.vue`, `popup.js`)` → `(webapp · `AlarmBanners.vue`)`.

- [ ] **Step 4: Delete §K (Extension)** — remove the entire `## K. Extension (Chrome MV3 popup)` section (lines ~135-141: popup mini-board, popup per-ticket actions, refresh, background badge poll).

- [ ] **Step 5: Open backlog** — in the bottom "Open backlog" list, **delete** the `[OPEN] Bulk actions in the extension popup` line and edit the `[OPEN] Webhook + SSE live updates` line to drop "+ popup" / "extension" from the push target (→ "push to the webapp").

- [ ] **Step 6: Verify**

Run: `git grep -ni "extension\|popup\|mv3\|mini-board\|\bboth\b" docs/FEATURES.md`
Expected: no hits (note `both` is also gone from the legend, so a stray `both` surface tag means a missed retag).

- [ ] **Step 7: Commit**

```bash
git add docs/FEATURES.md
git commit -m "docs: remove extension section + retag both→webapp in FEATURES.md"
```

---

### Task 8: Bump `docs/contract/spec.md` to v1.9 (remove extension requirements)

**Files:**
- Modify: `docs/contract/spec.md`

- [ ] **Step 1: Header + changelog** — bump `**Version:** 1.8` → `**Version:** 1.9` and add, directly under the header, a new changelog entry above "Changes from v1.7":
```
**Changes from v1.8:** extension retired — the Chrome extension package is removed. The webapp is the sole client surface; the backend (already the only Intercom ingestion path since v1.7) is unchanged. Deleted US-006 (Chrome-extension mini-board); removed extension/popup mentions from §2 scope, §3 personas, the alarm/non-actionable requirements, and NFR-010. No backend or board behavior removed.
```
(Leave the older "Changes from v1.7/v1.6/…" entries — they are historical record.)

- [ ] **Step 2: §2 Scope (line 29)** — replace:
```
In scope: a local tool with a backend, a webapp surface, and a Chrome extension surface. Intercom integration via the operator's logged-in browser session (extension-driven; no API token). AI categorization and summarization against a curated taxonomy. AI proposal flow for new categories. Manual category override that persists. Dynamic category curation.
```
with:
```
In scope: a local tool with a backend and a webapp surface. Intercom integration server-side via a workspace Access Token (the backend polls `api.intercom.io`). AI categorization and summarization against a curated taxonomy. AI proposal flow for new categories. Manual category override that persists. Dynamic category curation.
```

- [ ] **Step 3: §3 Personas (line 35)** — replace:
```
A single **operator** — the person running the tool on their own machine. They sign in to Intercom in Chrome, install the extension, triage tickets daily, and curate categories as the taxonomy evolves.
```
with:
```
A single **operator** — the person running the tool on their own machine. They configure the Intercom Access Token once, triage tickets daily from the webapp board, and curate categories as the taxonomy evolves.
```

- [ ] **Step 4: Delete US-006 (lines 80-88)** — remove the entire `### US-006 — Genuine mini-board in the Chrome extension` story and its acceptance bullets. (Do not renumber later US-* ids — they are referenced across plan/tasks/FEATURES; leave the gap.)

- [ ] **Step 5: Line 104** — replace `Neither the webapp nor the extension ever receives the credentials.` with `The webapp never receives the credentials.`

- [ ] **Step 6: Line 150** — replace `An alarm banner appears top-right of the webapp board and at the top of the popup.` with `An alarm banner appears top-right of the webapp board.`

- [ ] **Step 7: Line 201** — the closure pass is backend-side now. Replace the clause `The extension's sync flow includes a closure pass: it diffs tracked ids` with `The backend sync cycle includes a closure pass: it diffs tracked ids` (keep the rest of the sentence).

- [ ] **Step 8: Line 245** — replace `their own Kanban column in the webapp and their own popup tab` with `their own Kanban column in the webapp`.

- [ ] **Step 9: NFR-010 (line 550)** — replace `it never reaches the webapp/extension bundle, logs, or error responses` with `it never reaches the webapp bundle, logs, or error responses`.

- [ ] **Step 10: Line 562** — delete the bullet `- **Extension popup depth:** genuine mini-board with override support. The webapp surfaces a callout for installing the extension.`

- [ ] **Step 11: Verify** — Run: `git grep -ni "extension\|popup\|chrome\|mini-board" docs/contract/spec.md`
Expected: hits only on the historical "Changes from v1.7/v1.2" changelog lines (7, 17) and the new v1.8 changelog entry. No hits in the active requirement body.

- [ ] **Step 12: Commit**

```bash
git add docs/contract/spec.md
git commit -m "docs(spec): bump to v1.9 — retire the Chrome extension, delete US-006"
```

---

### Task 9: Update `docs/contract/plan.md`

**Files:**
- Modify: `docs/contract/plan.md`

- [ ] **Step 1: Stack table (line 32)** — delete the row `| Extension | Manifest V3 + vanilla TypeScript | Keeps popup bundle small |`.

- [ ] **Step 2: Deploy row (line 36)** — replace `webapp via `npm run dev` or static build; extension side-loaded` with `webapp via `npm run dev` or static build`.

- [ ] **Step 3: Architecture narrative (line 48)** — delete the paragraph:
```
The **Chrome extension** is a Manifest V3 extension. It is a read-only mini-board over the backend (full taxonomy as column tabs, override-capable) + a toolbar badge + "Open full board" handoff. It has **no** Intercom access — ingestion is entirely backend-side.
```

- [ ] **Step 4: Line 324** — keep the backend-ownership point, drop the extension clause. Replace `The extension has no Intercom access — ingestion is entirely backend-side.` with `Ingestion is entirely backend-side.`

- [ ] **Step 5: Alarm section (lines 366, 368, 384)** — replace `lets the popup raise alarms even when the webapp isn't open` with `runs entirely client-side in the webapp`; change the heading `**Client alarm loop** (webapp + popup):` → `**Client alarm loop** (webapp):`; replace `Webapp + popup must match.` with `The webapp implements it.`

- [ ] **Step 6: Line 477** — replace `Webapp-only in v1 — popup ergonomics too cramped for multi-select.` with `Webapp multi-select; bulk endpoints are cap-200 with per-id results.`

- [ ] **Step 7: Lines 546, 585** — change `Both surfaces `GET /settings`` / `both surfaces read the same shape` to reference just the webapp (e.g. `The webapp `GET /settings` on open …`).

- [ ] **Step 8: Line 555** — delete the comment line `# extension: chrome://extensions → load unpacked → ./extension`.

- [ ] **Step 9: Lines 619-620** — drop the `Extension popup gains …` clause from the parked-state description; keep the webapp park behavior.

- [ ] **Step 10: Lines 709-710** — drop the parenthetical `(the extension/`HydratedTicket` shape is untouched, …`; the priority badge is a webapp concern.

- [ ] **Step 11: Verify** — Run: `git grep -ni "extension\|popup\|mv3\|mini-board" docs/contract/plan.md`
Expected: hits only on the historical "Changes from v1.3" changelog line (11). No hits in the active body.

- [ ] **Step 12: Commit**

```bash
git add docs/contract/plan.md
git commit -m "docs(plan): remove extension architecture + popup clauses"
```

---

### Task 10: Update `docs/contract/tasks.md` (retarget T100, drop T105, add tombstone)

**Files:**
- Modify: `docs/contract/tasks.md`

- [ ] **Step 1: T100 (line 208)** — replace `push channel (SSE) to webapp and extension` with `push channel (SSE) to the webapp`.

- [ ] **Step 2: T105 (line 212)** — delete the line `- T105 — Bulk actions in the extension popup. *(roadmap 4.4 — open)*`.

- [ ] **Step 3: Add the removal tombstone task** — find the highest existing `T1NN` (Phase-19 ran T161–T166, so the next free id is **T167**; confirm with `git grep -oE "T1[0-9][0-9]" docs/contract/tasks.md | sort -u | tail -5`). Append a tombstone in the appropriate section:
```
- T167 ✓ — Remove the Chrome extension entirely: delete `extension/`, the CORS `chrome-extension://` regex, `webapp/.../ExtensionCallout.vue` (→ `EmptyBoard.vue`), `qa-extension`, and `check-invariants.ps1` extension rules; scrub spec/plan/tasks/PROJECT/FEATURES/README + the 14 invariants (#1/#10/#14). Continuation of T165. spec v1.9, inv #1.
```

- [ ] **Step 4: Leave Phase 7 + completed extension tasks** — T039–T053, T070/T071, T094, T106, T165 are a historical ledger of shipped work. Do **not** delete them; they record what happened. (The changelog lines 18/24 likewise stay.)

- [ ] **Step 5: Verify** — Run: `git grep -ni "extension popup\|popup mini-board\|popup tab" docs/contract/tasks.md`
Expected: no hits in active/open items (historical "✓" ledger lines may still name the popup — that is intended).

- [ ] **Step 6: Commit**

```bash
git add docs/contract/tasks.md
git commit -m "docs(tasks): retarget T100, drop T105, add extension-removal tombstone T167"
```

---

### Task 11: Update root `README.md`

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Title line (5)** — replace `Backend + webapp + Chrome extension, all on `localhost`.` with `Backend + webapp, all on `localhost`.`

- [ ] **Step 2: Layout (line 18)** — delete the line `├── extension/      Chrome MV3 popup mini-board + background badge`.

- [ ] **Step 3: Prerequisites (lines 27-28)** — delete the bullet:
```
- Chrome — optional: the extension is a read-only toolbar mini-board over the
  backend (it no longer touches Intercom)
```

- [ ] **Step 4: Quickstart §3 (lines 73-85)** — delete the entire `### 3. Chrome extension` section (the heading, the three install steps, and the read-only-mini-board paragraph).

- [ ] **Step 5: Dev launcher note (lines 164-165)** — replace `in a split-pane. Requires `wt.exe` (Windows Terminal — default on Win 11). Extension is loaded manually once via `chrome://extensions`.` with `in a split-pane. Requires `wt.exe` (Windows Terminal — default on Win 11).`

- [ ] **Step 6: Verify** — Run: `git grep -ni "extension\|chrome\|popup\|mv3\|mini-board" README.md`
Expected: no hits.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: drop the Chrome extension from the README"
```

---

### Task 12: Tooling cleanup, full grep sweep, final gates

**Files:**
- Modify: `scripts/dev.ps1:10`
- Modify: `.claude/commands/qa-all.md` (conditional)
- Modify: `.gitignore` (conditional)

- [ ] **Step 1: `scripts/dev.ps1`** — delete the comment line:
```
# Extension: load manually once via chrome://extensions
```

- [ ] **Step 2: `.claude/commands/qa-all.md`** — Run `git grep -ni "extension" .claude/commands/qa-all.md`. If it chains a `qa-extension` leg, remove that leg so it runs only backend + webapp. If there are no hits, leave the file unchanged.

- [ ] **Step 3: `.gitignore`** — Run `git grep -n "extension" .gitignore`. If `extension/dist` / `extension/build` entries exist, delete them. If no hits, leave unchanged.

- [ ] **Step 4: Repo-wide grep sweep** — Run:
```bash
git grep -ni "chrome-extension\|\bmv3\b\|mini-board\|popup" -- . ':(exclude)docs/_archive/*'
```
Expected: **zero** hits except — (a) the `docs/contract/spec.md` historical changelog lines (7/17) and new v1.8 entry, (b) the `docs/contract/tasks.md` historical "✓" ledger lines and the T167 tombstone. Investigate anything else.

Then run:
```bash
git grep -ni "\bextension\b" -- . ':(exclude)docs/_archive/*'
```
Expected: only the same historical changelog/ledger lines + the design doc + this plan doc. No active code or active-doc hits. (`badge` is intentionally NOT swept — it survives legitimately as the webapp priority badge on cards.)

- [ ] **Step 5: Final backend gate** — Run (from `backend/`, `.venv` active): `ruff check app tests && ruff format --check app tests && mypy app && pytest -q`
Expected: all green.

- [ ] **Step 6: Final webapp gate** — Run (from `webapp/`): `npm run lint && npm run format:check && npm run typecheck && npm test && npm run build`
Expected: all green.

- [ ] **Step 7: Verify the invariant hook still parses** — Run: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/check-invariants.ps1 < /dev/null; echo "exit=$?"`
Expected: `exit=0`.

- [ ] **Step 8: Commit**

```bash
git add scripts/dev.ps1 .claude/commands/qa-all.md .gitignore
git commit -m "chore: final extension cleanup (dev launcher, qa-all, gitignore)"
```

---

## Done criteria

- `extension/` directory gone; no `ExtensionCallout`, no `qa-extension`.
- Backend CORS no longer allows `chrome-extension://`; `check-invariants.ps1` has no dead extension rules.
- Webapp shows `EmptyBoard` on an empty board; `npm` gate green.
- spec at **v1.9**; PROJECT/FEATURES/README/plan/tasks/CLAUDE.md all extension-free (bar intended historical changelog + ledger lines).
- Grep sweep clean; both quality gates green.
- One PR on `refactor/remove-extension`, ~12 commits.

## Self-review notes (author)

- **Spec coverage:** every §6 item in the design maps to a task — delete (T1), CORS+hook (T2), empty-state (T3), webapp strays (T4, an addition found during grounding), root CLAUDE.md/invariants (T5), PROJECT (T6), FEATURES (T7), spec (T8), plan (T9), tasks (T10), README (T11), tooling+sweep (T12).
- **Refinement vs design:** check-invariants Rules **1/4/5** are deleted (all `^extension/`-path-filtered), not just 4/5 — the design said "keep the invariant-#1 backend-ownership check" but no such grep rule exists; Rule 1 is the extension-Intercom check and is now dead. PROJECT.md spec-version reference is bumped v1.7→v1.9 here (the design listed the pre-existing v1.7→v1.8 staleness as separate, but this change moves the spec to v1.9, so PROJECT must follow to stay consistent).
- **Type/name consistency:** `EmptyBoard.vue` / `EmptyBoard` used identically in the component, its test, and `App.vue`. `tickets.isEmpty` is the existing getter the old callout used — reused unchanged.
- **No placeholders:** every code/edit step shows the exact before/after text or full file content.

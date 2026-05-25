# CLAUDE.md

Guidance for Claude Code when working in `extension/`. These four principles override defaults — apply them on every change.

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

- State assumptions explicitly before touching code. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

In this repo:
- **The extension is the only Intercom integration.** The backend has no Intercom Access Token. Conversations are scraped from the operator's logged-in browser session against undocumented `ember/` endpoints and POSTed to `/tickets/ingest`. If you're tempted to add an Access-Token path or a backend-side Intercom client, stop and ask — that path doesn't exist.
- Intercom's `ember/` endpoints (`/ember/inbox/conversations/list`, `/ember/inbox/conversations/{id}`) are **undocumented and may change without notice**. Any code touching them is brittle. Flag changes to `intercom.js` accordingly; verify against live conversations before merging.
- The `renderable_type` mapping is reverse-engineered: `1`/`12` = inbound customer, `2`/`24` = admin reply (customer-visible), `3` = internal team note (admin-only). `5`/`6`/`14`/`71` are events and must be skipped. Adding a new type means inspecting a live payload — never guess.
- `parts[]` is customer-visible (fed to AI). `internal_notes[]` is team-only (never fed to AI). Don't merge them.
- Two clocks: Intercom timestamps can be ISO strings *or* unix seconds depending on endpoint/version. `toIso` accepts both. Don't drop the coercion.
- `summary.last_updated` ≠ `summary.updated_at` ≠ `summary.sorting_updated_at`. `summaryUpdatedMs` walks all three for the same reason. Don't simplify it without verifying the list response shape.
- 401/403 ≠ generic failure. Auth errors must bubble (`IntercomSessionError`) so the popup surfaces a "log in" hint; other errors degrade silently (best-effort badge / sync).

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" / "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

In this repo:
- **No build step.** Plain ES modules loaded by MV3 (`background.service_worker.type = "module"`, `<script type="module">` in `popup.html`). Don't introduce webpack / rollup / TypeScript / a bundler. Don't add npm dependencies. Plain `.js` files only.
- **No frameworks.** Popup DOM is built with `node(tag, className, text)` + `element.append(...)`. Don't introduce Vue / React / Preact / lit. The webapp is the place for a framework; this popup is intentionally minimal.
- One `api.js` (backend client). One `intercom.js` (Intercom session scraper). One `background.js` (service worker). One `popup.js` (mini-board controller). Don't carve a fifth module unless a new surface justifies it.
- The popup polls in-memory state at 1Hz via `alarmTick`. Don't replace it with reactive state, observables, or a store layer. A `state` object + targeted `render*` functions is the pattern.
- Permissions in `manifest.json` are deliberately narrow: `storage`, `alarms`, and host permissions for `127.0.0.1:8000` / `localhost:8000` / `app.intercom.com`. Don't add `tabs`, `cookies`, `webRequest`, or broader hosts unless a feature *requires* them.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports / functions your change made unused. Don't remove pre-existing dead code unless asked.

In this repo:
- Style: 2-space indent, single quotes, trailing commas, semicolons, `const`/`let` only, JSDoc on exported functions. Match it.
- Service worker is `type: "module"` — use `import` / `export`, not `importScripts`. The service worker may be killed and restarted between alarms; nothing persists across ticks except `chrome.storage.local`. Don't add module-level state that you expect to survive (counters, caches, timers).
- `chrome.storage.local` is the only persistence. Current keys: `intercomAppId` (workspace), `pollMinutes` (background interval). Document any new key in this file before adding it.
- `chrome.alarms` minimum period in production builds is 1 minute — values < 1 are silently clamped. Don't add sub-minute polling.
- Backend client lives in `api.js`. Don't inline `fetch(API_BASE + …)` into `popup.js` / `background.js`.
- Intercom client lives in `intercom.js`. Don't import its internals from elsewhere — only the named exports (`fetchHydratedBatch`, `getAppId`, `setAppId`, `getConversation`, `listClosedConversations`, `normalizeConversation`, `IntercomSessionError`, `LOOKBACK_SECONDS`).
- `normalizeConversation` produces a `HydratedTicket` matching the backend's pydantic schema (`backend/app/schemas.py:HydratedTicket`). Any new field on either side must be added on both — or the backend rejects the ingest. Cross-check before editing the shape.
- The skip-known optimization in `fetchHydratedBatch` is load-bearing: it reads `GET /tickets/sync-state` and bypasses the per-conversation detail fetch when the summary's `last_updated` is `<=` the stored value. Don't remove it.
- The closure pass in `background.js:ingestFromIntercom` exists so `state: open → closed` transitions get caught (Intercom drops closed conversations from `state=open` listings). Don't simplify it away.
- Fallback caching in the backend skips `result.fallback` rows — the extension's ingest call doesn't influence that. If you change the ingest shape, do not assume the backend will retry.

The test: every changed line traces directly to the user's request.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals before writing code:
- "Fix the popup not loading" → "Open the popup, see N tickets render."
- "Skip already-stored conversations" → "Sync, see `received - cache_hits == 0` in `/metrics`."
- "Refactor `intercom.js`" → "Reload unpacked, sync, see same ticket set in `/tickets`."

For multi-step work, state the plan up front:

```
1. [step] → verify: [check]
2. [step] → verify: [check]
```

There is no automated test suite for the extension. Every change is verified manually:

| Change                          | Verify with                                                                 |
|---------------------------------|-----------------------------------------------------------------------------|
| `popup.js` UI                   | `chrome://extensions` → reload → open popup → click through                  |
| `intercom.js` scrape / parse    | Open popup → "Sync now" → check `GET /tickets` count + sample parts          |
| `background.js` polling         | Set interval in popup footer → wait ≥ 1 tick → check toolbar badge          |
| Backend schema change           | Coordinate with `backend/app/schemas.py:HydratedTicket` — both sides ship together |
| Manifest / permission change    | Reload unpacked — Chrome surfaces permission deltas in a confirm dialog     |

"Reload and it looks fine" is not a success criterion. Name the click-path, the network call, or the `/metrics` counter that proves the change.

---

# Reference

## Install (unpacked)

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. **Load unpacked** → select this `extension/` folder.

Reload after every code change — Chrome doesn't watch files. (Right-click extension icon → Manage → reload icon, or the refresh arrow on the `chrome://extensions` card.)

Operator must enter the workspace `app_id` (e.g. `j3dxf22l`) in the popup setup screen on first run. It's stored in `chrome.storage.local.intercomAppId`.

## Architecture

Manifest V3 extension. One popup window, one service worker. Talks to:
- Backend on `http://127.0.0.1:8000` (CORS-allowed via `chrome-extension://[a-z]{32}` regex in `backend/app/main.py`).
- `https://app.intercom.com/ember/inbox/…` via the operator's session cookies (`credentials: 'include'`, host permission granted in `manifest.json`).

### Files

```
extension/
├── manifest.json     MV3 — popup + service worker + host_permissions (3 origins)
├── background.js     Service worker — chrome.alarms ticker, ingest + badge
├── intercom.js       Session-cookie scraper for Intercom's ember/ endpoints
├── api.js            Backend client — fetchSettings, ingestTickets, getStoredTickets, …
├── popup.html        Popup markup (tabs + list + footer)
├── popup.css         Popup styles (mirrors webapp's broadsheet aesthetic)
├── popup.js          Popup controller — render + state + alarm tick
└── icons/            Toolbar icons (16/32/48/128)
```

### Data flow

```
                  Intercom (browser session, ember/ API)
                        │  list + detail per state
                        ▼
   ┌──────────────────────────────────────┐
   │ fetchHydratedBatch + closure pass    │  background.js / popup.js
   │   ↳ skip if summary.last_updated     │
   │     ≤ knownState[id]                 │
   └──────────────────┬───────────────────┘
                      │ HydratedTicket[]
                      ▼
              POST /tickets/ingest          api.js → backend
                      │
                      ▼ (server categorizes, stores)
              GET /tickets → render          api.js → popup mini-board
              GET /tickets?resolved=true     resolved tab
              GET /categories                tabs + move-picker
              GET /followups                 due banner + countdown chip
              GET /settings                  lookback / states / mute_alarms
              PATCH /tickets/{id}/category   tap-to-move
              POST /tickets/{id}/resolve     ✓ Resolve button
              POST /tickets/{id}/reopen      ↺ Reopen button
              POST /followups/{id}/mark-fired  alarm dedupe
```

### Sync pipeline

`fetchHydratedBatch({ appId, state, count, concurrency, knownState })`:

1. `listConversations` → page of summaries (newest-first, sorted by `sorting_updated_at`).
2. Per summary: if `summaryUpdatedMs(summary) <= Date.parse(knownState[id])` → skip (no detail fetch, no AI call).
3. Otherwise: `getConversation(appId, summary.id)` → `normalizeConversation` → push to result.
4. Concurrency-bounded worker pool (default 4 parallel detail fetches).
5. Per-conversation errors are logged + skipped; auth errors (401/403) bubble as `IntercomSessionError` so the popup can surface the login hint.

`background.js:ingestFromIntercom` calls `fetchHydratedBatch` once per `settings.states` value (default `['open']`), then runs the **closure pass**: for every backend-tracked id that isn't in the open list, search `listClosedConversations` until found or the lookback window (`LOOKBACK_SECONDS = 7 days`) is exhausted. Found ids are hydrated and included in the ingest so the backend's `_upsert_ticket` stamps `resolved_at` / `resolved_source = 'intercom_closed'`.

### Background polling

OFF by default (`pollMinutes = 0`). The popup writes a value to `chrome.storage.local.pollMinutes` and sends `{ type: 'reschedule' }` to the service worker, which clears the alarm and (if `> 0`) creates a new one + does one immediate tick.

Each `poll()`:
1. `fetchSettings()`.
2. `ingestFromIntercom(settings)` — best-effort; errors leave the badge stale.
3. `fetchCategories()` + `getStoredTickets()` → count Urgent → write to `chrome.action` badge.

### Popup state model

`popup.js:state` is a plain object:
```
{ categories, proposals, tickets, resolvedTickets, followups,
  muteAlarms, now, dismissed, activeTab, error, loading }
```

`render*` functions reconcile the DOM. The 1Hz `alarmTick` updates `state.now`, refreshes countdown chips in place via `chipRefs` / `cardRefs` maps, and pings audio + marks fired follow-ups via `markFollowupFired(id)`.

`chipRefs` + `cardRefs` are rebuilt on every full `renderList` — don't try to keep them across renders.

## Conventions

- ES modules; `import` / `export` syntax (the service worker is `type: "module"` for this reason).
- `async` / `await` — no `.then()` chains except for the message-listener `sendResponse` pattern.
- JSDoc on exported functions. No JSDoc on internal helpers unless the shape is non-obvious.
- Errors that should bubble use named subclasses (`IntercomSessionError`, `ApiError`); otherwise `console.warn` + degrade silently is the rule for background work.
- Audio cues use `AudioContext` lazily — `audioCtx` is created on first ping (must be after a user gesture in some Chrome versions). Don't pre-warm it at module load.
- `FULL_BOARD_URL = 'http://localhost:5173/'` is the canonical link to the webapp from the popup. Don't hardcode it elsewhere.
- Use `encodeURIComponent` on every ticket id in URL paths (`api.js` does this consistently — match it).

## Don't

- Don't add an Intercom Access Token path. Session-cookie scraping is the only ingestion model.
- Don't introduce a build tool / bundler / TypeScript. The repo invariant is "plain ES modules, no transpile."
- Don't widen `host_permissions`. The three origins listed are the complete attack surface.
- Don't read or write to a `chrome.storage.local` key without documenting it under "Architecture → chrome.storage.local" above.
- Don't poll the backend more than once per minute (Chrome alarms clamp anyway, but plan for it).
- Don't strip the `credentials: 'include'` on Intercom fetches — that's how the operator's session cookie reaches the server.
- Don't feed `internal_notes[]` into anything fed to the backend's AI prompt path. Backend rules already guard this — extension just needs to keep the two arrays separate in the normalized output.
- Don't cache hydrated tickets in the popup across sessions. The backend is the source of truth; the popup re-reads `GET /tickets` on open.

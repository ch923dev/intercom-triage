# CLAUDE.md

Guidance for Claude Code when working in `extension/`.

> Principles: see [`../docs/principles.md`](../docs/principles.md) (Think Before Coding · Simplicity First · Surgical Changes · Goal-Driven Execution). Below = extension-specific overrides + reference only.

## 1. Think Before Coding (in this repo)

- **The extension no longer touches Intercom.** The backend polls Intercom directly with an Access Token (cross-package invariant #1). The extension is a **read-only mini-board + toolbar badge** over the backend (`localhost:4000`). There is no Intercom fetch, no `app.intercom.com` host permission, no workspace `app_id` setup. If you're tempted to add Intercom access back here, stop — it lives in `backend/app/clients/intercom.py`.
- The popup reads the backend board (`GET /tickets`, `/categories`, `/followups`, …) and mutates through the same API (override / resolve / park / reopen). It is a thin client; the source of truth is the backend.
- There is **no Sync button** — the backend's background poller keeps the board fresh. A manual one-shot exists only as `POST /tickets/sync` (curl/scripts), not in the popup.
- `parts[]` / `internal_notes[]` separation (invariant #4) is enforced backend-side now; the popup just displays what `GET /tickets` returns.

## 2. Simplicity First (in this repo)

- **No build step.** Plain ES modules loaded by MV3 (`background.service_worker.type = "module"`, `<script type="module">` in `popup.html`). Don't introduce webpack / rollup / TypeScript / a bundler. Don't add npm dependencies. Plain `.js` files only.
- **No frameworks.** Popup DOM is built with `node(tag, className, text)` + `element.append(...)`. Don't introduce Vue / React / Preact / lit. The webapp is the place for a framework; this popup is intentionally minimal.
- One `api.js` (backend client). One `background.js` (service worker, badge only). One `popup.js` (mini-board controller). Don't carve a fourth module unless a new surface justifies it.
- The popup polls in-memory state at 1Hz via `alarmTick`. Don't replace it with reactive state, observables, or a store layer. A `state` object + targeted `render*` functions is the pattern.
- Permissions in `manifest.json` are deliberately narrow: `storage`, `alarms`, and host permissions for `127.0.0.1:4000` / `localhost:4000` only. Don't add `tabs`, `cookies`, `webRequest`, `app.intercom.com`, or broader hosts — the extension never calls Intercom.

## 3. Surgical Changes (in this repo)

- Style: 2-space indent, single quotes, trailing commas, semicolons, `const`/`let` only, JSDoc on exported functions. Match it.
- Service worker is `type: "module"` — use `import` / `export`, not `importScripts`. The service worker may be killed and restarted between alarms; nothing persists across ticks except `chrome.storage.local`. Don't add module-level state that you expect to survive (counters, caches, timers).
- `chrome.storage.local` is the only persistence. Current key: `pollMinutes` (badge-refresh interval). Document any new key in this file before adding it.
- `chrome.alarms` minimum period in production builds is 1 minute — values < 1 are silently clamped. Don't add sub-minute polling.
- Backend client lives in `api.js`. Don't inline `fetch(API_BASE + …)` into `popup.js` / `background.js`.
- The `HydratedTicket`/board shape is owned by the backend (`backend/app/schemas.py`); the popup only reads `GET /tickets`. Don't reintroduce an extension-side normalizer.
- The skip-known optimization + the open→closed closure pass now live in the backend (`backend/app/services/sync.py`). The extension has no part in ingestion.

## 4. Goal-Driven Execution (in this repo)

Examples of verifiable goals (no automated test suite for the extension — every change is verified manually):
- "Fix the popup not loading" → "Open the popup, see N tickets render."
- "Refresh the badge" → "Set interval in popup footer, wait ≥ 1 tick, check toolbar Urgent count."

Verification table:

| Change                          | Verify with                                                                 |
|---------------------------------|-----------------------------------------------------------------------------|
| `popup.js` UI                   | `chrome://extensions` → reload → open popup → click through                  |
| `background.js` badge poll      | Set interval in popup footer → wait ≥ 1 tick → check toolbar badge          |
| Board shape change              | Backend owns `GET /tickets`; the popup just reads it — no extension ship     |
| Manifest / permission change    | Reload unpacked — Chrome surfaces permission deltas in a confirm dialog     |

---

# Reference

## Install (unpacked)

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. **Load unpacked** → select this `extension/` folder.

Reload after every code change — Chrome doesn't watch files. (Right-click extension icon → Manage → reload icon, or the refresh arrow on the `chrome://extensions` card.)

No setup screen — the operator points the backend at Intercom (`INTERCOM_ACCESS_TOKEN` in `backend/.env`); the popup just needs the backend running on `:4000`.

## Architecture

Manifest V3 extension. One popup window, one service worker. Talks to the backend on `http://127.0.0.1:4000` only (CORS-allowed via `chrome-extension://[a-z]{32}` regex in `backend/app/main.py`). It does **not** talk to Intercom — the backend does that.

### Files

```
extension/
├── manifest.json     MV3 — popup + service worker + host_permissions (backend only)
├── background.js     Service worker — chrome.alarms ticker, badge refresh
├── api.js            Backend client — fetchSettings, getStoredTickets, resolve/park/…
├── popup.html        Popup markup (tabs + list + footer)
├── popup.css         Popup styles (mirrors webapp's broadsheet aesthetic)
├── popup.js          Popup controller — render + state + alarm tick
└── icons/            Toolbar icons (16/32/48/128)
```

### Data flow

```
   Intercom ──(Access Token)──> BACKEND poller   (no extension involvement)
                                     │ stores the categorized board
                                     ▼
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

### Background polling (badge only)

OFF by default (`pollMinutes = 0`). The popup writes a value to `chrome.storage.local.pollMinutes` and sends `{ type: 'reschedule' }` to the service worker, which clears the alarm and (if `> 0`) creates a new one + does one immediate tick. The backend — not this alarm — keeps the board fresh; the alarm only refreshes the toolbar badge.

Each `poll()`:
1. `fetchCategories()` + `getStoredTickets()` → count Urgent → write to `chrome.action` badge.

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

- Don't give the extension Intercom access. Ingestion lives in `backend/app/clients/intercom.py`; the popup is a backend client only.
- Don't introduce a build tool / bundler / TypeScript. The repo invariant is "plain ES modules, no transpile."
- Don't widen `host_permissions`. The backend origins (`127.0.0.1:4000` / `localhost:4000`) are the complete attack surface — no `app.intercom.com`.
- Don't read or write to a `chrome.storage.local` key without documenting it under "Architecture → chrome.storage.local" above.
- Don't poll the backend more than once per minute (Chrome alarms clamp anyway, but plan for it).
- Don't cache tickets in the popup across sessions. The backend is the source of truth; the popup re-reads `GET /tickets` on open.

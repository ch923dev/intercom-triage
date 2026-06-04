# Chrome Extension — Intercom Triage

Manifest V3 popup mini-board over the backend at `http://localhost:4000`. It is
**read-only with respect to Intercom** — ingestion is the backend's job (it polls
Intercom directly with an Access Token). The popup reads `GET /tickets` and
mutates via the same API; the background alarm only refreshes the toolbar badge.

## Layout

```
extension/
├── manifest.json     MV3 manifest — popup + service worker + host_permissions (backend only)
├── background.js     Service worker — alarm-driven badge refresh
├── api.js            Shared backend client (tickets, categories, followups…)
├── popup.html        Popup mini-board markup
├── popup.css         Popup styles
├── popup.js          Popup controller (mini-board, resolved tab, alarms)
└── icons/            Toolbar icons
```

## Install (unpacked)

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. **Load unpacked** → select this `extension/` folder.

## Features

- Mini-board with the same category taxonomy as the webapp.
- Always-on **Resolved** tab + ✓ / ↩ resolve/reopen actions.
- Follow-up alarm mirror — due banner, per-row countdown chip, audio cue,
  shared mute via `GET /settings`.
- Background polling (off by default) updates the toolbar badge with the
  Urgent count when enabled (reads the backend board — it does not fetch from
  Intercom).

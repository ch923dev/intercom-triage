# Chrome Extension — Intercom Triage

Manifest V3 popup mini-board + background sync. Scrapes Intercom conversations
via the operator's logged-in browser session (no Access Token) and ships
them to the backend at `http://localhost:8000` via `POST /tickets/ingest`.

## Layout

```
extension/
├── manifest.json     MV3 manifest — popup + service worker + host_permissions
├── background.js     Service worker — alarms (sync + badge poll)
├── intercom.js       Browser-session scraper (workspace ember/ endpoints)
├── api.js            Shared backend client (ingest, categories, followups…)
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
  Urgent count when enabled.

# Webapp — Intercom Triage

Vue 3 + Vite + TypeScript SPA. Calls the backend at `http://127.0.0.1:8000`
via Vite's dev proxy on `/api/*`.

## Layout

```
webapp/
├── index.html               Loads Geist + JetBrains Mono
├── package.json             Pinned deps
├── tsconfig.json            Strict mode + path alias `@/*`
├── vite.config.ts           Dev proxy → 127.0.0.1:8000
└── src/
    ├── main.ts              Pinia + App mount
    ├── App.vue              Top bar + board + footer shell + alarm loop
    ├── api/client.ts        Typed fetch wrapper for every backend endpoint
    ├── components/
    │   ├── AlarmBanners.vue Follow-up due banner stack
    │   ├── Board.vue        Horizontal scroll of columns
    │   ├── CatDot.vue       8px category swatch
    │   ├── CategoriesPage.vue   Category management UI
    │   ├── Column.vue       Header + draggable cards
    │   ├── ExtensionCallout.vue Banner + empty-state placeholder
    │   ├── Mono.vue         Mono micro-label
    │   ├── ProposalsPage.vue    Pending AI proposal review
    │   ├── SettingsDrawer.vue   Right-side filter drawer
    │   ├── TicketCard.vue   Card per plan §8b
    │   ├── TicketFlyout.vue Detail flyout with follow-up + notes
    │   └── Topbar.vue       Wordmark + tweaks + status pill
    ├── stores/
    │   ├── categories.ts    Active categories + pending proposals
    │   ├── followups.ts     Per-ticket reminders + tick loop
    │   ├── notes.ts         Per-ticket next-step notes
    │   ├── settings.ts      FilterSettings (server-backed; carries mute_alarms)
    │   ├── tickets.ts       Stored board + optimistic overrides
    │   ├── tweaks.ts        Dark mode + accent + density + toggles (localStorage)
    │   └── view.ts          Active page + flyout selection + drawer
    ├── styles/tokens.css    Design tokens — plan §8b
    ├── types/api.ts         Mirror of plan §3 data contracts
    └── utils/time.ts        formatAgo + formatCountdown helpers
```

## Run

```powershell
npm install
npm run dev               # → http://127.0.0.1:5173
```

Backend must be running on `127.0.0.1:8000` (see `../scripts/dev-backend.ps1`).

## Data flow

The board reads from `GET /tickets` — the **stored** board the Chrome extension
ingests into via `POST /tickets/ingest`. There is no Intercom Access Token in
this build, so the extension is the only path that fetches conversations.
First run on a fresh DB shows an empty-state callout pointing at the extension;
once the operator clicks Sync in the popup, the board fills.

## Scripts

| Action          | Command              |
|-----------------|----------------------|
| dev server      | `npm run dev`        |
| typecheck       | `npm run typecheck`  |
| production build| `npm run build`      |
| preview build   | `npm run preview`    |
| format          | `npm run format`     |
| format check    | `npm run format:check` |

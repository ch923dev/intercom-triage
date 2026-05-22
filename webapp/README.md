# Webapp — Intercom Triage

Vue 3 + Vite + TypeScript SPA. Calls the backend at `http://127.0.0.1:8000`
via Vite's dev proxy on `/api/*`.

**Status:** Phase 6 partial — T029 (scaffold), T030 (API client), T031 (Pinia
stores), T032 (Kanban layout), T033 (TicketCard), T034 (drag override) done.
T035 (settings drawer), T036 (toolbar + keyboard), T037 (category mgmt page),
T038 (proposals page), T039 (extension callout) pending.

## Layout

```
webapp/
├── index.html               Loads Geist + JetBrains Mono
├── package.json             Pinned deps
├── tsconfig.json            Strict mode + path alias `@/*`
├── vite.config.ts           Dev proxy → 127.0.0.1:8000
└── src/
    ├── main.ts              Pinia + App mount
    ├── App.vue              Top bar + board + footer shell
    ├── api/client.ts        Typed fetch wrapper for every backend endpoint
    ├── components/
    │   ├── Board.vue        Horizontal scroll of columns
    │   ├── CatDot.vue       8px category swatch
    │   ├── Column.vue       Header + draggable cards
    │   ├── Mono.vue         Mono micro-label
    │   ├── TicketCard.vue   Card per plan §8b
    │   └── Topbar.vue       Wordmark + tweaks toggles
    ├── mock/sampleTickets.ts  Sample ports of the design's data.js
    ├── stores/
    │   ├── categories.ts    Active categories + pending proposals
    │   ├── settings.ts      FilterSettings (localStorage v1, server later)
    │   ├── tickets.ts       Fetched tickets + optimistic overrides
    │   └── tweaks.ts        Dark mode + accent + density + toggles
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

## Mock vs live

`/tickets/fetch` doesn't exist on the backend yet (T025). When the request
404s, `useTicketsStore` falls back to the design's sample data; the top bar
shows a `Mock data` badge so the state is visible. Once T025 lands, the badge
disappears automatically — no code change.

## Scripts

| Action          | Command              |
|-----------------|----------------------|
| dev server      | `npm run dev`        |
| typecheck       | `npm run typecheck`  |
| production build| `npm run build`      |
| preview build   | `npm run preview`    |
| format          | `npm run format`     |
| format check    | `npm run format:check` |

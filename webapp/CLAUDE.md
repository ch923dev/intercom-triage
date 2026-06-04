# CLAUDE.md

Guidance for Claude Code when working in `webapp/`.

> Principles: see [`../docs/principles.md`](../docs/principles.md) (Think Before Coding · Simplicity First · Surgical Changes · Goal-Driven Execution). Below = webapp-specific overrides + reference only.

## 1. Think Before Coding (in this repo)

- Backend contracts live in `src/types/api.ts` + `src/api/client.ts`. If a field's nullability or PATCH/PUT shape is unclear, check `../docs/contract/plan.md` / `../docs/contract/spec.md` or ask — never guess a wire format.
- `ConversationPart.is_admin` comes from the official Intercom `part_type` + author type (mapped backend-side in `intercom_normalizer.py`); `note` parts live in `Ticket.internal_notes`, never `parts`. Flag any contract change.
- The **backend** polls Intercom directly (Access Token in `backend/.env`); the webapp never touches Intercom. An empty board means "no token / nothing synced yet" (check `/health.intercom_configured`), not "fetch failed." Don't add fallbacks or mock data.

## 2. Simplicity First (in this repo)

- The `tickets` store is ~500 lines of optimistic-update logic. Don't wrap it in a helper layer "in case." New mutating actions go inline alongside `applyOverride` / `markResolved` / `bulkResolve`.
- One `api` object in `src/api/client.ts` — never inline `fetch` in components.
- No router. Views switch via `view.view` in `App.vue`. Don't introduce vue-router for "future flexibility."
- Default to no comments. Existing `tasks.md TXXX` / `plan §X` markers point at external specs; don't echo what the code already says.

## 3. Surgical Changes (in this repo)

- Style: single-word component names (`Topbar`, `Board`, `Column`), `import type { … }` (verbatimModuleSyntax), two-space indent, trailing commas, `@/` path alias, prettier `printWidth: 100`.
- `vue/multi-word-component-names` is disabled on purpose. Don't rename components.
- Two vite configs (`vite.config.ts` + `vitest.config.ts`) are intentional — merging them breaks `vue-tsc`. Don't consolidate.
- **Any UI / CSS / component change must conform to `DESIGN.md`.** That file is the design-system source of truth (palette, type scale, radii, spacing, component tokens, do's/don'ts). Use `var(--*)` tokens from `src/styles/tokens.css`; never hardcode hex or px values that exist as tokens. If a new component needs a token that isn't in `DESIGN.md`, propose the token there first.
- `notes` (legacy) and `noteEntries` (time-tabled, successor) coexist. Don't delete `notes` without being asked.

## 4. Goal-Driven Execution (in this repo)

Verification commands:

| Change                          | Verify with                                                |
|---------------------------------|------------------------------------------------------------|
| Store / pure logic              | Add or update `src/**/*.spec.ts`; `npm test` green         |
| UI / view / flyout              | `npm run dev`, exercise the click-path against live backend; cross-check colors/type/radii/spacing vs `DESIGN.md` |
| New component / restyle         | Tokens from `DESIGN.md` only (use `var(--*)` from `src/styles/tokens.css`); add to `DESIGN.md` components table if it introduces a reusable pattern |
| Type or API-contract change     | `npm run typecheck` clean                                  |
| Any merge-ready change          | `npm run lint` (zero-warning gate) + `npm run format:check`|

---

# Reference

## Commands

```powershell
npm install
npm run dev               # Vite dev server on http://127.0.0.1:5173 (strictPort)
npm run typecheck         # vue-tsc --noEmit
npm run build             # typecheck + vite build → dist/
npm run preview           # serve dist/
npm run lint              # eslint . --max-warnings 0
npm run lint:fix
npm run format            # prettier write src/**/*.{ts,vue,css}
npm run format:check
npm test                  # vitest run (happy-dom, src/**/*.spec.ts)
npm run test:watch
npx vitest run src/stores/selection.spec.ts     # single test file
npx vitest run -t "addRange"                    # single test by name
```

Dev server requires backend on `127.0.0.1:4000` — Vite proxies `/api/*` with the `/api` prefix stripped. Start backend + webapp together via `../scripts/dev.ps1` (Windows Terminal split-pane launcher).

## Architecture

Vue 3 + Pinia + TypeScript SPA. One page, multiple "views" toggled via `view.view`: `board` / `followups` / `categories` / `proposals`. No router — `App.vue` is the shell and switches the active component.

### Data-flow pivot

The **backend** polls Intercom's official `api.intercom.io` REST API with an Access Token (`backend/app/services/sync.py`) — no extension or browser involvement. The webapp only reads from the stored `tickets` table via `GET /tickets`.

Consequences:
- Empty DB → `ExtensionCallout mode="empty"` tells the operator the board is empty. The actionable cause is now "no token / nothing synced yet" (`/health.intercom_configured`), not "open the extension and sync." Never mock data. (Copy may still mention the extension as a quick-glance board — it's no longer the ingestion path.)
- `tickets.refresh()` failure leaves the board empty and surfaces the error inline — no retry, no fallback.
- `ConversationPart.is_admin` comes from the backend normalizer's `part_type` + author-type mapping; `note` parts live in `Ticket.internal_notes`, never `parts`.

### State: Pinia stores (`src/stores/`)

Loaded in `App.vue:onMounted` in order: `settings` → `categories` → (`followups`, `notes`, `noteEntries` parallel) → `tickets`. Components import stores directly; no prop drilling.

- `tickets` — board source of truth. Two parallel lists (`tickets` = open, `resolvedTickets`) + `pendingOverrides`. `visibleTickets` filters by `query`; `byCategory`/`byProposal` derive from filtered list (search narrows columns); `byId` walks raw list (flyouts resolve filtered-out rows).
- `settings` — server-backed `FilterSettings` (lookback, states, AI flags, `mute_alarms`).
- `tweaks` — client-only (`localStorage`): dark mode, accent, density, `autoSyncSeconds`, `desktopNotifications`.
- `categories` — active categories + pending AI proposals.
- `followups` — per-ticket reminders + 1Hz tick loop. `tick()` returns fired ids → audio ping (gated by `settings.muteAlarms`) + desktop notifications (gated by `tweaks.desktopNotifications`).
- `notes` — legacy single-body per-ticket note.
- `noteEntries` — time-tabled entries (successor to `notes`).
- `attachments` — multipart uploads bypass the JSON `request()` helper.
- `selection` — bulk-select set + `lastAnchor` for shift-range. Drives `BulkActionBar`.
- `view` — active view + flyout `selectedTicketId` + drawer open state.

### Optimistic-update pattern

Mutating actions (`applyOverride`, `markResolved`, `reopen`, `editTicket`, all `bulk*`): snapshot prior state → mutate locally → call API → restore from snapshot on failure. Bulk actions handle partial failure: server returns `{ ok_ids, failed[] }` and the store rolls back only `failed`. Match this pattern when adding new mutating actions.

### Auto-sync loop

`App.vue` arms a `setInterval` from `tweaks.autoSyncSeconds` calling `tickets.silentRefresh()` (no `loading=true`, no banner flicker). Skips ticks when `document.hidden` or when a manual refresh is in flight. Re-armed via `watch`; immediate silent refresh fires on `visibilitychange → visible`.

### Components

`src/components/` is mostly flat. Subfolders for the two largest:
- `components/ticket/` — pieces of `TicketFlyout.vue`.
- `components/settings/` — per-section `SettingsDrawer.vue` panels.

## Conventions

- Path alias `@/*` → `src/*` (tsconfig + both vite configs).
- `verbatimModuleSyntax: true` — use `import type { … }` for type-only imports.
- Strict TS: `noUnusedLocals`, `noUnusedParameters`. Unused params → `_` prefix or remove.
- Design tokens in `src/styles/tokens.css`, switched by `html[data-theme]` and inline `--accent`. Use tokens; never hardcode colors.
- `--max-warnings 0` — warnings fail lint.

## Tests

Vitest + happy-dom + `@vue/test-utils`. Files colocated as `*.spec.ts` under `src/`. Coverage is store-focused (`stores/*.spec.ts`).

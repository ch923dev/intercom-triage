# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

These four principles override defaults. Follow them on every change.

## 1. Think Before Coding

Don't assume. Don't hide confusion. Surface tradeoffs.

- State assumptions explicitly before touching code. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

In this repo:
- Backend contracts live in `src/types/api.ts` + `src/api/client.ts`. If a field's nullability or PATCH/PUT shape is unclear, check `../plan.md` / `../spec.md` or ask — never guess a wire format.
- The Intercom `renderable_type` mapping (1/12 customer, 2/24 admin, 3 internal note) is reverse-engineered and unstable. Flag any change.
- The backend has **no Intercom Access Token**. All ticket data arrives via the Chrome extension POSTing to `/tickets/ingest`. An empty board means "operator hasn't synced," not "fetch failed." Don't add fallbacks or mock data.

## 2. Simplicity First

Minimum code that solves the problem. Nothing speculative.

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If 200 lines could be 50, rewrite it.

In this repo:
- The `tickets` store is ~500 lines of optimistic-update logic. Don't wrap it in a helper layer "in case." New mutating actions go inline alongside `applyOverride` / `markResolved` / `bulkResolve`.
- One `api` object in `src/api/client.ts` — never inline `fetch` in components.
- No router. Views switch via `view.view` in `App.vue`. Don't introduce vue-router for "future flexibility."
- Default to no comments. Existing `tasks.md TXXX` / `plan §X` markers point at external specs; don't echo what the code already says.

## 3. Surgical Changes

Touch only what you must. Clean up only your own mess.

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.
- Remove imports/variables your change made unused. Don't remove pre-existing dead code unless asked.

In this repo:
- Style: single-word component names (`Topbar`, `Board`, `Column`), `import type { … }` (verbatimModuleSyntax), two-space indent, trailing commas, `@/` path alias, prettier `printWidth: 100`.
- `vue/multi-word-component-names` is disabled on purpose. Don't rename components.
- Two vite configs (`vite.config.ts` + `vitest.config.ts`) are intentional — merging them breaks `vue-tsc`. Don't consolidate.
- **Any UI / CSS / component change must conform to `DESIGN.md`.** That file is the design-system source of truth (palette, type scale, radii, spacing, component tokens, do's/don'ts). Use `var(--*)` tokens from `src/styles/tokens.css`; never hardcode hex or px values that exist as tokens. If a new component needs a token that isn't in `DESIGN.md`, propose the token there first.
- `notes` (legacy) and `noteEntries` (time-tabled, successor) coexist. Don't delete `notes` without being asked.

The test: every changed line traces directly to the user's request.

## 4. Goal-Driven Execution

Define success criteria. Loop until verified.

Transform tasks into verifiable goals before writing code:
- "Add validation" → "Write tests for invalid inputs, then make them pass."
- "Fix the bug" → "Write a test that reproduces it, then make it pass."
- "Refactor X" → "Tests pass before and after."

For multi-step work, state the plan up front:

```
1. [step] → verify: [check]
2. [step] → verify: [check]
```

Repo-specific verification commands:

| Change                          | Verify with                                                |
|---------------------------------|------------------------------------------------------------|
| Store / pure logic              | Add or update `src/**/*.spec.ts`; `npm test` green         |
| UI / view / flyout              | `npm run dev`, exercise the click-path against live backend; cross-check colors/type/radii/spacing vs `DESIGN.md` |
| New component / restyle         | Tokens from `DESIGN.md` only (use `var(--*)` from `src/styles/tokens.css`); add to `DESIGN.md` components table if it introduces a reusable pattern |
| Type or API-contract change     | `npm run typecheck` clean                                  |
| Any merge-ready change          | `npm run lint` (zero-warning gate) + `npm run format:check`|

"Make it work" is not a success criterion. Name the test, the click-path, or the command whose output proves the change.

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

No Intercom Access Token. Backend cannot call `api.intercom.io`. The sibling Chrome extension (`../extension/`) scrapes Intercom's internal Ember API using the operator's logged-in session and POSTs to `/tickets/ingest`. The webapp only reads from the stored `tickets` table via `GET /tickets`.

Consequences:
- Empty DB → `ExtensionCallout mode="empty"` tells the operator to sync. Never mock data.
- `tickets.refresh()` failure leaves the board empty and surfaces the error inline — no retry, no fallback.
- `ConversationPart.is_admin` derives from Intercom `renderable_type`; internal notes (type 3) live in `Ticket.internal_notes`, never `parts`.

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

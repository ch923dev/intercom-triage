# Follow-up board + desktop notifications — design

**Date:** 2026-05-23
**Status:** Approved

## Problem

Follow-ups currently surface only as transient alarm banners and a topbar count
pill. There is no dedicated view to see every pending follow-up at once, and no
notification when the operator's browser tab is not focused — a follow-up can
come due unseen.

This adds:

1. A dedicated kanban view for follow-ups, columns bucketed by time-to-due.
2. Optional desktop (browser `Notification`) alerts when a follow-up fires.

## Scope

In scope: a new `followups` view + components, a notification utility + settings
toggle, a `byId` getter on the tickets store.

Out of scope: drag-to-reschedule on the follow-up board; service-worker
scheduled notifications; adding a frontend test runner; any backend change.

## A. Follow-up board (new view)

### Navigation

- `webapp/src/stores/view.ts`: extend the `View` type — `'board' | 'categories'
  | 'proposals' | 'followups'`.
- `Topbar.vue`: add a 4th nav button **"Follow-ups"** to the `NAV` array, with a
  count badge equal to `followups.pendingCount` (reuse the existing `.nav-badge`
  styling, as the Proposals button does).
- `App.vue`: render the new `FollowupBoard` component when `view.view ===
  'followups'`.

### Columns + bucketing

Five columns, left → right by urgency:

| Column      | Predicate |
|-------------|-----------|
| Overdue     | `fired === false` and `due_at ≤ now` |
| Within 1h   | `fired === false` and `now < due_at ≤ now + 1h` |
| Today       | `fired === false` and `now + 1h < due_at ≤ local end-of-day` |
| Later       | `fired === false` and `due_at > local end-of-day` |
| Fired       | `fired === true` |

`fired` means the alarm has rung — **not** that the follow-up is handled. A
follow-up leaves the **Fired** column only when the operator clears it (Done) or
re-snoozes it (which resets `fired` and moves it back to a time bucket).
Because `tick()` sets `fired` within ~1s of a follow-up coming due, the
**Overdue** column is normally transient (it briefly holds a follow-up between
its due moment and the next tick, e.g. right after the app loads).

Implementation:

- `followups.ts`: export a pure function
  `bucketOf(followup: Followup, nowMs: number): Bucket` where
  `Bucket = 'overdue' | 'within1h' | 'today' | 'later' | 'fired'`. Pure so it is
  unit-testable in isolation. "Local end-of-day" = a `Date` set to 23:59:59.999
  in the browser's local timezone for the current day.
- `followups.ts`: add a `buckets` computed returning
  `Record<Bucket, Followup[]>`. It depends on the existing `now` ref, so it
  re-evaluates every second along with the alarm tick.

### Cards

- New `FollowupCard.vue`. Shows: ticket id (mono), reason (if any), a countdown
  line via `formatCountdown(Date.parse(due_at) - now)`, and four buttons:
  - **Open** → `view.selectTicket(id)` (opens the flyout, jumps to the board).
  - **15m** / **1h** → `followups.snooze(id, 15 | 60)`.
  - **Done** → `followups.clearFollowup(id)` (deletes the follow-up row).
- The follow-up record carries no ticket title. The card resolves the title via
  a new `byId` getter on the tickets store. If the ticket is not loaded
  (filtered out by the lookback window, or not yet synced), the card falls back
  to showing the id + reason only — never crashes.

### Tickets store change

- `tickets.ts`: add a `byId` computed — a `Map<string, Ticket>` over
  `state.value.tickets` — and expose it. Single focused addition; consumers
  (the follow-up card) look up titles without scanning the array.

### FollowupBoard.vue

- Reuses the `.board` horizontal-scroll layout from `Board.vue`.
- Renders five column sections (header = name + count, body = scrollable card
  list). The follow-up board does not need drag, so it does **not** reuse the
  `vuedraggable`-based `Column.vue`; it renders a lighter static column inline
  or via a small `FollowupColumn.vue`. Empty columns show an "empty" placeholder
  consistent with `Column.vue`.

## B. Desktop notifications

### Notification utility

New `webapp/src/utils/notify.ts`:

- `supported(): boolean` — `'Notification' in window`.
- `permission(): NotificationPermission` — current `Notification.permission`.
- `requestPermission(): Promise<NotificationPermission>` — wraps
  `Notification.requestPermission()`.
- `notify(title: string, body: string, tag: string, onClick: () => void): void`
  — constructs `new Notification(title, { body, tag })` only when permission is
  `'granted'`; `tag` is the ticket id so a re-fire for the same ticket replaces
  the prior notification rather than stacking. The `onClick` handler runs
  `window.focus()` then the supplied callback, and closes the notification.

### Preference storage

- The enable/disable preference lives in the **tweaks store**
  (`webapp/src/stores/tweaks.ts`, localStorage) as a new field
  `desktopNotifications: boolean`, default `false`.
- Rationale: the browser permission grant is already per-browser/origin, so the
  preference is inherently per-machine. A backend `settings` column would force
  another additive migration for a flag nothing else reads. (`mute_alarms` stays
  backend because the extension popup shares it; notifications do not.)
- Extend `TweaksState`, `DEFAULTS`, add a `setDesktopNotifications` action and a
  `desktopNotifications` computed. The existing persistence `watch` covers it.

### Settings drawer

- `SettingsDrawer.vue`: add a **"Desktop notifications"** checkbox near the
  existing mute control.
- Toggling **on**:
  - If `!supported()` → keep it off, show an inline hint ("This browser does not
    support notifications").
  - If permission is `'default'` → call `requestPermission()`; set the
    preference on `'granted'`, otherwise revert the checkbox and show a hint
    ("Notifications blocked — allow them in browser site settings").
  - If permission already `'granted'` → just set the preference.
- Toggling **off**: clears the preference; no browser call.

### Firing

- `App.vue` `alarmTick()` already receives `newlyFired: string[]` from
  `followups.tick()`. After the existing audio-ping logic, for each newly-fired
  ticket id, if `tweaks.desktopNotifications` is on and `permission() ===
  'granted'`, call `notify(...)`:
  - title: `Follow-up due — <ticket id>`
  - body: the follow-up `reason`, or `No reason given` when null.
  - tag: the ticket id.
  - onClick: `view.selectTicket(id)`.
- The in-app banner and audio cue are unchanged — the desktop notification is an
  additional channel, gated independently of `mute_alarms`.

## C. Timing accuracy

The alarm loop is a 1s `setInterval` in `App.vue`. Browsers throttle timers in
**backgrounded tabs** to roughly once per minute. Consequence: while the tab is
hidden, a notification can fire up to ~60s after the true due time.

This is acceptable for minute-scale human follow-ups and needs no code change:
`tick()` already raises every follow-up whose `due_at ≤ now` and `fired ===
false`, so the first tick after the tab regains focus (or the first throttled
tick) catches all missed follow-ups at once — none are dropped, only delayed.

Explicitly **not** doing: service-worker `showTrigger` scheduled notifications.
That API is experimental and Chrome-only, and the operator keeps the tab open in
normal use — the cost outweighs shaving the ≤60s background delay.

## D. Error handling

- Notification construction is wrapped so a throwing `Notification` constructor
  (some browsers throw if invoked without an active document) never breaks the
  alarm tick — failure is swallowed; the in-app banner still shows.
- `clearFollowup` / `snooze` from a follow-up card reuse the store actions,
  which already roll back optimistic state on a backend error.
- A follow-up card for an unknown ticket id degrades gracefully (id + reason).

## E. Testing

- Backend: no change — the follow-up API and passive store are already covered.
- Frontend: no test runner is configured. Verification:
  - `npm run typecheck` and `npm run build` must pass.
  - Manual: set a follow-up ~1 min out → card appears in **Within 1h** → moves
    to **Fired** when due; snooze 15m → card returns to a time bucket; Done →
    card disappears. Enable desktop notifications, deny vs grant permission
    paths, confirm a notification fires on due and its click focuses the tab and
    opens the flyout.
  - `bucketOf` is a pure exported function, unit-testable if a runner is added
    later (out of scope here).

## Files touched

| File | Change |
|------|--------|
| `webapp/src/stores/view.ts` | add `'followups'` to `View` |
| `webapp/src/stores/followups.ts` | export `bucketOf`, add `buckets` computed |
| `webapp/src/stores/tickets.ts` | add `byId` getter |
| `webapp/src/stores/tweaks.ts` | add `desktopNotifications` field + action |
| `webapp/src/utils/notify.ts` | **new** — Notification API wrapper |
| `webapp/src/components/FollowupBoard.vue` | **new** — the view |
| `webapp/src/components/FollowupColumn.vue` | **new** — static column |
| `webapp/src/components/FollowupCard.vue` | **new** — card |
| `webapp/src/components/Topbar.vue` | add "Follow-ups" nav button |
| `webapp/src/components/SettingsDrawer.vue` | add notifications checkbox |
| `webapp/src/App.vue` | render `FollowupBoard`; fire notifications in `alarmTick` |

# Follow-up Board + Desktop Notifications Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated time-bucketed kanban view for follow-ups and optional browser desktop notifications when a follow-up fires.

**Architecture:** All changes are in the Vue 3 webapp — no backend change. A new `followups` view renders a 5-column board (Overdue / Within 1h / Today / Later / Fired) driven by a pure `bucketOf` function in the follow-ups store. Desktop notifications are a thin wrapper over the browser `Notification` API, gated by a localStorage preference in the tweaks store and fired from the existing once-per-second alarm tick in `App.vue`.

**Tech Stack:** Vue 3 (`<script setup>`), Pinia, TypeScript, Vite. No frontend test runner exists — every task verifies with `npm run typecheck` (run inside `webapp/`).

**Working directory note:** All `npm` commands run from `F:\Claude Projects\niche\intercom-ticket-management\webapp`. All file paths below are repo-relative.

---

## File Structure

| File | Responsibility | New? |
|------|----------------|------|
| `webapp/src/stores/view.ts` | add `'followups'` to the `View` union | modify |
| `webapp/src/stores/tickets.ts` | add `byId` Map getter for title lookup | modify |
| `webapp/src/stores/tweaks.ts` | add `desktopNotifications` preference | modify |
| `webapp/src/utils/notify.ts` | browser `Notification` API wrapper | **new** |
| `webapp/src/stores/followups.ts` | `bucketOf` + `buckets` grouping | modify |
| `webapp/src/components/FollowupCard.vue` | one follow-up card with actions | **new** |
| `webapp/src/components/FollowupColumn.vue` | one static board column | **new** |
| `webapp/src/components/FollowupBoard.vue` | the 5-column view | **new** |
| `webapp/src/components/Topbar.vue` | "Follow-ups" nav button + badge | modify |
| `webapp/src/components/SettingsDrawer.vue` | desktop-notifications checkbox | modify |
| `webapp/src/App.vue` | render the board; fire notifications | modify |

Tasks are ordered so each task's `npm run typecheck` passes: stores and utilities come before the components that consume them.

---

## Task 1: Add the `followups` view

**Files:**
- Modify: `webapp/src/stores/view.ts:9`

- [ ] **Step 1: Extend the `View` union**

In `webapp/src/stores/view.ts`, change line 9 from:

```ts
export type View = 'board' | 'categories' | 'proposals';
```

to:

```ts
export type View = 'board' | 'categories' | 'proposals' | 'followups';
```

- [ ] **Step 2: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/stores/view.ts
git commit -m "Add followups value to the View union"
```

---

## Task 2: Add a `byId` getter to the tickets store

The follow-up card needs a ticket's title, but a `Followup` record carries only the ticket id. A `Map` getter gives O(1) lookup.

**Files:**
- Modify: `webapp/src/stores/tickets.ts`

- [ ] **Step 1: Add the `byId` computed**

In `webapp/src/stores/tickets.ts`, after the `byProposal` computed (ends at line 56), add:

```ts
  /** Every visible ticket keyed by id — for O(1) lookup by id. */
  const byId = computed(() => {
    const map = new Map<string, Ticket>();
    for (const t of state.value.tickets) map.set(t.id, t);
    return map;
  });
```

- [ ] **Step 2: Expose it from the store**

In the `return { ... }` block (starts at line 128), add `byId,` on its own line after `byProposal,`:

```ts
    byCategory,
    byProposal,
    byId,
    refresh,
```

- [ ] **Step 3: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/stores/tickets.ts
git commit -m "Add byId getter to the tickets store"
```

---

## Task 3: Add the `desktopNotifications` preference to the tweaks store

The enable/disable preference is per-browser (the `Notification` permission is per-origin), so it lives in the localStorage-backed tweaks store.

**Files:**
- Modify: `webapp/src/stores/tweaks.ts`

- [ ] **Step 1: Add the field to `TweaksState`**

In `webapp/src/stores/tweaks.ts`, change the `TweaksState` interface (lines 13-19) to:

```ts
interface TweaksState {
  darkMode: boolean;
  accent: string;
  density: Density;
  showSummary: boolean;
  showConfidence: boolean;
  desktopNotifications: boolean;
}
```

- [ ] **Step 2: Add the default**

Change the `DEFAULTS` object (lines 21-27) to:

```ts
const DEFAULTS: TweaksState = {
  darkMode: false,
  accent: '#ff4d2e',
  density: 'balanced',
  showSummary: true,
  showConfidence: true,
  desktopNotifications: false,
};
```

- [ ] **Step 3: Add the computed + setter**

After the `showConfidence` computed (line 48), add:

```ts
  const desktopNotifications = computed(() => state.value.desktopNotifications);
```

After the `setShowConfidence` function (ends at line 64), add:

```ts
  function setDesktopNotifications(v: boolean) {
    state.value.desktopNotifications = v;
  }
```

- [ ] **Step 4: Export both from the store**

In the `return { ... }` block (lines 78-90), add `desktopNotifications,` after `showConfidence,` and `setDesktopNotifications,` after `setShowConfidence,`:

```ts
  return {
    darkMode,
    accent,
    density,
    showSummary,
    showConfidence,
    desktopNotifications,
    setDarkMode,
    setAccent,
    setDensity,
    setShowSummary,
    setShowConfidence,
    setDesktopNotifications,
    ACCENT_SWATCHES,
  };
```

- [ ] **Step 5: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/stores/tweaks.ts
git commit -m "Add desktopNotifications preference to the tweaks store"
```

---

## Task 4: Create the notification utility

**Files:**
- Create: `webapp/src/utils/notify.ts`

- [ ] **Step 1: Write `notify.ts`**

Create `webapp/src/utils/notify.ts` with exactly:

```ts
// Desktop notification helper — a thin wrapper over the browser Notification
// API. The alarm loop uses it to surface a follow-up firing while the browser
// tab is not focused. The enable/disable preference lives in the tweaks store;
// this module deals only with the browser-level permission + construction.

/** True when the browser exposes the Notification API. */
export function supported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window;
}

/** Current permission state — 'denied' when notifications are unsupported. */
export function permission(): NotificationPermission {
  return supported() ? Notification.permission : 'denied';
}

/** Prompt for permission. Resolves to 'denied' when unsupported or on error. */
export async function requestPermission(): Promise<NotificationPermission> {
  if (!supported()) return 'denied';
  try {
    return await Notification.requestPermission();
  } catch {
    return 'denied';
  }
}

/**
 * Show a desktop notification. No-op unless permission is granted. `tag`
 * dedupes — a later notification with the same tag replaces the earlier one
 * rather than stacking, so a re-fired follow-up does not pile up. Wrapped in
 * try/catch: some browsers throw from the constructor, and that must never
 * break the once-per-second alarm tick.
 */
export function notify(
  title: string,
  body: string,
  tag: string,
  onClick: () => void,
): void {
  if (permission() !== 'granted') return;
  try {
    const n = new Notification(title, { body, tag });
    n.onclick = () => {
      window.focus();
      onClick();
      n.close();
    };
  } catch {
    // Swallowed — the in-app alarm banner still shows.
  }
}
```

- [ ] **Step 2: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/utils/notify.ts
git commit -m "Add browser Notification API wrapper"
```

---

## Task 5: Add bucketing to the follow-ups store

**Files:**
- Modify: `webapp/src/stores/followups.ts`

- [ ] **Step 1: Add the bucket type + helpers above the store**

In `webapp/src/stores/followups.ts`, after the `AlarmBanner` interface (ends at line 15) and before `export const useFollowupsStore`, add:

```ts
/** A follow-up board column. */
export type Bucket = 'overdue' | 'within1h' | 'today' | 'later' | 'fired';

/** Board columns, left → right by urgency. */
export const BUCKET_ORDER: Bucket[] = ['overdue', 'within1h', 'today', 'later', 'fired'];

/** Column header label per bucket. */
export const BUCKET_LABEL: Record<Bucket, string> = {
  overdue: 'Overdue',
  within1h: 'Within 1h',
  today: 'Today',
  later: 'Later',
  fired: 'Fired',
};

/**
 * The board column a follow-up belongs to at instant `nowMs`. A fired
 * follow-up (alarm already rang) sits in `fired` until cleared or re-snoozed;
 * an un-fired one is bucketed by how soon its `due_at` falls. "Today" ends at
 * local 23:59:59.999.
 */
export function bucketOf(f: Followup, nowMs: number): Bucket {
  if (f.fired) return 'fired';
  const due = Date.parse(f.due_at);
  if (due <= nowMs) return 'overdue';
  if (due <= nowMs + 3_600_000) return 'within1h';
  const endOfDay = new Date(nowMs);
  endOfDay.setHours(23, 59, 59, 999);
  if (due <= endOfDay.getTime()) return 'today';
  return 'later';
}
```

- [ ] **Step 2: Add the `buckets` computed inside the store**

In `webapp/src/stores/followups.ts`, after the `firing` computed (line 29) and before `function get(`, add:

```ts
  /** Follow-ups grouped into board columns, each column sorted by due_at
   *  ascending (most urgent first). Re-evaluates every tick via `now`. */
  const buckets = computed<Record<Bucket, Followup[]>>(() => {
    const grouped: Record<Bucket, Followup[]> = {
      overdue: [],
      within1h: [],
      today: [],
      later: [],
      fired: [],
    };
    for (const f of Object.values(map.value)) {
      grouped[bucketOf(f, now.value)].push(f);
    }
    for (const key of BUCKET_ORDER) {
      grouped[key].sort((a, b) => Date.parse(a.due_at) - Date.parse(b.due_at));
    }
    return grouped;
  });
```

- [ ] **Step 3: Export `buckets` from the store**

In the `return { ... }` block (starts at line 145), add `buckets,` after `firing,`:

```ts
    all,
    pendingCount,
    firing,
    buckets,
    get,
```

- [ ] **Step 4: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/stores/followups.ts
git commit -m "Add time-bucket grouping to the follow-ups store"
```

---

## Task 6: Create the follow-up card component

**Files:**
- Create: `webapp/src/components/FollowupCard.vue`

- [ ] **Step 1: Write `FollowupCard.vue`**

Create `webapp/src/components/FollowupCard.vue` with exactly:

```vue
<!-- One follow-up on the follow-up board. Shows the ticket id, its resolved
     title (when the ticket is loaded), the reason, a live countdown, and the
     Open / Snooze / Done actions. -->
<script setup lang="ts">
import { computed } from 'vue';
import Mono from './Mono.vue';
import { useFollowupsStore } from '@/stores/followups';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import { formatCountdown } from '@/utils/time';
import type { Followup } from '@/types/api';

interface Props {
  followup: Followup;
}
const props = defineProps<Props>();

const followups = useFollowupsStore();
const tickets = useTicketsStore();
const view = useViewStore();

/** Ticket title, or null when the ticket is not loaded (filtered out / not
 *  yet synced) — the card then shows id + reason only. */
const title = computed(() => tickets.byId.get(props.followup.ticket_id)?.title ?? null);
const countdown = computed(() =>
  formatCountdown(Date.parse(props.followup.due_at) - followups.now),
);

function open() {
  view.selectTicket(props.followup.ticket_id);
}
function snooze(minutes: number) {
  void followups.snooze(props.followup.ticket_id, minutes);
}
function done() {
  void followups.clearFollowup(props.followup.ticket_id);
}
</script>

<template>
  <article class="fu-card">
    <header>
      <Mono>{{ props.followup.ticket_id }}</Mono>
      <Mono class="countdown">{{ countdown }}</Mono>
    </header>
    <h3 v-if="title" class="title">{{ title }}</h3>
    <p v-if="props.followup.reason" class="reason">{{ props.followup.reason }}</p>
    <div class="actions">
      <button class="act primary" @click="open">Open</button>
      <button class="act" @click="snooze(15)">15m</button>
      <button class="act" @click="snooze(60)">1h</button>
      <button class="act" @click="done">Done</button>
    </div>
  </article>
</template>

<style scoped>
.fu-card {
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-card);
  padding: 11px 12px 12px;
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.countdown {
  color: var(--ink-3);
}
.title {
  margin: 0 0 6px;
  font-size: 13px;
  line-height: 1.35;
  color: var(--ink);
  font-weight: 500;
  letter-spacing: -0.005em;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.reason {
  margin: 0 0 8px;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--ink-2);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.act {
  font-family: var(--font-mono);
  font-size: 10px;
  letter-spacing: 0.03em;
  padding: 3px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  color: var(--ink);
  cursor: pointer;
}
.act:hover {
  background: var(--hover);
}
.act.primary {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}
</style>
```

- [ ] **Step 2: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/components/FollowupCard.vue
git commit -m "Add FollowupCard component"
```

---

## Task 7: Create the follow-up column component

**Files:**
- Create: `webapp/src/components/FollowupColumn.vue`

- [ ] **Step 1: Write `FollowupColumn.vue`**

Create `webapp/src/components/FollowupColumn.vue` with exactly:

```vue
<!-- One column of the follow-up board. Static (no drag) — header with label +
     count, body is a scrollable stack of FollowupCards. -->
<script setup lang="ts">
import FollowupCard from './FollowupCard.vue';
import Mono from './Mono.vue';
import type { Followup } from '@/types/api';

interface Props {
  label: string;
  followups: Followup[];
}
const props = defineProps<Props>();
</script>

<template>
  <section class="column">
    <header>
      <div class="name">{{ props.label }}</div>
      <Mono class="count">{{ props.followups.length }}</Mono>
    </header>
    <div class="cards">
      <FollowupCard v-for="f in props.followups" :key="f.ticket_id" :followup="f" />
      <div v-if="props.followups.length === 0" class="empty mono">empty</div>
    </div>
  </section>
</template>

<style scoped>
.column {
  flex: 0 0 280px;
  display: flex;
  flex-direction: column;
  border-right: var(--hairline) solid var(--line-soft);
}
header {
  padding: 14px 14px 10px;
  border-bottom: var(--hairline) solid var(--line);
  display: flex;
  align-items: center;
  gap: 8px;
  position: sticky;
  top: 0;
  background: var(--bg);
  z-index: 1;
}
.name {
  font-size: 12.5px;
  color: var(--ink);
  font-weight: 500;
  letter-spacing: -0.005em;
}
.count {
  margin-left: auto;
}
.cards {
  padding: 8px 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
  flex: 1;
}
.empty {
  text-align: center;
  padding: 24px 8px;
  border: var(--hairline) dashed var(--line);
  border-radius: 3px;
  color: var(--ink-3);
}
</style>
```

- [ ] **Step 2: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/components/FollowupColumn.vue
git commit -m "Add FollowupColumn component"
```

---

## Task 8: Create the follow-up board view

**Files:**
- Create: `webapp/src/components/FollowupBoard.vue`

- [ ] **Step 1: Write `FollowupBoard.vue`**

Create `webapp/src/components/FollowupBoard.vue` with exactly:

```vue
<!-- Follow-up board — five time-bucketed columns. Reuses the horizontal-scroll
     layout of the main Board. Read of `followups.buckets` re-evaluates every
     alarm tick, so cards re-bucket live. -->
<script setup lang="ts">
import FollowupColumn from './FollowupColumn.vue';
import { BUCKET_LABEL, BUCKET_ORDER, useFollowupsStore } from '@/stores/followups';

const followups = useFollowupsStore();
</script>

<template>
  <div class="board">
    <FollowupColumn
      v-for="b in BUCKET_ORDER"
      :key="b"
      :label="BUCKET_LABEL[b]"
      :followups="followups.buckets[b]"
    />
    <div class="board-tail" />
  </div>
</template>

<style scoped>
.board {
  flex: 1;
  display: flex;
  overflow-x: auto;
  overflow-y: hidden;
}
.board-tail {
  flex: 1;
  min-width: 40px;
}
</style>
```

- [ ] **Step 2: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/components/FollowupBoard.vue
git commit -m "Add FollowupBoard view"
```

---

## Task 9: Add the "Follow-ups" nav button

**Files:**
- Modify: `webapp/src/components/Topbar.vue`

- [ ] **Step 1: Add the nav entry**

In `webapp/src/components/Topbar.vue`, change the `NAV` array (lines 23-27) to insert `followups` right after `board`:

```ts
const NAV: { id: View; label: string }[] = [
  { id: 'board', label: 'Board' },
  { id: 'followups', label: 'Follow-ups' },
  { id: 'categories', label: 'Categories' },
  { id: 'proposals', label: 'Proposals' },
];
```

- [ ] **Step 2: Add the follow-up count badge**

In the `<nav class="seg">` block, the proposals badge is on lines 66-68. Add a sibling badge for follow-ups right after it. Replace lines 66-68:

```html
        <span v-if="n.id === 'proposals' && proposalCount" class="nav-badge">{{
          proposalCount
        }}</span>
```

with:

```html
        <span v-if="n.id === 'proposals' && proposalCount" class="nav-badge">{{
          proposalCount
        }}</span>
        <span
          v-else-if="n.id === 'followups' && followups.pendingCount"
          class="nav-badge"
        >{{ followups.pendingCount }}</span>
```

(The `followups` store is already imported and instantiated in `Topbar.vue` at lines 8 and 19 — no new import needed.)

- [ ] **Step 3: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/components/Topbar.vue
git commit -m "Add Follow-ups nav button with pending-count badge"
```

---

## Task 10: Render the board and fire desktop notifications in App.vue

**Files:**
- Modify: `webapp/src/App.vue`

- [ ] **Step 1: Add imports**

In `webapp/src/App.vue`, the component imports end at line 15 (`import Topbar`). Add after line 9 (`import ProposalsPage`), keeping alphabetical-ish grouping:

```ts
import FollowupBoard from '@/components/FollowupBoard.vue';
```

The store/util imports: after line 21 (`import { useViewStore }`), add:

```ts
import { useTweaksStore } from '@/stores/tweaks';
import { notify, permission } from '@/utils/notify';
```

- [ ] **Step 2: Instantiate the tweaks store**

After line 28 (`const view = useViewStore();`), add:

```ts
const tweaks = useTweaksStore();
```

- [ ] **Step 3: Fire notifications in `alarmTick`**

Replace the `alarmTick` function (lines 77-81):

```ts
function alarmTick() {
  const fired = followups.tick();
  // FR-021 — the banner always shows; the mute flag suppresses only the audio.
  if (fired.length > 0 && !settings.muteAlarms) playPing();
}
```

with:

```ts
function alarmTick() {
  const fired = followups.tick();
  // FR-021 — the banner always shows; the mute flag suppresses only the audio.
  if (fired.length > 0 && !settings.muteAlarms) playPing();
  // Desktop notifications — gated independently of mute_alarms by the
  // per-browser tweaks preference. No-op unless permission was granted.
  if (fired.length > 0 && tweaks.desktopNotifications && permission() === 'granted') {
    for (const id of fired) {
      const f = followups.get(id);
      notify(`Follow-up due — ${id}`, f?.reason ?? 'No reason given', id, () =>
        view.selectTicket(id),
      );
    }
  }
}
```

- [ ] **Step 4: Render `FollowupBoard` for the new view**

In the `<template>`, replace the page-switch block (lines 130-137):

```html
    <template v-else>
      <template v-if="view.view === 'board'">
        <ExtensionCallout v-if="tickets.isEmpty" mode="empty" />
        <Board v-else />
      </template>
      <CategoriesPage v-else-if="view.view === 'categories'" />
      <ProposalsPage v-else />
    </template>
```

with:

```html
    <template v-else>
      <template v-if="view.view === 'board'">
        <ExtensionCallout v-if="tickets.isEmpty" mode="empty" />
        <Board v-else />
      </template>
      <FollowupBoard v-else-if="view.view === 'followups'" />
      <CategoriesPage v-else-if="view.view === 'categories'" />
      <ProposalsPage v-else />
    </template>
```

- [ ] **Step 5: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/App.vue
git commit -m "Render FollowupBoard and fire desktop notifications on alarm tick"
```

---

## Task 11: Add the desktop-notifications checkbox to the settings drawer

**Files:**
- Modify: `webapp/src/components/SettingsDrawer.vue`

- [ ] **Step 1: Add imports**

In `webapp/src/components/SettingsDrawer.vue`, change the `vue` import (line 6) from:

```ts
import { computed } from 'vue';
```

to:

```ts
import { computed, ref } from 'vue';
```

After the store imports (line 12, `import { useViewStore }`), add:

```ts
import { useTweaksStore } from '@/stores/tweaks';
import { permission, requestPermission, supported } from '@/utils/notify';
```

- [ ] **Step 2: Instantiate the tweaks store + a hint ref**

After line 18 (`const view = useViewStore();`), add:

```ts
const tweaks = useTweaksStore();
const notifyHint = ref('');
```

- [ ] **Step 3: Add the toggle handler**

After the `onToggleUseAi` function (ends at line 70), add:

```ts
/** Desktop notifications toggle — turning it on prompts for browser
 *  permission the first time; a denial reverts the checkbox with a hint. */
async function onToggleNotifications(event: Event) {
  const input = event.target as HTMLInputElement;
  notifyHint.value = '';
  if (!input.checked) {
    tweaks.setDesktopNotifications(false);
    return;
  }
  if (!supported()) {
    notifyHint.value = 'This browser does not support notifications.';
    input.checked = false;
    return;
  }
  let perm = permission();
  if (perm === 'default') perm = await requestPermission();
  if (perm === 'granted') {
    tweaks.setDesktopNotifications(true);
  } else {
    notifyHint.value = 'Notifications blocked — allow them in browser site settings.';
    input.checked = false;
  }
}
```

- [ ] **Step 4: Add the settings section**

In the `<template>`, the AI-categorization `<section>` ends at line 172 (`</section>`). Add a new section immediately after it, before the closing `</div>` of `.body`:

```html
        <!-- Desktop notifications -->
        <section>
          <Mono>Desktop notifications</Mono>
          <label class="check">
            <input
              type="checkbox"
              :checked="tweaks.desktopNotifications"
              @change="onToggleNotifications"
            />
            <span class="sentence">Notify on the desktop when a follow-up is due</span>
          </label>
          <p v-if="notifyHint" class="hint">{{ notifyHint }}</p>
          <p v-else class="hint">
            A browser notification fires alongside the in-app alarm, even when
            this tab is in the background.
          </p>
        </section>
```

- [ ] **Step 5: Verify typecheck passes**

Run (from `webapp/`): `npm run typecheck`
Expected: exits 0, no errors.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/components/SettingsDrawer.vue
git commit -m "Add desktop-notifications toggle to the settings drawer"
```

---

## Task 12: Full verification

**Files:** none — verification only.

- [ ] **Step 1: Production build**

Run (from `webapp/`): `npm run build`
Expected: `vue-tsc --noEmit` passes and `vite build` completes with no errors.

- [ ] **Step 2: Lint**

Run (from `webapp/`): `npm run lint`
Expected: exits 0, no errors.

- [ ] **Step 3: Manual smoke test**

Start the backend (`scripts/dev-backend.ps1`) and the webapp (`npm run dev`), then verify:

- The topbar shows a **Follow-ups** button between Board and Categories; with at least one follow-up it carries a count badge.
- Clicking it opens a 5-column board: Overdue · Within 1h · Today · Later · Fired.
- Set a follow-up ~1 minute out on a ticket (via the ticket flyout) → its card appears in **Within 1h** with a live "in Ns" countdown.
- When it comes due → the card moves to **Fired**; the in-app alarm banner still shows.
- On a Fired card: **15m** moves it back to a time bucket; **Done** removes it; **Open** opens the ticket flyout.
- Open Settings → enable **Desktop notifications** → the browser permission prompt appears. Grant it.
- Let a follow-up fire → a desktop notification appears titled `Follow-up due — <id>`; clicking it focuses the tab and opens that ticket's flyout.
- Deny permission instead → the checkbox reverts and shows the "blocked" hint.

- [ ] **Step 4: Commit (only if Steps 1-2 required a fix)**

If a lint/build fix was needed, commit it:

```bash
git add -A
git commit -m "Fix lint/build issues from follow-up board verification"
```

Otherwise no commit — verification is complete.

---

## Self-Review Notes

- **Spec coverage:** §A (view, columns, bucketing, cards, tickets `byId`) → Tasks 1, 2, 5, 6, 7, 8, 9, 10. §B (notify util, tweaks preference, settings checkbox, firing) → Tasks 3, 4, 10, 11. §C (timing) → no code change by design; verified manually in Task 12. §D (error handling) → `notify` try/catch (Task 4), graceful unknown-ticket card (Task 6), store rollback reused (Task 6). §E (testing) → Task 12.
- **Type consistency:** `Bucket`, `BUCKET_ORDER`, `BUCKET_LABEL`, `bucketOf`, `buckets` are defined in Task 5 and consumed identically in Tasks 6-8. `byId` (Task 2) is a `Map<string, Ticket>`; consumed via `.get(...)` in Task 6. `desktopNotifications` / `setDesktopNotifications` (Task 3) consumed in Tasks 10-11. `supported` / `permission` / `requestPermission` / `notify` (Task 4) consumed in Tasks 10-11 with matching signatures.
- **Ordering:** stores + utils (Tasks 1-5) precede the components that import them (Tasks 6-11), so every task's `npm run typecheck` passes against already-present symbols.

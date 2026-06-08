<!-- App shell. Loads settings + categories + tickets + follow-ups + notes on
     mount, renders the top bar and the active page (board / categories /
     proposals), owns the global keyboard shortcuts (T036), the settings drawer
     (T035), the ticket flyout (T050/T052), and the once-per-second alarm loop
     (T051). -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue';
import LoginView from '@/components/LoginView.vue';
import AlarmBanners from '@/components/AlarmBanners.vue';
import Board from '@/components/Board.vue';
import BulkActionBar from '@/components/BulkActionBar.vue';
import CategoriesPage from '@/components/CategoriesPage.vue';
import EmptyBoard from '@/components/EmptyBoard.vue';
import FollowupBoard from '@/components/FollowupBoard.vue';
import PlaybooksPage from '@/components/PlaybooksPage.vue';
import ProposalsPage from '@/components/ProposalsPage.vue';
import SettingsDrawer from '@/components/SettingsDrawer.vue';
import SnippetsPage from '@/components/SnippetsPage.vue';
import StatsPage from '@/components/StatsPage.vue';
import TicketFlyout from '@/components/TicketFlyout.vue';
import Topbar from '@/components/Topbar.vue';
import { useKeyboardTriage } from '@/composables/useKeyboardTriage';
import { useAuthStore } from '@/stores/auth';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useNoteEntriesStore } from '@/stores/noteEntries';
import { useNotesStore } from '@/stores/notes';
import { useSelectionStore } from '@/stores/selection';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import { useTweaksStore } from '@/stores/tweaks';
import { notify, permission } from '@/utils/notify';

const auth = useAuthStore();
const authReady = ref(false);
const categories = useCategoriesStore();
const settings = useSettingsStore();
const tickets = useTicketsStore();
const followups = useFollowupsStore();
const notes = useNotesStore();
const noteEntries = useNoteEntriesStore();
const view = useViewStore();
const tweaks = useTweaksStore();
const selection = useSelectionStore();
const triage = useKeyboardTriage();

const COLUMN_STEP = 296; // column width (280) + gutter

onMounted(async () => {
  await auth.bootstrap();
  authReady.value = true;
  if (!auth.isAuthenticated) return;
  await loadAll();
});

async function loadAll() {
  await settings.load();
  await categories.load();
  await Promise.all([followups.load(), notes.load(), noteEntries.load()]);
  // A failed board load records tickets.error; the board view surfaces it as an
  // error state (distinct from the genuine empty "nothing synced" board). Caught
  // here so a partial backend failure doesn't reject the whole bootstrap.
  await tickets.refresh().catch(() => undefined);
}

watch(
  () => auth.isAuthenticated,
  (now, before) => {
    if (now && !before) void loadAll();
  },
);

// ── Alarm loop (T051) ─────────────────────────────────────────────────────────
//
// A WebAudio two-note ping (880 → 1175 Hz). The AudioContext can only start
// after a user gesture (browser autoplay policy), so it is created lazily on
// the first pointer interaction.

let audioCtx: AudioContext | null = null;

function ensureAudio() {
  if (audioCtx === null && typeof AudioContext !== 'undefined') {
    audioCtx = new AudioContext();
  }
}

function playPing() {
  ensureAudio();
  if (audioCtx === null) return;
  if (audioCtx.state === 'suspended') void audioCtx.resume();
  const t0 = audioCtx.currentTime;
  [880, 1175].forEach((freq, i) => {
    const osc = audioCtx!.createOscillator();
    const gain = audioCtx!.createGain();
    osc.type = 'sine';
    osc.frequency.value = freq;
    const start = t0 + i * 0.34;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(0.22, start + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.0001, start + 0.3);
    osc.connect(gain).connect(audioCtx!.destination);
    osc.start(start);
    osc.stop(start + 0.32);
  });
}

let tickHandle = 0;

// ── Auto-sync (background polling) ───────────────────────────────────────────
//
// Arms a setInterval based on tweaks.autoSyncSeconds. Zero disables polling.
// The silent path never sets loading=true so the status banner doesn't flicker.
// Skips the poll tick when the document is hidden (saves cycles) or when a
// manual refresh is already in flight (concurrency safety).

let syncHandle = 0;

function armAutoSync(seconds: number) {
  if (syncHandle) {
    clearInterval(syncHandle);
    syncHandle = 0;
  }
  if (seconds <= 0) return;
  syncHandle = window.setInterval(() => {
    if (document.visibilityState === 'hidden') return;
    if (tickets.loading) return; // manual refresh in flight — skip this tick
    void tickets.silentRefresh();
  }, seconds * 1000);
}

function onVisibilityChange() {
  // When the tab becomes visible again after being hidden, fire an immediate
  // silent refresh so the board catches up without waiting for the next tick.
  if (document.visibilityState === 'visible' && tweaks.autoSyncSeconds > 0) {
    if (!tickets.loading) void tickets.silentRefresh();
  }
}

function alarmTick() {
  // Early-return is cheaper than the watcher lifecycle dance; same CPU savings.
  if (followups.pendingCount === 0 && followups.banners.length === 0) return;
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

/** Global shortcuts (T036): `r` refreshes, ←/→ scroll the board columns,
 *  `/` focuses the search input, Escape clears search / closes flyout. */
function onKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement | null;
  // Let keystrokes through normally when focus is inside a form control,
  // EXCEPT for Escape — which we still handle to clear/blur the search input.
  const inFormControl = target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName);
  if (e.metaKey || e.ctrlKey || e.altKey) return;

  if (e.key === 'Escape') {
    if (tickets.query) {
      // First Escape clears the search query and blurs the input.
      tickets.setQuery('');
      document.querySelector<HTMLInputElement>('.search-input')?.blur();
      return;
    }
    // Bulk-selection wins over flyout-close — operators clearing a multi-
    // select shouldn't accidentally dismiss an open flyout (plan §8d).
    if (!selection.isEmpty) {
      selection.clear();
      return;
    }
    if (view.selectedTicketId !== null) {
      view.closeFlyout();
      return;
    }
    return;
  }

  if (inFormControl) return;

  if (e.key === '/') {
    e.preventDefault();
    document.querySelector<HTMLInputElement>('.search-input')?.focus();
    return;
  }
  if (e.key === 'r') {
    e.preventDefault();
    void tickets.refresh();
    return;
  }
  if (view.view !== 'board') return;

  // Keyboard-driven triage (NFR-007): j/k navigate, e resolves, 1..9
  // recategorize the focused card. Suppressed while a modal surface is open
  // (flyout / settings drawer) so those keep their own focus + Escape
  // semantics; the bulk-selection set does not block triage (it has no key
  // overlap). See composables/useKeyboardTriage.ts for the key scheme.
  const modalOpen = view.selectedTicketId !== null || view.drawerOpen;
  if (!modalOpen && triage.runTriageKey(e.key)) {
    e.preventDefault();
    return;
  }

  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    const board = document.querySelector<HTMLElement>('.board');
    if (!board) return;
    e.preventDefault();
    board.scrollBy({
      left: e.key === 'ArrowRight' ? COLUMN_STEP : -COLUMN_STEP,
      behavior: 'smooth',
    });
  }
}

/** Empty-background click clears the bulk selection (plan §8d / FR-032).
 *  Triggered only when the pointer lands on the board chrome itself, not on
 *  a card or a column header — those have their own click handlers and won't
 *  bubble through with the `.board` element as `event.target`. */
function onBoardBackgroundClick(e: MouseEvent) {
  if (selection.isEmpty) return;
  const target = e.target as HTMLElement | null;
  if (!target) return;
  // The only acceptable targets are the .board container itself or the
  // .board-tail spacer — anything inside a column/card means the click was
  // intentional and the existing handlers already ran.
  if (target.classList.contains('board') || target.classList.contains('board-tail')) {
    selection.clear();
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
  window.addEventListener('pointerdown', ensureAudio, { once: true });
  window.addEventListener('visibilitychange', onVisibilityChange);
  tickHandle = window.setInterval(alarmTick, 1000);
  // Arm auto-sync from the saved preference on first load.
  armAutoSync(tweaks.autoSyncSeconds);
});
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown);
  window.removeEventListener('visibilitychange', onVisibilityChange);
  clearInterval(tickHandle);
  if (syncHandle) clearInterval(syncHandle);
});

// Re-arm the sync interval whenever the preference changes.
watch(
  () => tweaks.autoSyncSeconds,
  (seconds) => armAutoSync(seconds),
);
</script>

<template>
  <div v-if="!authReady" class="status mono">Loading…</div>
  <LoginView v-else-if="!auth.isAuthenticated" />
  <div v-else class="app">
    <Topbar />

    <div v-if="categories.loading" class="status mono">Loading…</div>
    <div v-else-if="categories.error" class="status error mono">
      Backend unreachable — {{ categories.error }}
    </div>
    <template v-else>
      <template v-if="view.view === 'board'">
        <div v-if="tickets.error && tickets.isEmpty" class="status error mono">
          Couldn't load the board — {{ tickets.error }}
        </div>
        <EmptyBoard v-else-if="tickets.isEmpty" />
        <Board v-else @board-click="onBoardBackgroundClick" />
      </template>
      <FollowupBoard v-else-if="view.view === 'followups'" />
      <CategoriesPage v-else-if="view.view === 'categories'" />
      <PlaybooksPage v-else-if="view.view === 'playbooks'" />
      <SnippetsPage v-else-if="view.view === 'snippets'" />
      <StatsPage v-else-if="view.view === 'stats'" />
      <ProposalsPage v-else />
    </template>

    <footer>
      <span class="mono">
        Last {{ settings.lookbackValue }} {{ settings.lookbackUnit }} · auto-categorized · drag to
        override
      </span>
      <span class="mono"
        >j/k focus · e resolve · 1-9 categorize · r refresh · ←/→ columns · / search</span
      >
    </footer>

    <SettingsDrawer />
    <TicketFlyout />
    <AlarmBanners />
    <BulkActionBar />
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.status {
  padding: 40px 20px;
  text-align: center;
  color: var(--ink-3);
}
.status.error {
  color: var(--accent);
}
footer {
  padding: 8px 20px;
  border-top: var(--hairline) solid var(--line);
  background: var(--bg);
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex: 0 0 auto;
  color: var(--ink-3);
}
</style>

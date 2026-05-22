<!-- App shell. Loads settings + categories + tickets + follow-ups + notes on
     mount, renders the top bar and the active page (board / categories /
     proposals), owns the global keyboard shortcuts (T036), the settings drawer
     (T035), the ticket flyout (T050/T052), and the once-per-second alarm loop
     (T051). -->
<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue';
import AlarmBanners from '@/components/AlarmBanners.vue';
import Board from '@/components/Board.vue';
import CategoriesPage from '@/components/CategoriesPage.vue';
import ExtensionCallout from '@/components/ExtensionCallout.vue';
import FollowupBoard from '@/components/FollowupBoard.vue';
import ProposalsPage from '@/components/ProposalsPage.vue';
import SettingsDrawer from '@/components/SettingsDrawer.vue';
import TicketFlyout from '@/components/TicketFlyout.vue';
import Topbar from '@/components/Topbar.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useFollowupsStore } from '@/stores/followups';
import { useNotesStore } from '@/stores/notes';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';
import { useViewStore } from '@/stores/view';
import { useTweaksStore } from '@/stores/tweaks';
import { notify, permission } from '@/utils/notify';

const categories = useCategoriesStore();
const settings = useSettingsStore();
const tickets = useTicketsStore();
const followups = useFollowupsStore();
const notes = useNotesStore();
const view = useViewStore();
const tweaks = useTweaksStore();

const COLUMN_STEP = 296; // column width (280) + gutter

onMounted(async () => {
  await settings.load();
  await categories.load();
  await Promise.all([followups.load(), notes.load()]);
  // An unreachable backend leaves the board empty + raises an inline error;
  // the empty-state callout points the operator at the extension to sync.
  await tickets.refresh().catch(() => undefined);
});

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

/** Global shortcuts (T036): `r` refreshes, ←/→ scroll the board columns. */
function onKeydown(e: KeyboardEvent) {
  const target = e.target as HTMLElement | null;
  if (target && /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName)) return;
  if (e.metaKey || e.ctrlKey || e.altKey) return;

  if (e.key === 'r') {
    e.preventDefault();
    void tickets.refresh();
    return;
  }
  if (e.key === 'Escape' && view.selectedTicketId !== null) {
    view.closeFlyout();
    return;
  }
  if (view.view !== 'board') return;
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

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
  window.addEventListener('pointerdown', ensureAudio, { once: true });
  tickHandle = window.setInterval(alarmTick, 1000);
});
onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown);
  clearInterval(tickHandle);
});
</script>

<template>
  <div class="app">
    <Topbar />
    <ExtensionCallout />

    <div v-if="categories.loading" class="status mono">Loading…</div>
    <div v-else-if="categories.error" class="status error mono">
      Backend unreachable — {{ categories.error }}
    </div>
    <template v-else>
      <template v-if="view.view === 'board'">
        <ExtensionCallout v-if="tickets.isEmpty" mode="empty" />
        <Board v-else />
      </template>
      <FollowupBoard v-else-if="view.view === 'followups'" />
      <CategoriesPage v-else-if="view.view === 'categories'" />
      <ProposalsPage v-else />
    </template>

    <footer>
      <span class="mono">
        Last {{ settings.lookbackValue }} {{ settings.lookbackUnit }} · auto-categorized · drag to
        override
      </span>
      <span class="mono">r refresh · ←/→ columns</span>
    </footer>

    <SettingsDrawer />
    <TicketFlyout />
    <AlarmBanners />
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

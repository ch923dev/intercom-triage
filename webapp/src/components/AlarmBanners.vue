<!-- Alarm banner stack. Reference: tasks.md T051, plan §8a.
     Top-right stack of banners, one per firing follow-up. The once-per-second
     tick and audio cue live in App.vue; this component only renders + acts. -->
<script setup lang="ts">
import { useFollowupsStore } from '@/stores/followups';
import { useViewStore } from '@/stores/view';

const followups = useFollowupsStore();
const view = useViewStore();

function open(ticketId: string) {
  view.selectTicket(ticketId);
  followups.dismissBanner(ticketId);
}

function snooze(ticketId: string, minutes: number) {
  // The store re-raises the banner on failure; swallow the rejection here so it
  // doesn't surface as an unhandled promise rejection.
  void followups.snooze(ticketId, minutes).catch(() => undefined);
}
</script>

<template>
  <div class="stack">
    <div v-for="b in followups.banners" :key="b.ticketId" class="banner">
      <div class="head">
        <span class="mono">Follow-up due</span>
        <span class="mono id">{{ b.ticketId }}</span>
      </div>
      <p v-if="b.reason" class="reason">{{ b.reason }}</p>
      <div class="actions">
        <button class="act primary" @click="open(b.ticketId)">Open</button>
        <button class="act" @click="snooze(b.ticketId, 15)">Snooze 15m</button>
        <button class="act" @click="snooze(b.ticketId, 60)">Snooze 1h</button>
        <button class="act" @click="followups.dismissBanner(b.ticketId)">Dismiss</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.stack {
  position: fixed;
  top: 64px;
  right: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 50;
}
.banner {
  width: 280px;
  background: var(--panel);
  border: var(--hairline) solid var(--accent);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow);
  padding: 10px 12px;
  animation:
    triageSlide 0.18s ease-out,
    triageRing 1.4s ease-out 2;
}
.head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.head .mono:first-child {
  color: var(--accent);
  font-weight: 600;
}
.id {
  color: var(--ink-3);
}
.reason {
  margin: 6px 0 8px;
  font-size: 12px;
  line-height: 1.45;
  color: var(--ink-2);
}
.actions {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  margin-top: 6px;
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

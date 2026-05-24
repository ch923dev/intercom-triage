<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { useFollowupsStore } from '@/stores/followups';
import { formatShortDateTime } from '@/utils/time';

const { ticketId } = defineProps<{ ticketId: string }>();
const followups = useFollowupsStore();

const FU_PRESETS: { label: string; minutes: number | 'eod' }[] = [
  { label: '+15m', minutes: 15 },
  { label: '+1h', minutes: 60 },
  { label: '+4h', minutes: 240 },
  { label: '+EOD', minutes: 'eod' },
  { label: '+24h', minutes: 1440 },
];

const reason = ref('');
const busy = ref(false);
const error = ref<string | null>(null);

const followup = computed(() => followups.get(ticketId) ?? null);
const due = computed(() => followups.isDue(ticketId));

const dueLabel = computed(() =>
  followup.value ? formatShortDateTime(followup.value.due_at) : null,
);

watch(
  () => ticketId,
  (id) => {
    reason.value = id ? (followups.get(id)?.reason ?? '') : '';
    error.value = null;
  },
  { immediate: true },
);

function presetDate(minutes: number | 'eod'): Date {
  if (minutes !== 'eod') return new Date(Date.now() + minutes * 60_000);
  const d = new Date();
  d.setHours(18, 0, 0, 0);
  if (d.getTime() <= Date.now()) d.setDate(d.getDate() + 1);
  return d;
}

async function setFollowup(minutes: number | 'eod') {
  busy.value = true;
  error.value = null;
  try {
    await followups.setFollowup(ticketId, presetDate(minutes), reason.value.trim() || null);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}

async function clearFollowup() {
  busy.value = true;
  error.value = null;
  try {
    await followups.clearFollowup(ticketId);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}

async function snooze(mins: number) {
  busy.value = true;
  try {
    await followups.snooze(ticketId, mins);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="block">
    <div class="mono label">Follow-up</div>

    <div v-if="followup" class="fu-active" :class="{ due }">
      <span class="mono">{{ due ? 'Due now' : `Due ${dueLabel}` }}</span>
      <span v-if="followup.reason" class="fu-reason">{{ followup.reason }}</span>
    </div>

    <div v-if="followup && due" class="presets">
      <button class="chip" :disabled="busy" @click="snooze(15)">Snooze 15m</button>
      <button class="chip" :disabled="busy" @click="snooze(60)">Snooze 1h</button>
    </div>

    <input
      v-model="reason"
      class="reason"
      type="text"
      maxlength="80"
      placeholder="Reason (optional, ≤ 80 chars)"
    />
    <div class="presets">
      <button
        v-for="p in FU_PRESETS"
        :key="p.label"
        class="chip"
        :disabled="busy"
        @click="setFollowup(p.minutes)"
      >
        {{ p.label }}
      </button>
      <button v-if="followup" class="chip danger" :disabled="busy" @click="clearFollowup">
        Clear
      </button>
    </div>
    <div v-if="error" class="mono err">{{ error }}</div>
  </section>
</template>

<style scoped>
.block {
  border-top: var(--hairline) solid var(--line);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.label {
  color: var(--ink-3);
}
.fu-active {
  display: flex;
  gap: 8px;
  align-items: baseline;
  padding: 6px 9px;
  border-radius: var(--radius-chip);
  background: var(--chip-bg);
  border: var(--hairline) solid var(--line);
}
.fu-active.due {
  background: var(--accent-soft-2);
  border-color: var(--accent);
}
.fu-reason {
  font-size: 11.5px;
  color: var(--ink-2);
}
.reason {
  font-family: var(--font-sans);
  font-size: 12px;
  padding: 6px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  color: var(--ink);
}
.presets {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.chip {
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
.chip:hover {
  background: var(--hover);
}
.chip:disabled {
  opacity: 0.5;
  cursor: default;
}
.chip.danger {
  color: var(--accent);
  border-color: var(--accent);
}
.err {
  color: var(--accent);
}
</style>

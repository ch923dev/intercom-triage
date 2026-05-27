<!-- Park action menu: pick a duration preset (or custom datetime) + a reason,
     emit `park(untilAtIso, reason)`. Used by the card/flyout action row and
     reused conceptually by BulkActionBar's inline menu. Roadmap 4.1. -->
<script setup lang="ts">
import { ref } from 'vue';
import type { ParkedReason } from '@/types/api';

const emit = defineEmits<{ (e: 'park', untilAt: string, reason: ParkedReason): void }>();

const presets: Array<{ label: string; minutes: number }> = [
  { label: '1h', minutes: 60 },
  { label: '4h', minutes: 240 },
  { label: '1d', minutes: 24 * 60 },
  { label: '3d', minutes: 3 * 24 * 60 },
];

const reasons: Array<{ value: ParkedReason; label: string }> = [
  { value: 'waiting_on_customer', label: 'Waiting on customer' },
  { value: 'waiting_on_third_party', label: 'Waiting on third party' },
  { value: 'waiting_internal', label: 'Waiting (internal)' },
  { value: 'other', label: 'Other' },
];

const reason = ref<ParkedReason>('waiting_on_customer');
const customAt = ref('');

function emitPreset(minutes: number) {
  emit('park', new Date(Date.now() + minutes * 60_000).toISOString(), reason.value);
}
function emitCustom() {
  if (!customAt.value) return;
  const iso = new Date(customAt.value).toISOString();
  if (Date.parse(iso) <= Date.now()) return; // backend also rejects past times (422)
  emit('park', iso, reason.value);
}
</script>

<template>
  <div class="park-menu" role="menu">
    <label class="label">Reason</label>
    <select v-model="reason" class="reason">
      <option v-for="r in reasons" :key="r.value" :value="r.value">{{ r.label }}</option>
    </select>
    <label class="label">Until</label>
    <div class="presets">
      <button
        v-for="p in presets"
        :key="p.label"
        type="button"
        class="preset mono"
        role="menuitem"
        @click="emitPreset(p.minutes)"
      >
        +{{ p.label }}
      </button>
    </div>
    <div class="custom">
      <input v-model="customAt" type="datetime-local" class="custom-input" />
      <button type="button" class="preset" :disabled="!customAt" @click="emitCustom">Set</button>
    </div>
  </div>
</template>

<style scoped>
.park-menu {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  min-width: 200px;
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: 4px;
  box-shadow: var(--shadow);
}
.label {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--ink-3);
}
.reason,
.custom-input {
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  background: var(--bg);
  border: var(--hairline) solid var(--line);
  border-radius: 4px;
  padding: 4px 6px;
}
.presets {
  display: flex;
  gap: 4px;
}
.preset {
  font-family: inherit;
  font-size: 12px;
  color: var(--ink);
  background: transparent;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 4px 8px;
  cursor: pointer;
}
.preset:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.preset:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.custom {
  display: flex;
  gap: 4px;
  align-items: center;
}
</style>

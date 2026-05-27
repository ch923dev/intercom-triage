<!-- Park action menu: pick a duration preset (or custom datetime) + a reason,
     emit `park(untilAtIso, reason)`. Teleported to <body> and positioned
     fixed relative to its trigger (`anchor`) so it never clips inside a
     scrolling board column or the flyout panel. The parent owns the trigger
     button + open state and passes the trigger element as `anchor`; the menu
     emits `close` on an outside click. Roadmap 4.1. -->
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue';
import type { ParkedReason } from '@/types/api';

const props = defineProps<{ anchor?: HTMLElement | null }>();
const emit = defineEmits<{
  (e: 'park', untilAt: string, reason: ParkedReason, note: string | null): void;
  (e: 'close'): void;
}>();

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
const note = ref('');
const customAt = ref('');

/** Free-text note only applies to the 'other' reason; null otherwise. */
function noteArg(): string | null {
  return reason.value === 'other' ? note.value.trim() || null : null;
}
const panel = ref<HTMLElement | null>(null);
const top = ref(0);
const left = ref(0);

/** Position the fixed panel right-aligned under its trigger, clamped into the
 *  viewport (flip above if it would overflow the bottom). */
function place() {
  const a = props.anchor;
  const el = panel.value;
  if (!a || !el) return;
  const r = a.getBoundingClientRect();
  const w = el.offsetWidth || 210;
  const h = el.offsetHeight || 170;
  let l = r.right - w;
  l = Math.max(8, Math.min(l, window.innerWidth - w - 8));
  let t = r.bottom + 4;
  if (t + h > window.innerHeight - 8) t = Math.max(8, r.top - h - 4);
  left.value = l;
  top.value = t;
}

function onDocPointer(e: PointerEvent) {
  const el = panel.value;
  const a = props.anchor ?? null;
  const tgt = e.target as Node;
  if (el && !el.contains(tgt) && (!a || !a.contains(tgt))) emit('close');
}

function emitPreset(minutes: number) {
  emit('park', new Date(Date.now() + minutes * 60_000).toISOString(), reason.value, noteArg());
}
function emitCustom() {
  if (!customAt.value) return;
  const iso = new Date(customAt.value).toISOString();
  if (Date.parse(iso) <= Date.now()) return; // backend also rejects past times (422)
  emit('park', iso, reason.value, noteArg());
}

onMounted(async () => {
  await nextTick();
  place();
  window.addEventListener('scroll', place, true);
  window.addEventListener('resize', place);
  document.addEventListener('pointerdown', onDocPointer, true);
});
onBeforeUnmount(() => {
  window.removeEventListener('scroll', place, true);
  window.removeEventListener('resize', place);
  document.removeEventListener('pointerdown', onDocPointer, true);
});
</script>

<template>
  <Teleport to="body">
    <div
      ref="panel"
      class="park-menu"
      role="menu"
      :style="{ top: `${top}px`, left: `${left}px` }"
      @click.stop
    >
      <label class="label">Reason</label>
      <select v-model="reason" class="reason">
        <option v-for="r in reasons" :key="r.value" :value="r.value">{{ r.label }}</option>
      </select>
      <input
        v-if="reason === 'other'"
        v-model="note"
        type="text"
        class="reason note-input"
        maxlength="200"
        placeholder="Reason (optional)"
      />
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
  </Teleport>
</template>

<style scoped>
.park-menu {
  position: fixed;
  z-index: 200;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 8px;
  width: 210px;
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

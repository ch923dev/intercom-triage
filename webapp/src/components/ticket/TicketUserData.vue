<!-- Customer "User data" panel — mirrors Intercom's contact data block. Reads
     the ticket's customer `author`; rows with no value are omitted. Email and
     User ID carry an explicit Copy button. -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import type { TicketAuthor } from '@/types/api';
import CollapsibleSection from './CollapsibleSection.vue';

const { author } = defineProps<{ author: TicketAuthor }>();

/** Intercom roles are `user_role` / `lead_role` / `admin_role`; show "User". */
const typeLabel = computed(() => {
  const t = author.type;
  if (!t) return null;
  const base = t
    .replace(/_role$/, '')
    .replace(/_/g, ' ')
    .trim();
  return base ? base.charAt(0).toUpperCase() + base.slice(1) : null;
});

interface Row {
  label: string;
  value: string;
  copyable: boolean;
}

/** Label / value rows, filtered to the ones that actually have a value. */
const rows = computed<Row[]>(() =>
  [
    { label: 'Name', value: author.name, copyable: false },
    { label: 'Type', value: typeLabel.value, copyable: false },
    { label: 'Company', value: author.company, copyable: false },
    { label: 'Location', value: author.location, copyable: false },
    { label: 'Timezone', value: author.timezone, copyable: false },
    { label: 'Email', value: author.email, copyable: true },
    { label: 'Phone', value: author.phone, copyable: false },
    { label: 'User ID', value: author.id, copyable: true },
  ].filter((r): r is Row => !!r.value),
);

const copied = ref<string | null>(null);
let timer: ReturnType<typeof setTimeout> | undefined;

async function copy(value: string, label: string) {
  try {
    await navigator.clipboard.writeText(value);
    copied.value = label;
    clearTimeout(timer);
    timer = setTimeout(() => (copied.value = null), 1200);
  } catch {
    /* clipboard blocked — value stays visible for manual selection */
  }
}
</script>

<template>
  <CollapsibleSection title="User data" storage-key="userdata">
    <dl v-if="rows.length" class="grid">
      <template v-for="r in rows" :key="r.label">
        <dt class="mono key">{{ r.label }}</dt>
        <dd class="val-cell">
          <span class="val">{{ r.value }}</span>
          <button
            v-if="r.copyable"
            class="copy-btn mono"
            :class="{ done: copied === r.label }"
            type="button"
            :title="`Copy ${r.label}`"
            @click="copy(r.value, r.label)"
          >
            {{ copied === r.label ? '✓ Copied' : 'Copy' }}
          </button>
        </dd>
      </template>
    </dl>
    <p v-else class="mono empty">No user data</p>
  </CollapsibleSection>
</template>

<style scoped>
.grid {
  display: grid;
  grid-template-columns: 84px 1fr;
  gap: 6px 12px;
  margin: 0;
}
.key {
  color: var(--ink-3);
  text-transform: none;
  letter-spacing: 0.02em;
  align-self: baseline;
}
.val-cell {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}
.val {
  font-size: 12px;
  color: var(--ink);
  word-break: break-word;
  min-width: 0;
}
.copy-btn {
  flex: 0 0 auto;
  font-size: 9px;
  text-transform: none;
  letter-spacing: 0.02em;
  color: var(--ink-3);
  background: var(--chip-bg);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 1px 6px;
  cursor: pointer;
}
.copy-btn:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.copy-btn.done {
  color: var(--accent);
  border-color: var(--accent);
}
.empty {
  color: var(--ink-3);
}
</style>

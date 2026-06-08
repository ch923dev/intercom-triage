<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '@/api/client';
import { useTicketsStore } from '@/stores/tickets';
import type { UserRef } from '@/types/api';

const props = defineProps<{ ticketId: string; assignedTo: UserRef | null }>();
const tickets = useTicketsStore();
const users = ref<UserRef[]>([]);
const busy = ref(false);
const loadError = ref(false);
const assignError = ref(false);

onMounted(async () => {
  try {
    users.value = await api.listUsers();
  } catch {
    loadError.value = true;
  }
});

async function onChange(e: Event) {
  if (busy.value) return;
  busy.value = true;
  assignError.value = false;
  const select = e.target as HTMLSelectElement;
  try {
    const raw = select.value;
    await tickets.assign(props.ticketId, raw === '' ? null : Number(raw));
  } catch {
    // The store leaves assignment untouched on failure (it mutates only after the
    // await resolves), so snap the control back to server truth rather than strand
    // the rejected pick, and surface the failure to the operator.
    assignError.value = true;
    select.value = String(props.assignedTo?.id ?? '');
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <label class="assignee">
    Assigned
    <select :value="props.assignedTo?.id ?? ''" :disabled="busy" @change="onChange">
      <option value="">Unassigned</option>
      <option v-for="u in users" :key="u.id" :value="u.id">{{ u.name ?? `#${u.id}` }}</option>
    </select>
    <span v-if="loadError" class="err">Could not load users</span>
    <span v-else-if="assignError" class="err">Couldn't assign — try again</span>
  </label>
</template>

<style scoped>
.assignee {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  font-size: 0.85rem;
  color: var(--ink-2);
}
.err {
  font-size: 0.75rem;
  color: var(--accent);
}
</style>

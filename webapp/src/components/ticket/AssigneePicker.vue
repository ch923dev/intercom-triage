<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { api } from '@/api/client';
import { useTicketsStore } from '@/stores/tickets';
import type { UserRef } from '@/types/api';

const props = defineProps<{ ticketId: string; assignedTo: UserRef | null }>();
const tickets = useTicketsStore();
const users = ref<UserRef[]>([]);

onMounted(async () => {
  users.value = await api.listUsers();
});

async function onChange(e: Event) {
  const raw = (e.target as HTMLSelectElement).value;
  await tickets.assign(props.ticketId, raw === '' ? null : Number(raw));
}
</script>

<template>
  <label class="assignee">
    Assigned
    <select :value="props.assignedTo?.id ?? ''" @change="onChange">
      <option value="">Unassigned</option>
      <option v-for="u in users" :key="u.id" :value="u.id">{{ u.name ?? `#${u.id}` }}</option>
    </select>
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
</style>

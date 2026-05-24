<script setup lang="ts">
import { ref } from 'vue';
import CatDot from '../CatDot.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useTicketsStore } from '@/stores/tickets';

const { ticketId, effectiveCategoryId } = defineProps<{
  ticketId: string;
  effectiveCategoryId: number | null;
}>();

const categories = useCategoriesStore();
const tickets = useTicketsStore();
const busy = ref(false);

async function pick(categoryId: number) {
  if (effectiveCategoryId === categoryId || busy.value) return;
  busy.value = true;
  try {
    await tickets.applyOverride(ticketId, categoryId);
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <section class="block">
    <div class="mono label">Category</div>
    <div class="cat-chips">
      <button
        v-for="c in categories.categories"
        :key="c.id"
        class="cat-chip"
        :class="{ active: c.id === effectiveCategoryId }"
        :disabled="busy"
        @click="pick(c.id)"
      >
        <CatDot :color="c.color" :size="8" />
        <span>{{ c.name }}</span>
      </button>
    </div>
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
.cat-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.cat-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border: 0.5px solid var(--hairline);
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--ink-2);
  font-family: inherit;
  font-size: 12px;
  cursor: pointer;
}
.cat-chip:hover:not(.active):not(:disabled) {
  background: var(--hover);
  color: var(--ink);
}
.cat-chip.active {
  background: var(--ink);
  color: var(--bg);
  border-color: var(--ink);
}
.cat-chip:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
</style>

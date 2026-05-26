<!-- Playbooks library — all playbooks grouped by category. Spec:
     docs/superpowers/specs/2026-05-26-playbooks-design.md -->
<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { useCategoriesStore } from '@/stores/categories';
import { usePlaybooksStore } from '@/stores/playbooks';

const playbooks = usePlaybooksStore();
const categories = useCategoriesStore();

onMounted(() => {
  void playbooks.loadAll();
});

const groups = computed(() =>
  categories.categories
    .map((c) => ({ category: c, items: playbooks.forCategory(c.id) }))
    .filter((g) => g.items.length > 0),
);
</script>

<template>
  <div class="page">
    <h2 class="mono">Playbooks</h2>
    <p v-if="groups.length === 0" class="mono empty">
      No playbooks yet. Save one from a ticket flyout.
    </p>
    <section v-for="g in groups" :key="g.category.id" class="group">
      <div class="mono cat">{{ g.category.name }}</div>
      <details v-for="p in g.items" :key="p.id" class="playbook">
        <summary class="mono">{{ p.label }}</summary>
        <pre class="body">{{ p.body }}</pre>
        <button class="ghost" @click="playbooks.archive(p.id)">
          <span class="mono">Archive</span>
        </button>
      </details>
    </section>
  </div>
</template>

<style scoped>
.page {
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
h2 {
  color: var(--ink);
  margin: 0;
}
.empty {
  color: var(--ink-3);
}
.group {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.cat {
  color: var(--ink-3);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-size: 10px;
}
.playbook {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 8px 10px;
  max-width: 720px;
}
.playbook summary {
  cursor: pointer;
  color: var(--ink);
}
.body {
  margin: 6px 0;
  white-space: pre-wrap;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-2);
}
.ghost {
  padding: 3px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}
</style>

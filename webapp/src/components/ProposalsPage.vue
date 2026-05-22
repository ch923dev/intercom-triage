<!-- Proposals review page. Reference: tasks.md T038 — US-010, FR-016.
     Lists pending category proposals raised by the AI, each with example
     tickets. Approve promotes it to a category; "Merge into…" folds its
     tickets into an existing category; Reject sends them to the fallback and
     remembers the name so it is not proposed again. -->
<script setup lang="ts">
import { onMounted, ref } from 'vue';
import Mono from './Mono.vue';
import { useCategoriesStore } from '@/stores/categories';
import { useSettingsStore } from '@/stores/settings';
import { useTicketsStore } from '@/stores/tickets';

const categories = useCategoriesStore();
const tickets = useTicketsStore();
const settings = useSettingsStore();

const busy = ref<number | null>(null);
const error = ref<string | null>(null);
const loading = ref(false);

onMounted(async () => {
  loading.value = true;
  try {
    await categories.loadProposals();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    loading.value = false;
  }
});

/** Resolve a proposal, then reload categories + board so columns update. */
async function run(id: number, fn: () => Promise<void>) {
  busy.value = id;
  error.value = null;
  try {
    await fn();
    await tickets.refresh(settings.filter);
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = null;
  }
}

function approve(id: number) {
  void run(id, () => categories.approveProposal(id, null));
}

function reject(id: number, name: string) {
  if (
    !window.confirm(
      `Reject “${name}”? Its tickets move to the fallback and the name is remembered.`,
    )
  ) {
    return;
  }
  void run(id, () => categories.rejectProposal(id));
}

function merge(id: number, event: Event) {
  const select = event.target as HTMLSelectElement;
  const dstId = Number(select.value);
  select.value = '';
  if (!dstId) return;
  void run(id, () => categories.mergeProposal(id, dstId));
}
</script>

<template>
  <div class="page">
    <div class="head">
      <Mono :size="11">AI category proposals</Mono>
      <Mono>{{ categories.proposals.length }} pending</Mono>
    </div>

    <p v-if="error" class="error mono">{{ error }}</p>

    <div v-if="loading" class="empty mono">Loading…</div>
    <div v-else-if="categories.proposals.length === 0" class="empty mono">
      No pending proposals — the AI categorized everything into existing categories.
    </div>

    <ul v-else class="rows">
      <li
        v-for="p in categories.proposals"
        :key="p.id"
        class="card"
        :class="{ busy: busy === p.id }"
      >
        <div class="info">
          <div class="title-row">
            <span class="name">{{ p.name }}</span>
            <Mono :size="9">proposal</Mono>
          </div>
          <p class="desc">{{ p.description }}</p>
          <div v-if="p.example_ticket_ids.length" class="examples">
            <Mono :size="9">examples</Mono>
            <Mono v-for="tid in p.example_ticket_ids" :key="tid" class="chip">{{ tid }}</Mono>
          </div>
        </div>

        <div class="actions">
          <button class="approve" :disabled="busy !== null" @click="approve(p.id)">Approve</button>
          <select class="merge" :disabled="busy !== null" @change="merge(p.id, $event)">
            <option value="">Merge into…</option>
            <option v-for="c in categories.categories" :key="c.id" :value="c.id">
              {{ c.name }}
            </option>
          </select>
          <button class="reject" :disabled="busy !== null" @click="reject(p.id, p.name)">
            Reject
          </button>
        </div>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.page {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px 40px;
}
.head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 14px;
}
.error {
  color: var(--accent);
  margin: 0 0 12px;
}
.empty {
  padding: 40px 8px;
  text-align: center;
  color: var(--ink-3);
  border: var(--hairline) dashed var(--line);
  border-radius: var(--radius-card);
}
.rows {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.card {
  display: flex;
  gap: 16px;
  align-items: flex-start;
  justify-content: space-between;
  padding: 14px 16px;
  border: var(--hairline) solid var(--line);
  border-left: 2px solid var(--accent);
  border-radius: var(--radius-card);
  background: var(--panel);
}
.card.busy {
  opacity: 0.55;
}
.info {
  flex: 1;
  min-width: 0;
}
.title-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.name {
  font-size: 13.5px;
  font-weight: 600;
  color: var(--ink);
}
.desc {
  margin: 6px 0 8px;
  font-size: 12px;
  color: var(--ink-2);
  line-height: 1.45;
}
.examples {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.chip {
  padding: 2px 6px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--chip-bg);
}
.actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex: 0 0 auto;
}
.approve,
.reject,
.merge {
  font-family: var(--font-mono);
  font-size: 10.5px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 6px 12px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink-2);
  cursor: pointer;
}
.approve {
  background: var(--ink);
  color: var(--bg);
  border-color: var(--ink);
}
.reject:not(:disabled):hover {
  border-color: var(--accent);
  color: var(--accent);
}
.approve:disabled,
.reject:disabled,
.merge:disabled {
  opacity: 0.4;
  cursor: default;
}
</style>

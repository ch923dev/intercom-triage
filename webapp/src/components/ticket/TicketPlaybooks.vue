<!-- Playbooks for a ticket's effective category. Spec:
     docs/superpowers/specs/2026-05-26-playbooks-design.md -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import CollapsibleSection from './CollapsibleSection.vue';
import { usePlaybooksStore } from '@/stores/playbooks';

const props = defineProps<{
  ticketId: string;
  categoryId: number | null;
}>();

const playbooks = usePlaybooksStore();

const items = computed(() =>
  props.categoryId === null ? [] : playbooks.forCategory(props.categoryId),
);

watch(
  () => props.categoryId,
  (id) => {
    if (id !== null) void playbooks.ensureForCategory(id);
  },
  { immediate: true },
);

const showForm = ref(false);
const label = ref('');
const body = ref('');
const drafting = ref(false);
const saving = ref(false);
const error = ref<string | null>(null);

function openForm() {
  showForm.value = true;
  label.value = '';
  body.value = '';
  error.value = null;
}

async function draft() {
  drafting.value = true;
  error.value = null;
  try {
    body.value = await playbooks.draft(props.ticketId);
  } catch {
    error.value = 'AI draft failed — write the steps manually.';
  } finally {
    drafting.value = false;
  }
}

async function save() {
  if (props.categoryId === null || !label.value.trim() || !body.value.trim()) return;
  saving.value = true;
  error.value = null;
  try {
    await playbooks.create({
      category_id: props.categoryId,
      label: label.value.trim(),
      body: body.value.trim(),
      source_ticket_id: props.ticketId,
    });
    showForm.value = false;
  } catch {
    error.value = 'Save failed.';
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <CollapsibleSection title="Playbooks" storage-key="playbooks">
    <p v-if="categoryId === null" class="mono empty">Categorize this ticket to use playbooks.</p>
    <p v-else-if="items.length === 0 && !showForm" class="mono empty">
      No playbooks for this category yet.
    </p>

    <details v-for="p in items" :key="p.id" class="playbook">
      <summary class="mono">{{ p.label }}</summary>
      <pre class="body">{{ p.body }}</pre>
    </details>

    <div v-if="showForm" class="form">
      <input v-model="label" class="input mono" placeholder="Issue label" maxlength="120" />
      <textarea v-model="body" class="input area" placeholder="Next steps…" rows="5" />
      <p v-if="error" class="mono err">{{ error }}</p>
      <div class="row">
        <button class="ghost" :disabled="drafting" @click="draft">
          <span class="mono">{{ drafting ? 'Drafting…' : 'Draft with AI' }}</span>
        </button>
        <button class="ghost" :disabled="saving || !label.trim() || !body.trim()" @click="save">
          <span class="mono">{{ saving ? 'Saving…' : 'Save playbook' }}</span>
        </button>
      </div>
    </div>

    <button v-else-if="categoryId !== null" class="ghost" @click="openForm">
      <span class="mono">Save as playbook</span>
    </button>
  </CollapsibleSection>
</template>

<style scoped>
.empty {
  color: var(--ink-3);
  font-size: 11px;
}
.playbook {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 6px 8px;
}
.playbook summary {
  cursor: pointer;
  color: var(--ink);
}
.body {
  margin: 6px 0 0;
  white-space: pre-wrap;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-2);
}
.form {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.input {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--bg);
  color: var(--ink);
  padding: 5px 8px;
  font-size: 11px;
}
.area {
  resize: vertical;
  font-family: var(--font-mono);
}
.row {
  display: flex;
  gap: 6px;
}
.err {
  color: var(--accent);
  font-size: 11px;
}
.ghost {
  padding: 4px 10px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--ink);
  cursor: pointer;
}
.ghost:disabled {
  opacity: 0.5;
  cursor: default;
}
</style>

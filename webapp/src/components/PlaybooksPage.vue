<!-- Playbooks library — all playbooks grouped by category, with edit / archive /
     restore. New playbooks are captured from a ticket flyout. Spec:
     docs/superpowers/specs/2026-05-26-playbooks-design.md -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useCategoriesStore } from '@/stores/categories';
import { usePlaybooksStore } from '@/stores/playbooks';

const playbooks = usePlaybooksStore();
const categories = useCategoriesStore();

const showArchived = ref(false);
const error = ref<string | null>(null);

const editingId = ref<number | null>(null);
const editLabel = ref('');
const editBody = ref('');

onMounted(() => {
  void playbooks.loadAll();
});

watch(showArchived, (on) => {
  void playbooks.loadAll(on);
});

const groups = computed(() =>
  categories.categories
    .map((c) => ({
      category: c,
      items: playbooks.forCategory(c.id),
      archived: showArchived.value ? playbooks.archivedFor(c.id) : [],
    }))
    .filter((g) => g.items.length > 0 || g.archived.length > 0),
);

function startEdit(id: number, label: string, body: string) {
  editingId.value = id;
  editLabel.value = label;
  editBody.value = body;
}

function cancelEdit() {
  editingId.value = null;
}

async function saveEdit(id: number) {
  if (!editLabel.value.trim() || !editBody.value.trim()) return;
  error.value = null;
  try {
    await playbooks.update(id, { label: editLabel.value.trim(), body: editBody.value.trim() });
    editingId.value = null;
  } catch {
    error.value = 'Save failed.';
  }
}

async function archive(id: number) {
  error.value = null;
  try {
    await playbooks.archive(id);
  } catch {
    error.value = 'Archive failed.';
  }
}

async function restore(id: number) {
  error.value = null;
  try {
    await playbooks.restore(id);
  } catch {
    error.value = 'Restore failed.';
  }
}
</script>

<template>
  <div class="page">
    <div class="head">
      <h2 class="mono">Playbooks</h2>
      <label class="toggle mono">
        <input v-model="showArchived" type="checkbox" />
        Show archived
      </label>
    </div>

    <p v-if="error" class="mono err">{{ error }}</p>
    <p v-if="groups.length === 0" class="mono empty">
      No playbooks yet. Save one from a ticket flyout.
    </p>

    <section v-for="g in groups" :key="g.category.id" class="group">
      <div class="mono cat">{{ g.category.name }}</div>

      <div v-for="p in g.items" :key="p.id" class="playbook">
        <template v-if="editingId === p.id">
          <input v-model="editLabel" class="input mono" maxlength="120" />
          <textarea v-model="editBody" class="input area" rows="5" />
          <div class="row">
            <button
              class="ghost"
              :disabled="!editLabel.trim() || !editBody.trim()"
              @click="saveEdit(p.id)"
            >
              <span class="mono">Save</span>
            </button>
            <button class="ghost" @click="cancelEdit">
              <span class="mono">Cancel</span>
            </button>
          </div>
        </template>
        <template v-else>
          <details>
            <summary class="mono">{{ p.label }}</summary>
            <pre class="body">{{ p.body }}</pre>
          </details>
          <div class="row">
            <button class="ghost" @click="startEdit(p.id, p.label, p.body)">
              <span class="mono">Edit</span>
            </button>
            <button class="ghost" @click="archive(p.id)">
              <span class="mono">Archive</span>
            </button>
          </div>
        </template>
      </div>

      <div v-for="p in g.archived" :key="`a-${p.id}`" class="playbook archived">
        <details>
          <summary class="mono">{{ p.label }} <span class="tag">archived</span></summary>
          <pre class="body">{{ p.body }}</pre>
        </details>
        <button class="ghost" @click="restore(p.id)">
          <span class="mono">Restore</span>
        </button>
      </div>
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
.head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  max-width: 720px;
}
h2 {
  color: var(--ink);
  margin: 0;
}
.toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ink-3);
  cursor: pointer;
}
.empty {
  color: var(--ink-3);
}
.err {
  color: var(--accent);
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
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.playbook.archived {
  opacity: 0.7;
}
.playbook summary {
  cursor: pointer;
  color: var(--ink);
}
.tag {
  font-family: var(--font-mono);
  font-size: 9px;
  color: var(--ink-3);
}
.body {
  margin: 6px 0;
  white-space: pre-wrap;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--ink-2);
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
.ghost {
  padding: 3px 8px;
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

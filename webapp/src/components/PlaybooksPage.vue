<!-- Playbooks library — all playbooks grouped by category, with edit / archive /
     restore. New playbooks are captured from a ticket flyout. Spec:
     docs/superpowers/specs/2026-05-26-playbooks-design.md -->
<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useCategoriesStore } from '@/stores/categories';
import { useClusterGapsStore } from '@/stores/clusterGaps';
import { usePlaybooksStore } from '@/stores/playbooks';

const playbooks = usePlaybooksStore();
const categories = useCategoriesStore();
const clusterGaps = useClusterGapsStore();

const showArchived = ref(false);
const error = ref<string | null>(null);

const editingId = ref<number | null>(null);
const editLabel = ref('');
const editBody = ref('');

// "Suggested playbooks to build" (roadmap 3.2): recurring-issue clusters whose
// dominant effective category has no playbook yet. Each row offers an inline
// form to start a playbook scoped to that exact category.
const draftingClusterId = ref<number | null>(null);
const draftLabel = ref('');
const draftBody = ref('');

onMounted(() => {
  void playbooks.loadAll();
  void clusterGaps.load();
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

function startDraft(clusterId: number, label: string) {
  draftingClusterId.value = clusterId;
  draftLabel.value = label;
  draftBody.value = '';
}

function cancelDraft() {
  draftingClusterId.value = null;
}

async function saveDraft(categoryId: number) {
  if (!draftLabel.value.trim() || !draftBody.value.trim()) return;
  error.value = null;
  try {
    await playbooks.create({
      category_id: categoryId,
      label: draftLabel.value.trim(),
      body: draftBody.value.trim(),
    });
    draftingClusterId.value = null;
    // The category now has a playbook → drop it from the suggestions.
    await clusterGaps.load();
  } catch {
    error.value = 'Create failed.';
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

    <!-- Suggested playbooks to build (roadmap 3.2): recurring resolved-ticket
         clusters whose dominant category has no playbook yet, most-recurring
         first. The standout content-gap view. -->
    <section v-if="clusterGaps.gaps.length > 0" class="gaps">
      <div class="gaps-head">
        <h3 class="mono">Suggested playbooks to build</h3>
        <span class="mono hint">Recurring issues with no playbook yet</span>
      </div>
      <div v-for="gap in clusterGaps.gaps" :key="gap.cluster_id" class="gap">
        <div class="gap-main">
          <div class="gap-label mono">{{ gap.label }}</div>
          <div class="gap-meta mono">
            <span class="pill">{{ gap.category_name }}</span>
            <span>{{ gap.size }} recurring ticket{{ gap.size === 1 ? '' : 's' }}</span>
            <span class="nogap">no playbook</span>
          </div>
          <div v-if="gap.top_terms.length > 0" class="gap-terms mono">
            {{ gap.top_terms.join(' · ') }}
          </div>
        </div>
        <template v-if="draftingClusterId === gap.cluster_id">
          <input
            v-model="draftLabel"
            class="input mono"
            maxlength="120"
            placeholder="Playbook name"
          />
          <textarea v-model="draftBody" class="input area" rows="5" placeholder="Steps…" />
          <div class="row">
            <button
              class="ghost"
              :disabled="!draftLabel.trim() || !draftBody.trim()"
              @click="saveDraft(gap.category_id)"
            >
              <span class="mono">Create</span>
            </button>
            <button class="ghost" @click="cancelDraft">
              <span class="mono">Cancel</span>
            </button>
          </div>
        </template>
        <button v-else class="ghost" @click="startDraft(gap.cluster_id, gap.label)">
          <span class="mono">Build playbook for {{ gap.category_name }}</span>
        </button>
      </div>
    </section>

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
.gaps {
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 720px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 12px;
}
.gaps-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}
.gaps-head h3 {
  margin: 0;
  color: var(--ink);
  font-size: 13px;
}
.hint {
  color: var(--ink-3);
  font-size: 10px;
}
.gap {
  display: flex;
  flex-direction: column;
  gap: 6px;
  border-top: var(--hairline) solid var(--line);
  padding-top: 8px;
}
.gap-main {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.gap-label {
  color: var(--ink);
  font-size: 12px;
}
.gap-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 10px;
  color: var(--ink-3);
}
.gap-terms {
  font-size: 10px;
  color: var(--ink-3);
}
.pill {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 1px 6px;
  color: var(--ink-2);
}
.nogap {
  color: var(--accent);
}
</style>

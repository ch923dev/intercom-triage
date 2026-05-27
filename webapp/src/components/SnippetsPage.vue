<!-- Snippets library (roadmap 1.5) — short canned replies with {{variable}}
     placeholders. CRUD lives here (unlike playbooks, snippets are authored
     directly, not captured from a ticket flyout). Bodies are stored verbatim;
     substitution happens client-side from the open ticket (see
     utils/snippets.ts), so this page previews placeholders as-is. -->
<script setup lang="ts">
import { onMounted, ref, watch } from 'vue';
import { useSnippetsStore } from '@/stores/snippets';
import { SUPPORTED_VARIABLES } from '@/utils/snippets';

const snippets = useSnippetsStore();

/** Render a variable name as its `{{name}}` placeholder for the hint line.
 *  Built in script (not the template) so the literal braces don't collide with
 *  Vue's `{{ }}` interpolation parser. */
function placeholderLabel(name: string): string {
  return `{{${name}}}`;
}

const showArchived = ref(false);
const error = ref<string | null>(null);

const newTitle = ref('');
const newBody = ref('');

const editingId = ref<number | null>(null);
const editTitle = ref('');
const editBody = ref('');

onMounted(() => {
  void snippets.loadAll();
});

watch(showArchived, (on) => {
  void snippets.loadAll(on);
});

async function add() {
  if (!newTitle.value.trim() || !newBody.value.trim()) return;
  error.value = null;
  try {
    await snippets.create({ title: newTitle.value.trim(), body: newBody.value.trim() });
    newTitle.value = '';
    newBody.value = '';
  } catch {
    error.value = 'Create failed.';
  }
}

function startEdit(id: number, title: string, body: string) {
  editingId.value = id;
  editTitle.value = title;
  editBody.value = body;
}

function cancelEdit() {
  editingId.value = null;
}

async function saveEdit(id: number) {
  if (!editTitle.value.trim() || !editBody.value.trim()) return;
  error.value = null;
  try {
    await snippets.update(id, { title: editTitle.value.trim(), body: editBody.value.trim() });
    editingId.value = null;
  } catch {
    error.value = 'Save failed.';
  }
}

async function archive(id: number) {
  error.value = null;
  try {
    await snippets.archive(id);
  } catch {
    error.value = 'Archive failed.';
  }
}

async function restore(id: number) {
  error.value = null;
  try {
    await snippets.restore(id);
  } catch {
    error.value = 'Restore failed.';
  }
}
</script>

<template>
  <div class="page">
    <div class="head">
      <h2 class="mono">Snippets</h2>
      <label class="toggle mono">
        <input v-model="showArchived" type="checkbox" />
        Show archived
      </label>
    </div>

    <p class="mono hint">
      Short canned replies. Use placeholders —
      <code v-for="v in SUPPORTED_VARIABLES" :key="v">{{ placeholderLabel(v) }}</code>
      — filled from the open ticket when you insert a snippet from its flyout.
    </p>

    <!-- New snippet -->
    <div class="composer">
      <input v-model="newTitle" class="input mono" maxlength="120" placeholder="Title" />
      <textarea
        v-model="newBody"
        class="input area"
        rows="3"
        placeholder="Body — e.g. Hi {{customer_name}}, thanks for reaching out."
      />
      <div class="row">
        <button class="ghost" :disabled="!newTitle.trim() || !newBody.trim()" @click="add">
          <span class="mono">Add snippet</span>
        </button>
      </div>
    </div>

    <p v-if="error" class="mono err">{{ error }}</p>
    <p v-if="snippets.active.length === 0 && snippets.archived.length === 0" class="mono empty">
      No snippets yet. Add one above.
    </p>

    <section class="group">
      <div v-for="s in snippets.active" :key="s.id" class="snippet">
        <template v-if="editingId === s.id">
          <input v-model="editTitle" class="input mono" maxlength="120" />
          <textarea v-model="editBody" class="input area" rows="4" />
          <div class="row">
            <button
              class="ghost"
              :disabled="!editTitle.trim() || !editBody.trim()"
              @click="saveEdit(s.id)"
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
            <summary class="mono">{{ s.title }}</summary>
            <pre class="body">{{ s.body }}</pre>
          </details>
          <div class="row">
            <button class="ghost" @click="startEdit(s.id, s.title, s.body)">
              <span class="mono">Edit</span>
            </button>
            <button class="ghost" @click="archive(s.id)">
              <span class="mono">Archive</span>
            </button>
          </div>
        </template>
      </div>

      <div v-for="s in snippets.archived" :key="`a-${s.id}`" class="snippet archived">
        <details>
          <summary class="mono">{{ s.title }} <span class="tag">archived</span></summary>
          <pre class="body">{{ s.body }}</pre>
        </details>
        <button class="ghost" @click="restore(s.id)">
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
.hint {
  color: var(--ink-3);
  max-width: 720px;
  font-size: 11px;
  line-height: 1.5;
}
.hint code {
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--ink-2);
  margin: 0 2px;
}
.composer {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 720px;
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
.snippet {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 8px 10px;
  max-width: 720px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.snippet.archived {
  opacity: 0.7;
}
.snippet summary {
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

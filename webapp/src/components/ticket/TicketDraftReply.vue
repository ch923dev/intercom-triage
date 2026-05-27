<!-- RAG draft reply (roadmap 2.6). On demand, asks the backend to draft a
     customer reply grounded in similar RESOLVED tickets + the ticket's
     effective-category playbooks. The draft is ephemeral (never persisted) and
     read-only / copyable — the operator edits it in Intercom, not here. The
     grounding ticket ids are shown for transparency; no internal-note content
     is ever exposed (backend invariant #4). -->
<script setup lang="ts">
import { ref } from 'vue';
import CollapsibleSection from './CollapsibleSection.vue';
import { api } from '@/api/client';
import type { DraftReply } from '@/types/api';

const props = defineProps<{
  ticketId: string;
}>();

const draft = ref<DraftReply | null>(null);
const drafting = ref(false);
const copied = ref(false);
const error = ref<string | null>(null);

async function generate() {
  drafting.value = true;
  error.value = null;
  copied.value = false;
  try {
    draft.value = await api.draftReply(props.ticketId);
  } catch {
    error.value = 'AI draft failed — try again or reply manually.';
  } finally {
    drafting.value = false;
  }
}

async function copy() {
  if (!draft.value) return;
  try {
    await navigator.clipboard.writeText(draft.value.body);
    copied.value = true;
  } catch {
    error.value = 'Copy failed — select the text manually.';
  }
}
</script>

<template>
  <CollapsibleSection title="Draft reply" storage-key="draft-reply">
    <p class="mono hint">Grounded in similar resolved tickets and this category's playbooks.</p>

    <button class="ghost" :disabled="drafting" @click="generate">
      <span class="mono">{{ drafting ? 'Drafting…' : draft ? 'Re-draft' : 'Draft reply' }}</span>
    </button>

    <p v-if="error" class="mono err">{{ error }}</p>

    <div v-if="draft" class="result">
      <textarea class="input area" :value="draft.body" readonly rows="8" aria-label="Draft reply" />
      <div class="row">
        <button class="ghost" @click="copy">
          <span class="mono">{{ copied ? 'Copied' : 'Copy' }}</span>
        </button>
      </div>
      <p v-if="draft.grounding_ticket_ids.length" class="mono grounding">
        Grounded in:
        <span v-for="id in draft.grounding_ticket_ids" :key="id" class="chip">{{ id }}</span>
      </p>
      <p v-else class="mono grounding empty">No similar resolved tickets found.</p>
    </div>
  </CollapsibleSection>
</template>

<style scoped>
.hint {
  color: var(--ink-3);
  font-size: 11px;
  margin: 0 0 8px;
}
.err {
  color: var(--accent);
  font-size: 11px;
}
.result {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
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
  white-space: pre-wrap;
}
.row {
  display: flex;
  gap: 6px;
}
.grounding {
  font-size: 11px;
  color: var(--ink-2);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.grounding.empty {
  color: var(--ink-3);
}
.chip {
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 1px 6px;
  color: var(--ink);
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

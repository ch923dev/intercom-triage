<!-- TicketCard. Reference: tasks.md T033, plan §8b.
     Renders id mono · ago, title (line-clamped), summary, meta row, optional
     follow-up + notes row. -->
<script setup lang="ts">
import { computed } from 'vue';
import Mono from './Mono.vue';
import { useTweaksStore } from '@/stores/tweaks';
import { formatAgoFromDate } from '@/utils/time';
import type { Ticket } from '@/types/api';

interface Props {
  ticket: Ticket;
  overridden?: boolean;
  selected?: boolean;
}
const props = withDefaults(defineProps<Props>(), {
  overridden: false,
  selected: false,
});

const tweaks = useTweaksStore();

const dense = computed(() => tweaks.density === 'compact');
const rich = computed(() => tweaks.density === 'comfy');
const showSummary = computed(() => tweaks.showSummary && !dense.value);
const confColor = computed(() =>
  props.ticket.ai_confidence < 0.5 ? '#c34a2b' : 'var(--ink-3)',
);
const updatedAgo = computed(() => formatAgoFromDate(props.ticket.updated_at));
</script>

<template>
  <article
    class="card"
    :class="{ dense, rich, selected: props.selected, overridden: props.overridden }"
    draggable="true"
  >
    <div v-if="props.overridden" class="override-marker" title="Manually moved" />

    <header>
      <Mono>{{ props.ticket.id }}</Mono>
      <Mono>{{ updatedAgo }}</Mono>
    </header>

    <h3 class="title">{{ props.ticket.title }}</h3>

    <p v-if="showSummary" class="summary">{{ props.ticket.summary }}</p>

    <div class="meta">
      <span class="customer">{{ props.ticket.author.name ?? '—' }}</span>
      <Mono
        v-if="props.ticket.parts.length > 1"
        :color="'var(--ink-3)'"
        :size="9.5"
      >
        {{ props.ticket.parts.length }} msgs
      </Mono>
      <Mono
        v-if="tweaks.showConfidence"
        :color="confColor"
        :size="9.5"
        class="conf"
      >
        {{ Math.round(props.ticket.ai_confidence * 100) }}%
      </Mono>
    </div>
  </article>
</template>

<style scoped>
.card {
  position: relative;
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-card);
  padding: 11px 12px 12px;
  cursor: grab;
  transition: border-color 0.12s, background 0.12s, box-shadow 0.25s;
}
.card.dense {
  padding: 8px 10px;
}
.card:hover {
  background: var(--hover);
}
.card.selected {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}
.override-marker {
  position: absolute;
  left: -3px;
  top: 14px;
  width: 5px;
  height: 5px;
  background: var(--accent);
  transform: rotate(45deg);
}
header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.card.dense header {
  margin-bottom: 4px;
}
.title {
  margin: 0 0 8px;
  font-size: 13.5px;
  line-height: 1.35;
  color: var(--ink);
  font-weight: 500;
  letter-spacing: -0.005em;
  text-wrap: pretty;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card.dense .title {
  font-size: 12.5px;
  -webkit-line-clamp: 2;
}
.summary {
  margin: 0 0 9px;
  font-size: 11.5px;
  line-height: 1.45;
  color: var(--ink-2);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.card.rich .summary {
  -webkit-line-clamp: 4;
}
.meta {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.customer {
  font-size: 11px;
  color: var(--ink-2);
  max-width: 110px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conf {
  margin-left: auto;
}
</style>

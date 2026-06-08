<!-- Renders a list of NoteAttachment rows as thumbnails (images) and pills
     (non-images). Click a thumbnail to open it in the shared ImageLightbox
     (zoom / pan / ←→ / Esc). Non-image files download via `raw_url`. Each
     attachment has an × button that emits `remove(id)`. Used by both the
     per-entry slot in the timeline and the per-ticket bin. -->
<script setup lang="ts">
import { computed, ref } from 'vue';
import type { NoteAttachment } from '@/types/api';
import ImageLightbox from './ImageLightbox.vue';

interface Props {
  items: NoteAttachment[];
}
const props = defineProps<Props>();
const emit = defineEmits<{ (e: 'remove', id: number): void }>();

function isImage(a: NoteAttachment): boolean {
  return a.mime.startsWith('image/');
}

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes}B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)}KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)}MB`;
}

const images = computed(() => props.items.filter(isImage));
const files = computed(() => props.items.filter((x) => !isImage(x)));

const lightboxImages = computed(() =>
  images.value.map((a) => ({
    url: a.raw_url,
    caption: `${a.filename} · ${sizeLabel(a.size_bytes)}`,
  })),
);
const lightboxIndex = ref<number | null>(null);
</script>

<template>
  <div v-if="props.items.length" class="att-list">
    <div v-for="(a, i) in images" :key="a.id" class="att-thumb-wrap" :title="a.filename">
      <button type="button" class="att-thumb-btn" @click="lightboxIndex = i">
        <img v-if="a.thumb_url" :src="a.thumb_url" :alt="a.filename" class="att-thumb" />
        <span v-else class="att-thumb att-thumb-placeholder">…</span>
      </button>
      <button class="att-x" title="Remove" @click.stop="emit('remove', a.id)">×</button>
    </div>
    <span v-for="a in files" :key="a.id" class="att-pill" :title="a.filename">
      <a :href="a.raw_url" target="_blank" rel="noopener" class="att-pill-link">
        📄 {{ a.filename }} · {{ sizeLabel(a.size_bytes) }}
      </a>
      <button class="att-x att-x-inline" title="Remove" @click.prevent="emit('remove', a.id)">
        ×
      </button>
    </span>
  </div>

  <ImageLightbox v-model:index="lightboxIndex" :images="lightboxImages" />
</template>

<style scoped>
.att-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 4px;
}
.att-thumb-wrap {
  position: relative;
  width: 64px;
  height: 64px;
  display: inline-block;
}
.att-thumb-btn {
  display: block;
  width: 64px;
  height: 64px;
  padding: 0;
  border: none;
  background: none;
  cursor: zoom-in;
}
.att-thumb {
  width: 64px;
  height: 64px;
  object-fit: cover;
  border-radius: var(--radius-chip);
  border: var(--hairline) solid var(--line);
  background: var(--panel);
}
.att-thumb-placeholder {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--ink-3);
}
.att-x {
  position: absolute;
  top: -6px;
  right: -6px;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  border: var(--hairline) solid var(--line);
  background: var(--panel);
  color: var(--ink);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}
.att-x:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.att-x-inline {
  position: static;
  width: 16px;
  height: 16px;
  margin-left: 4px;
}
.att-pill {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 3px 8px;
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  background: var(--panel);
  font-family: var(--font-mono);
  font-size: 10px;
}
.att-pill-link {
  color: var(--ink);
  text-decoration: none;
}
.att-pill-link:hover {
  color: var(--accent);
}
</style>

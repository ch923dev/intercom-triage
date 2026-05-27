<!-- Renders a list of NoteAttachment rows as thumbnails (images) and pills
     (non-images). Click a thumbnail to open it inline in a lightbox overlay
     (Esc / backdrop / × to close, ←/→ to step between a note's images).
     Non-image files still download via `raw_url`. Each attachment has an ×
     button that emits `remove(id)`. Used by both the per-entry slot in the
     timeline and the per-ticket bin. -->
<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue';
import type { NoteAttachment } from '@/types/api';

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

const lightboxIndex = ref<number | null>(null);
const current = computed(() =>
  lightboxIndex.value === null ? null : (images.value[lightboxIndex.value] ?? null),
);

// Zoom + pan state for the open image. Reset whenever the image changes.
const MAX_ZOOM = 5;
const imgEl = ref<HTMLImageElement | null>(null);
const scale = ref(1);
const panX = ref(0);
const panY = ref(0);
const dragging = ref(false);
let dragMoved = false;
let dragStart = { x: 0, y: 0, panX: 0, panY: 0 };

function resetZoom() {
  scale.value = 1;
  panX.value = 0;
  panY.value = 0;
}

function clampPan() {
  const el = imgEl.value;
  if (!el) return;
  const maxX = (el.clientWidth * (scale.value - 1)) / 2;
  const maxY = (el.clientHeight * (scale.value - 1)) / 2;
  panX.value = Math.max(-maxX, Math.min(maxX, panX.value));
  panY.value = Math.max(-maxY, Math.min(maxY, panY.value));
}

function setScale(next: number) {
  scale.value = Math.max(1, Math.min(MAX_ZOOM, next));
  if (scale.value === 1) {
    panX.value = 0;
    panY.value = 0;
  } else {
    clampPan();
  }
}

function onWheel(e: WheelEvent) {
  setScale(scale.value * (e.deltaY < 0 ? 1.2 : 1 / 1.2));
}

function toggleZoom() {
  // A pan-drag fires a trailing click; don't let it flip the zoom.
  if (dragMoved) {
    dragMoved = false;
    return;
  }
  setScale(scale.value > 1 ? 1 : 2);
}

function onPointerDown(e: PointerEvent) {
  if (scale.value === 1) return;
  dragging.value = true;
  dragMoved = false;
  dragStart = { x: e.clientX, y: e.clientY, panX: panX.value, panY: panY.value };
  (e.target as HTMLElement).setPointerCapture(e.pointerId);
}
function onPointerMove(e: PointerEvent) {
  if (!dragging.value) return;
  if (Math.abs(e.clientX - dragStart.x) > 3 || Math.abs(e.clientY - dragStart.y) > 3) {
    dragMoved = true;
  }
  panX.value = dragStart.panX + (e.clientX - dragStart.x);
  panY.value = dragStart.panY + (e.clientY - dragStart.y);
  clampPan();
}
function onPointerUp() {
  dragging.value = false;
}

function open(i: number) {
  lightboxIndex.value = i;
}
function close() {
  lightboxIndex.value = null;
}
function step(delta: number) {
  if (lightboxIndex.value === null) return;
  const next = lightboxIndex.value + delta;
  if (next >= 0 && next < images.value.length) lightboxIndex.value = next;
}

// Capture-phase listener so Escape closes the lightbox without bubbling to the
// app-level handler (App.vue) that would otherwise close the whole flyout.
function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.stopPropagation();
    close();
  } else if (e.key === 'ArrowRight') {
    e.stopPropagation();
    step(1);
  } else if (e.key === 'ArrowLeft') {
    e.stopPropagation();
    step(-1);
  }
}

watch(current, (img) => {
  resetZoom();
  if (img) window.addEventListener('keydown', onKey, true);
  else window.removeEventListener('keydown', onKey, true);
});
onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true));
</script>

<template>
  <div v-if="props.items.length" class="att-list">
    <div v-for="(a, i) in images" :key="a.id" class="att-thumb-wrap" :title="a.filename">
      <button type="button" class="att-thumb-btn" @click="open(i)">
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

  <Teleport to="body">
    <div v-if="current" class="lightbox-scrim" @click="close">
      <button class="lightbox-btn lightbox-close" title="Close (Esc)" @click="close">×</button>
      <button
        v-if="images.length > 1"
        class="lightbox-btn lightbox-nav"
        title="Previous (←)"
        :disabled="lightboxIndex === 0"
        @click.stop="step(-1)"
      >
        ‹
      </button>
      <figure class="lightbox-fig" @click.stop @wheel.prevent="onWheel">
        <img
          ref="imgEl"
          :src="current.raw_url"
          :alt="current.filename"
          class="lightbox-img"
          :class="{ 'is-zoomed': scale > 1, 'is-dragging': dragging }"
          :style="{ transform: `translate(${panX}px, ${panY}px) scale(${scale})` }"
          draggable="false"
          @click="toggleZoom"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
        />
        <figcaption class="lightbox-cap mono">
          {{ current.filename }} · {{ sizeLabel(current.size_bytes)
          }}<template v-if="images.length > 1">
            · {{ (lightboxIndex ?? 0) + 1 }}/{{ images.length }}</template
          ><template v-if="scale > 1"> · {{ Math.round(scale * 100) }}%</template>
        </figcaption>
      </figure>
      <button
        v-if="images.length > 1"
        class="lightbox-btn lightbox-nav"
        title="Next (→)"
        :disabled="lightboxIndex === images.length - 1"
        @click.stop="step(1)"
      >
        ›
      </button>
    </div>
  </Teleport>
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

/* Lightbox — lifted surface above the flyout (z 40), so z 60. */
.lightbox-scrim {
  position: fixed;
  inset: 0;
  z-index: 60;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 24px;
  background: rgba(0, 0, 0, 0.72);
  animation: lightboxFade 0.14s ease-out;
}
.lightbox-fig {
  margin: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  max-width: 92vw;
  max-height: 88vh;
}
.lightbox-img {
  max-width: 92vw;
  max-height: 80vh;
  object-fit: contain;
  border-radius: var(--radius-card);
  box-shadow: var(--shadow);
  cursor: zoom-in;
  touch-action: none;
  transition: transform 0.08s ease-out;
}
.lightbox-img.is-zoomed {
  cursor: grab;
}
.lightbox-img.is-dragging {
  cursor: grabbing;
  transition: none;
}
.lightbox-cap {
  color: var(--ink-3);
  background: var(--panel);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  padding: 3px 8px;
}
.lightbox-btn {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--panel);
  color: var(--ink-2);
  border: var(--hairline) solid var(--line);
  border-radius: var(--radius-chip);
  cursor: pointer;
}
.lightbox-btn:hover:not(:disabled) {
  color: var(--accent);
  border-color: var(--accent);
}
.lightbox-btn:disabled {
  opacity: 0.35;
  cursor: default;
}
.lightbox-nav {
  width: 40px;
  height: 64px;
  font-size: 28px;
  line-height: 1;
}
.lightbox-close {
  position: fixed;
  top: 16px;
  right: 16px;
  width: 32px;
  height: 32px;
  font-size: 20px;
  line-height: 1;
}
@keyframes lightboxFade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}
</style>

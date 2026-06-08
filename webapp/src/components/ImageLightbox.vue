<!-- Reusable full-screen image viewer. Thumbnails live in the caller; this is
     only the overlay: zoom (wheel / click), pan (drag when zoomed), ←/→ between
     the set, Esc / backdrop / × to close. Controlled via v-model:index
     (null = closed). Shared by AttachmentList (operator-note files) and
     TicketConversation (inline Intercom images) so both look + behave the same. -->
<script setup lang="ts">
import { computed, ref, watch, onBeforeUnmount } from 'vue';

interface LightboxImage {
  url: string;
  caption?: string;
}
const props = defineProps<{ images: LightboxImage[]; index: number | null }>();
const emit = defineEmits<{ (e: 'update:index', value: number | null): void }>();

const current = computed(() => (props.index === null ? null : (props.images[props.index] ?? null)));

// Zoom + pan state for the open image. Reset whenever the image changes.
const MAX_ZOOM = 5;
const imgEl = ref<HTMLImageElement | null>(null);
const scale = ref(1);
const panX = ref(0);
const panY = ref(0);
const dragging = ref(false);
let dragMoved = false;
let dragStart = { x: 0, y: 0, panX: 0, panY: 0 };

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

function close() {
  emit('update:index', null);
}
function step(delta: number) {
  if (props.index === null) return;
  const next = props.index + delta;
  if (next >= 0 && next < props.images.length) emit('update:index', next);
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
  scale.value = 1;
  panX.value = 0;
  panY.value = 0;
  if (img) window.addEventListener('keydown', onKey, true);
  else window.removeEventListener('keydown', onKey, true);
});
onBeforeUnmount(() => window.removeEventListener('keydown', onKey, true));
</script>

<template>
  <Teleport to="body">
    <div v-if="current" class="lightbox-scrim" @click="close">
      <button class="lightbox-btn lightbox-close" title="Close (Esc)" @click="close">×</button>
      <button
        v-if="images.length > 1"
        class="lightbox-btn lightbox-nav"
        title="Previous (←)"
        :disabled="index === 0"
        @click.stop="step(-1)"
      >
        ‹
      </button>
      <figure class="lightbox-fig" @click.stop @wheel.prevent="onWheel">
        <img
          ref="imgEl"
          :src="current.url"
          :alt="current.caption ?? 'image'"
          class="lightbox-img"
          :class="{ 'is-zoomed': scale > 1, 'is-dragging': dragging }"
          :style="{ transform: `translate(${panX}px, ${panY}px) scale(${scale})` }"
          draggable="false"
          @click="toggleZoom"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
        />
        <figcaption
          v-if="current.caption || images.length > 1 || scale > 1"
          class="lightbox-cap mono"
        >
          {{ current.caption
          }}<template v-if="images.length > 1">
            · {{ (index ?? 0) + 1 }}/{{ images.length }}</template
          ><template v-if="scale > 1"> · {{ Math.round(scale * 100) }}%</template>
        </figcaption>
      </figure>
      <button
        v-if="images.length > 1"
        class="lightbox-btn lightbox-nav"
        title="Next (→)"
        :disabled="index === images.length - 1"
        @click.stop="step(1)"
      >
        ›
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
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

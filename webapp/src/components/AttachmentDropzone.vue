<!-- Drag/drop, paste, or click-to-browse zone. Emits a `files` event with
     the picked File[]. Owns no upload logic — caller decides what to do. -->
<script setup lang="ts">
import { ref } from 'vue';

const emit = defineEmits<{ (e: 'files', files: File[]): void }>();

const hover = ref(false);
const inputRef = ref<HTMLInputElement | null>(null);

function emitFiles(list: FileList | null | undefined) {
  if (!list || list.length === 0) return;
  emit('files', Array.from(list));
}

function onDrop(e: DragEvent) {
  e.preventDefault();
  hover.value = false;
  emitFiles(e.dataTransfer?.files);
}

function onPaste(e: ClipboardEvent) {
  emitFiles(e.clipboardData?.files);
}

function onPick(e: Event) {
  const input = e.target as HTMLInputElement;
  emitFiles(input.files);
  input.value = '';
}
</script>

<template>
  <div
    class="dropzone"
    :class="{ hover }"
    tabindex="0"
    @dragover.prevent="hover = true"
    @dragleave="hover = false"
    @drop="onDrop"
    @paste="onPaste"
    @click="inputRef?.click()"
  >
    <span class="mono dim">Drop files, paste, or click to browse</span>
    <input
      ref="inputRef"
      type="file"
      multiple
      hidden
      @change="onPick"
    />
  </div>
</template>

<style scoped>
.dropzone {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 12px;
  border: 1px dashed var(--line);
  border-radius: var(--radius-card);
  background: var(--panel);
  cursor: pointer;
  user-select: none;
  font-size: 11px;
}
.dropzone:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.dropzone.hover {
  border-color: var(--accent);
  background: var(--hover);
}
</style>

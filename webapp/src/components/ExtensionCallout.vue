<!-- Extension callout. Two modes:
       - top banner: discovery hint, dismissible (`mode="banner"`, default).
       - center placeholder: shown when the board is empty + the operator
         hasn't synced yet (`mode="empty"`).
     The Chrome extension is the only path that reaches Intercom — the
     backend has no Access Token — so the empty state points at it explicitly. -->
<script setup lang="ts">
import { ref } from 'vue';
import Mono from './Mono.vue';

interface Props {
  mode?: 'banner' | 'empty';
}
const props = withDefaults(defineProps<Props>(), { mode: 'banner' });

const STORAGE_KEY = 'triage-callout-dismissed-v1';
const dismissed = ref(localStorage.getItem(STORAGE_KEY) === '1');

function dismiss() {
  dismissed.value = true;
  localStorage.setItem(STORAGE_KEY, '1');
}
</script>

<template>
  <!-- Banner: top-of-page discovery hint -->
  <div v-if="props.mode === 'banner' && !dismissed" class="callout">
    <span class="dot" />
    <div class="text">
      <Mono :size="10">Chrome extension required</Mono>
      <span>
        The extension is how Triage reaches Intercom. Load <code>extension/</code> via
        <code>chrome://extensions</code> → enable Developer mode → "Load unpacked", then click the
        toolbar icon and press <b>Sync</b>.
      </span>
    </div>
    <button class="x" aria-label="Dismiss" @click="dismiss">✕</button>
  </div>

  <!-- Empty: replaces the board when zero tickets are stored -->
  <div v-else-if="props.mode === 'empty'" class="empty">
    <Mono :size="11">No tickets yet</Mono>
    <p class="lead">
      Open the Triage popup in Chrome and press <b>Sync</b> to pull conversations from your Intercom
      session.
    </p>
    <ol class="steps">
      <li>
        Load the extension: <code>chrome://extensions</code> → Developer mode → "Load unpacked" →
        select <code>extension/</code>.
      </li>
      <li>Click the toolbar icon. Enter your workspace id (e.g. <code>j3dxf22l</code>).</li>
      <li>Press <b>Sync</b>. The board fills as the backend categorizes.</li>
    </ol>
  </div>
</template>

<style scoped>
.callout {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 7px 20px;
  background: var(--accent-soft);
  border-bottom: var(--hairline) solid var(--line);
  flex: 0 0 auto;
}
.dot {
  width: 6px;
  height: 6px;
  background: var(--accent);
  border-radius: 50%;
  flex: 0 0 auto;
}
.text {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-size: 11.5px;
  color: var(--ink-2);
}
code {
  font-family: var(--font-mono);
  font-size: 10.5px;
  background: var(--chip-bg);
  padding: 1px 4px;
  border-radius: 2px;
  color: var(--ink);
}
.x {
  margin-left: auto;
  border: 0;
  background: transparent;
  color: var(--ink-3);
  cursor: pointer;
  font-size: 12px;
  flex: 0 0 auto;
}

.empty {
  flex: 1;
  align-self: center;
  margin: 60px auto;
  max-width: 520px;
  padding: 24px 28px;
  border: var(--hairline) solid var(--line);
  border-radius: 6px;
  background: var(--panel);
  color: var(--ink-2);
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.empty .lead {
  margin: 0;
  font-size: 13px;
  color: var(--ink);
  line-height: 1.5;
}
.empty .steps {
  margin: 4px 0 0;
  padding-left: 18px;
  font-size: 12px;
  line-height: 1.55;
}
.empty .steps li {
  margin-bottom: 4px;
}
</style>

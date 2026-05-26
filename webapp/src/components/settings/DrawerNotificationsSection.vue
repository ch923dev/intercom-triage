<script setup lang="ts">
import { ref } from 'vue';
import Mono from '../Mono.vue';
import { useTweaksStore } from '@/stores/tweaks';
import { permission, requestPermission, supported } from '@/utils/notify';

const tweaks = useTweaksStore();
const notifyHint = ref('');

/** Desktop notifications toggle — turning it on prompts for browser
 *  permission the first time; a denial reverts the checkbox with a hint. */
async function onToggleNotifications(event: Event) {
  const input = event.target as HTMLInputElement;
  notifyHint.value = '';
  if (!input.checked) {
    tweaks.setDesktopNotifications(false);
    return;
  }
  if (!supported()) {
    notifyHint.value = 'This browser does not support notifications.';
    input.checked = false;
    return;
  }
  let perm = permission();
  if (perm === 'default') perm = await requestPermission();
  if (perm === 'granted') {
    tweaks.setDesktopNotifications(true);
  } else {
    notifyHint.value = 'Notifications blocked — allow them in browser site settings.';
    input.checked = false;
  }
}
</script>

<template>
  <section>
    <Mono>Desktop notifications</Mono>
    <label class="check">
      <input
        type="checkbox"
        :checked="tweaks.desktopNotifications"
        @change="onToggleNotifications"
      />
      <span class="sentence">Notify on the desktop when a follow-up is due</span>
    </label>
    <p v-if="notifyHint" class="hint">{{ notifyHint }}</p>
    <p v-else class="hint">
      A browser notification fires alongside the in-app alarm, even when this tab is in the
      background.
    </p>
  </section>
</template>

<style scoped>
section {
  padding: 16px 0;
  border-bottom: var(--hairline) solid var(--line-soft);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.hint {
  margin: 0;
  font-size: 11px;
  color: var(--ink-3);
}
.check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12.5px;
  color: var(--ink);
  text-transform: capitalize;
  cursor: pointer;
}
.check .sentence {
  text-transform: none;
}
</style>

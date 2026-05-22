<!-- Mono micro-label. Plan §8b: 10–11px, .04em letter-spacing, uppercase. -->
<script setup lang="ts">
interface Props {
  color?: string;
  size?: number;
}
const props = withDefaults(defineProps<Props>(), { size: 10.5, color: undefined });
</script>

<template>
  <span class="mono" :style="{ color: props.color ?? 'var(--ink-3)', fontSize: `${props.size}px` }">
    <slot />
  </span>
</template>

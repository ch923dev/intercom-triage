<!-- 8px (default) color square per plan §8b. Linear-style swatch. -->
<script setup lang="ts">
interface Props {
  color: string | null;
  size?: number;
}
const props = withDefaults(defineProps<Props>(), { size: 8 });
</script>

<template>
  <span
    v-if="props.color"
    class="cat-dot"
    :style="{
      width: `${props.size}px`,
      height: `${props.size}px`,
      background: props.color,
    }"
  />
</template>

<style scoped>
.cat-dot {
  display: inline-block;
  border-radius: 2px;
  flex: 0 0 auto;
}
</style>

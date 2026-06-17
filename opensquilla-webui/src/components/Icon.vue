<template>
  <span class="icon" v-html="svg"></span>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { getIconSvg, type IconName } from '@/utils/icons'

const props = defineProps<{
  name: IconName
  size?: number
}>()

const svg = computed(() => getIconSvg(props.name, props.size ?? 16))
</script>

<style scoped>
.icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  line-height: 1;
}
.icon :deep(svg) {
  display: block;
}
</style>

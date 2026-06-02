<template>
  <div class="placeholder-view">
    <h2>{{ title }}</h2>
    <p class="hint">This view will be migrated in a later phase.</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'

const route = useRoute()
const title = computed(() => (route.meta?.title as string) || 'View')
</script>

<style scoped>
.placeholder-view {
  padding: 2rem;
  text-align: center;
}
.placeholder-view h2 {
  margin-bottom: 0.5rem;
  color: var(--text-primary, #1a1a1a);
}
.placeholder-view .hint {
  color: var(--text-muted, #666);
}
</style>

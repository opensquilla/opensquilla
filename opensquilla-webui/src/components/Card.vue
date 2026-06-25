<template>
  <div class="card">
    <div v-if="title" class="card__header">
      <h3 class="card__title">{{ title }}</h3>
    </div>
    <div class="card__body">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  title?: string
}>()
</script>

<style scoped>
.card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
  transition: border-color var(--transition), box-shadow var(--transition);
}

.card:hover {
  border-color: var(--border-strong);
}

.card__header {
  padding: var(--sp-4) var(--sp-5) 0;
}

.card__title {
  margin: 0;
  font-size: var(--fs-md);
  font-weight: 700;
  color: var(--text);
  letter-spacing: var(--track-display);
  line-height: 1.3;
}

.card__body {
  padding: var(--sp-4) var(--sp-5);
}

.card__header + .card__body {
  padding-top: var(--sp-3);
}
</style>

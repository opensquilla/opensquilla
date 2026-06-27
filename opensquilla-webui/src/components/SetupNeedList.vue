<template>
  <div v-if="needs.length > 0" class="setup-need-list" :aria-label="label">
    <span>{{ label }}</span>
    <ul>
      <li v-for="(item, i) in needs" :key="i">{{ item }}</li>
    </ul>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  items?: string[]
  label: string
}>()

const needs = computed(() => (props.items || []).filter(Boolean))
</script>

<style scoped>
.setup-need-list {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  font-size: var(--fs-sm);
  padding: var(--sp-3);
}

.setup-need-list span {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
}

.setup-need-list ul {
  color: var(--text-muted);
  list-style: none;
  margin: var(--sp-1) 0 0;
  padding: 0;
}

.setup-need-list li::before {
  color: var(--accent);
  content: "\2022";
  margin-right: 6px;
}
</style>

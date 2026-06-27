<template>
  <details class="thinking-fold">
    <summary class="thinking-fold__summary">
      <Icon class="thinking-fold__chevron" name="chevronRight" :size="12" />
      <span>{{ summary }}</span>
    </summary>
    <div class="thinking-fold__body">{{ part.text }}</div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import type { ChatPart } from '@/types/parts'

const props = defineProps<{ part: Extract<ChatPart, { type: 'reasoning' }> }>()

const summary = computed(() => {
  const seconds = props.part.seconds || 0
  if (seconds < 1) return 'Thought process'
  if (seconds < 60) return `Thought for ${seconds}s`
  return `Thought for ${Math.floor(seconds / 60)}m ${seconds % 60}s`
})
</script>

<style scoped>
/* Reasoning disclosure — mirrors the thinking-fold treatment that ChatView's
 * live work card uses, kept local so this part needs no shared sheet. */
.thinking-fold { margin: 0 0 0.5rem; font-size: 0.8125rem; color: var(--text-dim); }
.thinking-fold__summary {
  display: inline-flex; align-items: center; gap: 0.375rem;
  padding: 0.125rem 0.25rem; border-radius: var(--radius-sm);
  cursor: pointer; list-style: none; color: var(--text-dim); line-height: 1.5;
}
.thinking-fold__summary::-webkit-details-marker { display: none; }
.thinking-fold__summary:hover { color: var(--text-muted); }
.thinking-fold__summary:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}
.thinking-fold__chevron { flex-shrink: 0; transition: transform 0.12s ease; }
.thinking-fold[open] > .thinking-fold__summary .thinking-fold__chevron { transform: rotate(90deg); }
.thinking-fold__body {
  margin: 0.25rem 0 0.375rem; padding: 0.375rem 0.75rem;
  border-left: 2px solid var(--border); color: var(--text-muted);
  line-height: 1.55; white-space: pre-wrap; word-break: break-word;
  max-height: 16rem; overflow-y: auto;
}
@media (prefers-reduced-motion: reduce) {
  .thinking-fold__chevron { transition: none; }
}
</style>

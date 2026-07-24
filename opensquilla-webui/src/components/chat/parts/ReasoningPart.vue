<template>
  <section v-if="embedded" class="thinking-block">
    <div class="thinking-block__header">
      <Icon name="skills" :size="12" aria-hidden="true" />
      <span>{{ summary }}</span>
    </div>
    <div class="thinking-block__body">{{ part.text }}</div>
  </section>
  <details v-else class="thinking-fold">
    <summary class="thinking-fold__summary">
      <Icon class="thinking-fold__chevron" name="chevronRight" :size="12" />
      <span>{{ summary }}</span>
    </summary>
    <div class="thinking-fold__body">{{ part.text }}</div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import type { ChatPart } from '@/types/parts'

const { t } = useI18n()

const props = defineProps<{
  part: Extract<ChatPart, { type: 'reasoning' }>
  embedded?: boolean
}>()

const summary = computed(() => {
  const seconds = props.part.seconds || 0
  if (seconds < 1) return t('chat.thoughtProcess')
  if (seconds < 60) return t('chat.thoughtForSeconds', { seconds })
  return t('chat.thoughtForMinutes', { minutes: Math.floor(seconds / 60), seconds: seconds % 60 })
})
</script>

<style scoped>
.thinking-block {
  min-width: 0;
}
.thinking-block__header {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  margin-bottom: 0.25rem;
  color: var(--text-dim);
  font-size: 0.75rem;
  line-height: 1.5;
}
.thinking-block__body {
  color: var(--text-muted);
  font-size: 0.8125rem;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-word;
}

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
  box-shadow: var(--focus-ring);
}
.thinking-fold__chevron { flex-shrink: 0; transition: transform var(--dur-fast) var(--ease-standard); }
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

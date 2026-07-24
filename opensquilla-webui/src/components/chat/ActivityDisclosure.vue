<template>
  <details
    class="assistant-activity"
    :open="defaultOpen"
    data-testid="assistant-activity"
  >
    <summary
      class="assistant-activity__summary"
      @click.stop
    >
      <Icon
        class="assistant-activity__chevron"
        name="chevronRight"
        :size="13"
        aria-hidden="true"
      />
      <span class="assistant-activity__label">
        {{ t('chat.activitySteps', { count: stepCount }) }}
      </span>
      <span v-if="reasoningDuration" class="assistant-activity__meta">
        {{ reasoningDuration }}
      </span>
      <span v-if="failureCount" class="assistant-activity__failure">
        {{ t('chat.activityFailures', { count: failureCount }) }}
      </span>
    </summary>
    <div class="assistant-activity__body">
      <slot />
    </div>
  </details>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'

const props = defineProps<{
  stepCount: number
  failureCount: number
  reasoningSeconds?: number
  defaultOpen?: boolean
}>()

const { t } = useI18n()

const reasoningDuration = computed(() => {
  const seconds = Math.max(0, Math.floor(props.reasoningSeconds || 0))
  if (seconds < 1) return ''
  if (seconds < 60) return t('chat.thoughtForSeconds', { seconds })
  return t('chat.thoughtForMinutes', {
    minutes: Math.floor(seconds / 60),
    seconds: seconds % 60,
  })
})
</script>

<style scoped>
.assistant-activity {
  margin: 0 0 0.625rem;
  color: var(--text-muted);
}

.assistant-activity__summary {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  min-height: 1.75rem;
  gap: 0.375rem;
  padding: 0.1875rem 0.375rem;
  border-radius: var(--radius-sm);
  color: var(--text-dim);
  cursor: pointer;
  list-style: none;
  font-size: 0.75rem;
  line-height: 1.4;
}

.assistant-activity__summary::-webkit-details-marker {
  display: none;
}

.assistant-activity__summary:hover {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.assistant-activity__summary:focus-visible {
  outline: none;
  box-shadow: var(--focus-ring);
}

.assistant-activity__chevron {
  flex-shrink: 0;
  transition: transform var(--dur-fast) var(--ease-standard);
}

.assistant-activity[open] > .assistant-activity__summary .assistant-activity__chevron {
  transform: rotate(90deg);
}

.assistant-activity__label {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.assistant-activity__meta,
.assistant-activity__failure {
  white-space: nowrap;
}

.assistant-activity__meta::before,
.assistant-activity__failure::before {
  content: "·";
  margin-right: 0.375rem;
  color: var(--text-dim);
}

.assistant-activity__failure {
  color: var(--danger);
}

.assistant-activity__body {
  display: grid;
  gap: 0.5rem;
  margin: 0.25rem 0 0.25rem 0.375rem;
  padding: 0.125rem 0 0.125rem 0.75rem;
  border-left: 1px solid var(--border);
  min-width: 0;
}

@media (max-width: 480px) {
  .assistant-activity__summary {
    flex-wrap: wrap;
  }

  .assistant-activity__body {
    margin-left: 0.25rem;
    padding-left: 0.5rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-activity__chevron {
    transition: none;
  }
}
</style>

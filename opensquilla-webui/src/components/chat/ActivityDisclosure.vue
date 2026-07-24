<template>
  <section
    v-if="isLive"
    class="assistant-activity assistant-activity--live"
    data-testid="assistant-activity"
    data-share-activity="true"
    data-share-expanded="true"
  >
    <header class="assistant-activity__live-head" data-share-activity-label>
      <span
        class="assistant-activity__live-dot"
        :class="{ 'is-active': !stale }"
        aria-hidden="true"
      />
      <span
        class="assistant-activity__live-label"
        :class="{ 'is-active': !stale }"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        {{ phaseLabel || t('chat.activityWorking') }}
      </span>
      <span
        v-if="elapsedLabel"
        class="assistant-activity__live-elapsed"
        aria-hidden="true"
      >
        · {{ elapsedLabel }}
      </span>
    </header>
    <div class="assistant-activity__body" data-share-activity-body>
      <slot />
    </div>
  </section>

  <section
    v-else
    class="assistant-activity assistant-activity--settled"
    :class="{
      'assistant-activity--failed': lifecycle === 'failed',
      'assistant-activity--interrupted': lifecycle === 'interrupted',
    }"
    data-testid="assistant-activity"
    data-share-activity="true"
    :data-share-expanded="open ? 'true' : 'false'"
  >
    <button
      type="button"
      class="assistant-activity__summary"
      data-share-activity-label
      data-share-control
      :aria-expanded="open"
      @click.stop="open = !open"
    >
      <span class="assistant-activity__label">{{ resolvedSummaryLabel }}</span>
      <span v-if="failureCount" class="assistant-activity__failure">
        {{ resolvedFailureLabel }}
      </span>
      <Icon
        class="assistant-activity__summary-arrow"
        name="chevronRight"
        :size="13"
        aria-hidden="true"
      />
    </button>
    <div v-show="open" class="assistant-activity__body" data-share-activity-body>
      <slot />
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import {
  readAssistantActivityExpansion,
  writeAssistantActivityExpansion,
} from '@/utils/chat/activityDisclosureState'

const props = withDefaults(defineProps<{
  lifecycle?: 'working' | 'answering' | 'settled' | 'failed' | 'interrupted'
  stepCount: number
  failureCount: number
  durationSeconds?: number
  completionConfirmed?: boolean
  summaryLabel?: string
  phaseLabel?: string
  elapsedLabel?: string
  stale?: boolean
  defaultOpen?: boolean
  stateKey?: string
  continuityKey?: string
}>(), {
  lifecycle: 'settled',
  durationSeconds: 0,
  completionConfirmed: false,
  summaryLabel: '',
  phaseLabel: '',
  elapsedLabel: '',
  stale: false,
  defaultOpen: false,
  stateKey: '',
  continuityKey: '',
})

const { t } = useI18n()
const initialOpen = () =>
  props.defaultOpen
  || props.lifecycle === 'failed'
  || props.lifecycle === 'interrupted'
const open = ref(readAssistantActivityExpansion(
  props.stateKey,
  initialOpen(),
  props.continuityKey,
))

watch(open, expanded => {
  writeAssistantActivityExpansion(props.stateKey, expanded, props.continuityKey)
})

watch(() => [props.stateKey, props.continuityKey] as const, ([key, continuityKey]) => {
  open.value = readAssistantActivityExpansion(key, initialOpen(), continuityKey)
})

watch(
  () => [props.lifecycle, props.defaultOpen] as const,
  ([lifecycle, defaultOpen], [previousLifecycle, previousDefaultOpen]) => {
    const becameTerminal = (
      lifecycle === 'failed'
      || lifecycle === 'interrupted'
    ) && (
      previousLifecycle !== 'failed'
      && previousLifecycle !== 'interrupted'
    )
    if (becameTerminal || (defaultOpen && !previousDefaultOpen)) {
      open.value = true
    }
  },
)

const isLive = computed(() =>
  props.lifecycle === 'working' || props.lifecycle === 'answering',
)

const resolvedSummaryLabel = computed(() => {
  if (props.summaryLabel) return props.summaryLabel
  const seconds = Math.max(0, Math.floor(props.durationSeconds || 0))
  if (seconds > 0) {
    if (seconds < 60) return t('chat.workedForSeconds', { seconds })
    return t('chat.workedForMinutes', {
      minutes: Math.floor(seconds / 60),
      seconds: seconds % 60,
    })
  }
  return t(
    props.lifecycle === 'settled' && props.completionConfirmed
      ? 'chat.activityCompletedItems'
      : 'chat.activityItems',
    { count: Math.max(1, props.stepCount) },
  )
})

const resolvedFailureLabel = computed(() =>
  t(
    props.lifecycle === 'settled' && props.completionConfirmed
      ? 'chat.activityFailuresRecovered'
      : 'chat.activityFailures',
    { count: props.failureCount },
  ),
)
</script>

<style scoped>
.assistant-activity {
  min-width: 0;
  margin: 0 0 0.625rem;
  color: var(--text-muted);
}

.assistant-activity--live {
  display: grid;
  gap: 0.25rem;
  margin-top: 0.25rem;
}

.assistant-activity__live-head {
  display: flex;
  align-items: center;
  min-width: 0;
  min-height: 1.75rem;
  gap: 0.5rem;
  color: color-mix(in srgb, var(--text) 90%, transparent);
  font-size: 0.875rem;
  line-height: 1.5;
}

.assistant-activity__live-dot {
  width: 0.4375rem;
  height: 0.4375rem;
  flex: 0 0 auto;
  border-radius: var(--radius-full);
  background: var(--accent);
}

.assistant-activity__live-dot.is-active {
  animation: assistant-activity-pulse 2.3s var(--ease-standard) infinite;
}

.assistant-activity__live-label {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.assistant-activity__live-label.is-active {
  background: linear-gradient(
    90deg,
    color-mix(in srgb, var(--text) 82%, transparent) 15%,
    color-mix(in srgb, var(--text) 52%, transparent) 48%,
    color-mix(in srgb, var(--text) 82%, transparent) 82%
  );
  background-size: 220% 100%;
  background-clip: text;
  color: transparent;
  animation: assistant-activity-shimmer 2.3s linear infinite;
}

.assistant-activity__live-elapsed {
  flex: 0 0 auto;
  color: color-mix(in srgb, var(--text) 46%, transparent);
  font-size: 0.75rem;
  font-variant-numeric: tabular-nums;
}

.assistant-activity__summary {
  display: inline-flex;
  align-items: center;
  max-width: 100%;
  min-height: 1.75rem;
  gap: 0.375rem;
  padding: 0.1875rem 0.25rem;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: color-mix(in srgb, var(--text) 56%, transparent);
  cursor: pointer;
  font: inherit;
  font-size: 0.75rem;
  line-height: 1.4;
  text-align: left;
  transition: color var(--dur-fast) var(--ease-standard);
}

.assistant-activity__summary:hover {
  color: color-mix(in srgb, var(--text) 78%, transparent);
  background: transparent;
}

.assistant-activity__summary:focus-visible {
  outline: none;
  box-shadow: none;
  color: color-mix(in srgb, var(--text) 78%, transparent);
}

.assistant-activity__label {
  min-width: 0;
  white-space: normal;
  overflow-wrap: anywhere;
}

.assistant-activity__failure {
  flex: 0 0 auto;
  color: var(--danger);
  white-space: nowrap;
}

.assistant-activity__failure::before {
  content: "·";
  margin-right: 0.375rem;
  color: var(--text-dim);
}

.assistant-activity__summary-arrow {
  flex: 0 0 auto;
  color: currentColor;
  opacity: 0;
  transform: translateX(-0.125rem);
  transform-origin: center;
  transition:
    opacity var(--dur-fast) var(--ease-standard),
    transform var(--dur-fast) var(--ease-standard);
}

.assistant-activity__summary:hover .assistant-activity__summary-arrow,
.assistant-activity__summary:focus-visible .assistant-activity__summary-arrow {
  opacity: 0.8;
  transform: translateX(0);
}

.assistant-activity__summary[aria-expanded="true"] .assistant-activity__summary-arrow {
  opacity: 0.55;
  transform: rotate(90deg);
}

.assistant-activity__summary[aria-expanded="true"]:hover .assistant-activity__summary-arrow,
.assistant-activity__summary[aria-expanded="true"]:focus-visible .assistant-activity__summary-arrow {
  opacity: 0.8;
  transform: rotate(90deg);
}

.assistant-activity__body {
  display: grid;
  min-width: 0;
  gap: 0.25rem;
  margin: 0.125rem 0 0.25rem;
  padding: 0;
  border: 0;
  background: transparent;
}

@keyframes assistant-activity-pulse {
  0%,
  100% { opacity: 0.45; }
  50% { opacity: 1; }
}

@keyframes assistant-activity-shimmer {
  from { background-position: 100% 0; }
  to { background-position: -120% 0; }
}

@media (max-width: 480px) {
  .assistant-activity__summary {
    flex-wrap: wrap;
  }

  .assistant-activity__live-head {
    gap: 0.375rem;
  }
}

@media (prefers-reduced-motion: reduce) {
  .assistant-activity__summary,
  .assistant-activity__summary-arrow {
    transition: none;
  }

  .assistant-activity__live-dot.is-active,
  .assistant-activity__live-label.is-active {
    animation: none;
  }

  .assistant-activity__live-label.is-active {
    background: none;
    color: color-mix(in srgb, var(--text) 82%, transparent);
  }
}
</style>

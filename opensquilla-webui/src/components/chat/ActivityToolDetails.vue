<template>
  <div class="activity-tool-details">
    <div
      v-for="(line, index) in projection.lines"
      :key="`${line.kind}:${index}`"
      class="activity-tool-details__line"
      :class="`activity-tool-details__line--${line.kind}`"
    >
      <template v-if="line.kind === 'bytes'">
        {{ t('shared.runTrace.activityBytesWritten', { size: formatBytes(line.bytes) }) }}
      </template>
      <template v-else-if="line.kind === 'content-size'">
        {{
          t('shared.runTrace.activityContentSize', {
            lines: formatNumber(line.lines),
            characters: formatNumber(line.characters),
          })
        }}
      </template>
      <template v-else-if="line.kind === 'published'">
        {{ t('shared.runTrace.activityPublished') }}
      </template>
      <template v-else>
        {{ line.text }}
      </template>
    </div>
    <button
      v-if="projection.rawContent"
      type="button"
      class="activity-tool-details__view"
      data-share-control
      @click.stop="showRawDetails"
    >
      {{ t('shared.runTrace.activityViewDetails') }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatToolCallRenderItem, ToolResultContext } from '@/types/chat'
import { projectActivityToolDetail } from '@/utils/chat/activityToolDetails'

const props = defineProps<{
  call: ChatToolCallRenderItem
  label: string
  operationKey: string
}>()

const emit = defineEmits<{
  showResult: [content: string, title: string, context?: ToolResultContext]
}>()

const { locale, t } = useI18n()
const projection = computed(() =>
  projectActivityToolDetail(props.call, props.operationKey),
)

function formatNumber(value: number): string {
  return new Intl.NumberFormat(locale.value).format(value)
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return '0 B'
  if (value < 1024) return `${formatNumber(value)} B`
  const units = ['KB', 'MB', 'GB']
  let amount = value / 1024
  let unitIndex = 0
  while (amount >= 1024 && unitIndex < units.length - 1) {
    amount /= 1024
    unitIndex += 1
  }
  const digits = amount >= 10 ? 0 : 1
  return `${new Intl.NumberFormat(locale.value, {
    maximumFractionDigits: digits,
  }).format(amount)} ${units[unitIndex]}`
}

function showRawDetails() {
  const detail = projection.value
  emit(
    'showResult',
    detail.rawContent,
    `${props.label} · ${t('shared.runTrace.activityDetailsTitle')}`,
    {
      toolName: props.call.name,
      inputRaw: props.call.inputRaw || props.call.inputPreview,
      section: detail.rawSection,
    },
  )
}
</script>

<style scoped>
.activity-tool-details {
  display: grid;
  gap: 0.125rem;
  min-width: 0;
  padding: 0.0625rem 0 0.375rem;
  font-size: 0.75rem;
  line-height: 1.45;
}

.activity-tool-details__line {
  min-width: 0;
  overflow: hidden;
  color: color-mix(in srgb, var(--text) 46%, transparent);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.activity-tool-details__line--target {
  color: color-mix(in srgb, var(--text) 62%, transparent);
}

.activity-tool-details__line--code {
  color: color-mix(in srgb, var(--text) 62%, transparent);
  font-family: var(--font-mono);
  font-variant-ligatures: none;
}

.activity-tool-details__line--error {
  color: var(--danger);
}

.activity-tool-details__view {
  justify-self: start;
  margin: 0.0625rem 0 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: color-mix(in srgb, var(--text) 46%, transparent);
  cursor: pointer;
  font: inherit;
  font-size: 0.71875rem;
  line-height: 1.45;
  transition: color var(--dur-fast) var(--ease-standard);
}

.activity-tool-details__view:hover,
.activity-tool-details__view:focus-visible {
  outline: none;
  color: color-mix(in srgb, var(--text) 78%, transparent);
  text-decoration: underline;
  text-underline-offset: 0.15em;
}

@media (prefers-reduced-motion: reduce) {
  .activity-tool-details__view {
    transition: none;
  }
}
</style>

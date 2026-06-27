<template>
  <RunTrace
    :items="items"
    :variant="variant"
    :is-tool-group-open="isToolGroupOpen"
    :is-tool-item-open="isToolItemOpen"
    :tool-group-status-text="toolGroupStatusText"
    :tool-status-text="toolStatusText"
    :tool-secondary-text="toolSecondaryText"
    :tool-elapsed-text="toolElapsedText"
    @toggle-group="$emit('toggleGroup', $event)"
    @toggle-item="$emit('toggleItem', $event)"
    @show-result="(content, title) => $emit('showResult', content, title)"
  />
</template>

<script setup lang="ts">
import RunTrace from '@/components/run/RunTrace.vue'
import type {
  ChatStreamTimelineItem,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
} from '@/types/chat'

defineProps<{
  items: ChatStreamTimelineItem[]
  isToolGroupOpen: (groupId: string) => boolean
  isToolItemOpen: (renderKey: string) => boolean
  toolGroupStatusText: (group: ChatToolCallGroup) => string
  toolStatusText: (call: ChatToolCallRenderItem) => string
  toolSecondaryText: (call: ChatToolCallRenderItem) => string
  toolElapsedText?: (call: ChatToolCallRenderItem) => string
  variant?: 'checklist'
}>()

defineEmits<{
  toggleGroup: [groupId: string]
  toggleItem: [renderKey: string]
  showResult: [content: string, title: string]
}>()
</script>

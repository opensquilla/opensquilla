<template>
  <template v-for="(message, index) in messages" :key="message.id || `${message.role}-${index}`">
    <slot
      v-if="message.isRouterStrip"
      name="router-strip"
      :message="message"
      :index="index"
    />
    <UserMessage
      v-else-if="message.displayRole === 'user'"
      :message="message"
      :strip-time-prefix="stripTimePrefix"
      @copy="$emit('copyMessage', $event)"
      @edit="$emit('editMessage', $event)"
    />
    <AssistantMessage
      v-else-if="message.displayRole === 'assistant'"
      :message="message"
      :index="index"
      :assistant-avatar-url="assistantAvatarUrl"
      :render-markdown="renderMarkdown"
      :fmt-tok="fmtTok"
      :tool-call-groups="toolCallGroups"
      :is-tool-group-open="isToolGroupOpen"
      :is-tool-item-open="isToolItemOpen"
      :tool-group-status-text="toolGroupStatusText"
      :tool-status-text="toolStatusText"
      :tool-secondary-text="toolSecondaryText"
      @copy="$emit('copyMessage', $event)"
      @regenerate="$emit('regenerateMessage', $event)"
      @download-artifact="$emit('downloadArtifact', $event)"
      @toggle-tool-group="$emit('toggleToolGroup', $event)"
      @toggle-tool-item="$emit('toggleToolItem', $event)"
      @show-tool-result="(content, title) => $emit('showToolResult', content, title)"
    />
    <SystemMessage
      v-else
      :message="message"
      :subagent-summary="subagentSummary"
      :subagent-body="subagentBody"
    />
  </template>
</template>

<script setup lang="ts">
import AssistantMessage from '@/components/chat/AssistantMessage.vue'
import SystemMessage from '@/components/chat/SystemMessage.vue'
import UserMessage from '@/components/chat/UserMessage.vue'
import type {
  ChatRenderedMessage,
  ChatToolCall,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
} from '@/types/chat'
import type { ArtifactPayload } from '@/types/rpc'

defineProps<{
  messages: ChatRenderedMessage[]
  assistantAvatarUrl: string
  stripTimePrefix: (text: string) => string
  renderMarkdown: (text: string) => string
  fmtTok: (value: number) => string
  subagentSummary: (text: string) => string
  subagentBody: (text: string) => string
  toolCallGroups: (calls: ChatToolCall[], baseKey: string) => ChatToolCallGroup[]
  isToolGroupOpen: (groupId: string) => boolean
  isToolItemOpen: (renderKey: string) => boolean
  toolGroupStatusText: (group: ChatToolCallGroup) => string
  toolStatusText: (call: ChatToolCallRenderItem) => string
  toolSecondaryText: (call: ChatToolCallRenderItem) => string
}>()

defineEmits<{
  copyMessage: [message: ChatRenderedMessage]
  editMessage: [message: ChatRenderedMessage]
  regenerateMessage: [message: ChatRenderedMessage]
  downloadArtifact: [artifact: ArtifactPayload]
  toggleToolGroup: [groupId: string]
  toggleToolItem: [renderKey: string]
  showToolResult: [content: string, title: string]
}>()
</script>

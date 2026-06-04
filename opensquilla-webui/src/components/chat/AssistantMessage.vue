<template>
  <div class="msg-ai" :data-message-id="message.messageId">
    <div class="msg-ai-avatar">
      <img class="msg-ai-avatar__img" :src="assistantAvatarUrl" alt="" aria-hidden="true" />
    </div>
    <div class="msg-ai-main">
      <ToolCallTimeline
        v-if="message.timelineItems?.length"
        :items="message.timelineItems"
        :is-tool-group-open="isToolGroupOpen"
        :is-tool-item-open="isToolItemOpen"
        :tool-group-status-text="toolGroupStatusText"
        :tool-status-text="toolStatusText"
        :tool-secondary-text="toolSecondaryText"
        @toggle-group="$emit('toggleToolGroup', $event)"
        @toggle-item="$emit('toggleToolItem', $event)"
        @show-result="(content, title) => $emit('showToolResult', content, title)"
      />
      <template v-else>
        <div v-if="message.text" class="msg-ai-text" v-html="renderMarkdown(message.text)" />
      </template>

      <ToolCallTimeline
        v-if="!message.timelineItems?.length && message.toolCalls?.length"
        :items="legacyTimelineItems"
        :is-tool-group-open="isToolGroupOpen"
        :is-tool-item-open="isToolItemOpen"
        :tool-group-status-text="toolGroupStatusText"
        :tool-status-text="toolStatusText"
        :tool-secondary-text="toolSecondaryText"
        @toggle-group="$emit('toggleToolGroup', $event)"
        @toggle-item="$emit('toggleToolItem', $event)"
        @show-result="(content, title) => $emit('showToolResult', content, title)"
      />

      <ChatArtifactList
        v-if="message.artifacts?.length"
        :artifacts="message.artifacts"
        @download="$emit('downloadArtifact', $event)"
      />

      <div class="msg-ai-footer">
        <div v-if="message.meta" class="msg-ai-meta">
          <span v-if="message.meta.model" class="msg-meta__model">{{ message.meta.modelShort }}</span>
          <span v-if="message.meta.hasTokens">
            &#8593;{{ fmtTok(message.meta.input) }} &#8595;{{ fmtTok(message.meta.output) }}
          </span>
          <span v-if="message.meta.cachedTokens">cache:{{ fmtTok(message.meta.cachedTokens) }}</span>
          <span v-if="message.meta.reasoningTokens">think:{{ fmtTok(message.meta.reasoningTokens) }}</span>
          <span v-if="message.meta.costUsd">${{ message.meta.costUsd.toFixed(6).replace(/\.?0+$/, '') }}</span>
          <span v-if="message.meta.hasSaved" class="savings-indicator">{{ message.meta.savedLabel }}</span>
        </div>
        <div class="msg-ai-actions">
          <button type="button" class="msg-action" title="Copy" @click="$emit('copy', message)">
            <Icon name="copy" :size="12" />
          </button>
          <button type="button" class="msg-action" title="Regenerate" @click="$emit('regenerate', message)">
            <Icon name="refresh" :size="12" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import ChatArtifactList from '@/components/chat/ChatArtifactList.vue'
import ToolCallTimeline from '@/components/chat/ToolCallTimeline.vue'
import type {
  ChatRenderedMessage,
  ChatStreamTimelineItem,
  ChatToolCall,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
} from '@/types/chat'
import type { ArtifactPayload } from '@/types/rpc'

const props = defineProps<{
  message: ChatRenderedMessage
  index: number
  assistantAvatarUrl: string
  renderMarkdown: (text: string) => string
  fmtTok: (value: number) => string
  toolCallGroups: (calls: ChatToolCall[], baseKey: string) => ChatToolCallGroup[]
  isToolGroupOpen: (groupId: string) => boolean
  isToolItemOpen: (renderKey: string) => boolean
  toolGroupStatusText: (group: ChatToolCallGroup) => string
  toolStatusText: (call: ChatToolCallRenderItem) => string
  toolSecondaryText: (call: ChatToolCallRenderItem) => string
}>()

defineEmits<{
  copy: [message: ChatRenderedMessage]
  regenerate: [message: ChatRenderedMessage]
  downloadArtifact: [artifact: ArtifactPayload]
  toggleToolGroup: [groupId: string]
  toggleToolItem: [renderKey: string]
  showToolResult: [content: string, title: string]
}>()

const legacyTimelineItems = computed<ChatStreamTimelineItem[]>(() => {
  const calls = props.message.toolCalls || []
  const baseKey = props.message.messageId || props.message.id || String(props.index)
  return props.toolCallGroups(calls, baseKey).map(group => ({
    type: 'tool-group',
    key: group.groupId,
    group,
  }))
})
</script>

<style scoped>
.msg-ai {
  display: flex;
  gap: 0.625rem;
  width: min(calc(100% - 48px), 980px);
  margin: 0 auto;
  padding: 0.5rem 0;
  align-items: flex-start;
  max-width: calc(100% - 48px);
}

.msg-ai-avatar {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: #fff;
  border: 1px solid rgba(32, 39, 34, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 0.0625rem;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(31, 35, 40, 0.05);
}

.msg-ai-avatar__img {
  width: 1.125rem;
  height: 1.125rem;
  object-fit: contain;
  display: block;
}

.msg-ai-main {
  flex: 1;
  min-width: 0;
  max-width: none;
  padding-top: 0.0625rem;
}

.msg-ai-text {
  font-size: 0.875rem;
  line-height: 1.6;
  color: #27272a;
  word-break: break-word;
  margin-bottom: 0.5rem;
}

.msg-ai-text :deep(p) { margin: 0.375rem 0; }
.msg-ai-text :deep(p:first-child) { margin-top: 0; }
.msg-ai-text :deep(ul), .msg-ai-text :deep(ol) { margin: 0.375rem 0; padding-left: 1.25rem; }
.msg-ai-text :deep(li) { margin: 0.125rem 0; }
.msg-ai-text :deep(code) {
  background: #f4f4f5;
  padding: 0.0625rem 0.25rem;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  color: #52525b;
}
.msg-ai-text :deep(pre) {
  background: #fafafa;
  border: 1px solid #e4e4e7;
  border-radius: 6px;
  padding: 0.625rem;
  overflow-x: auto;
  margin: 0.375rem 0;
}
.msg-ai-text :deep(pre code) {
  background: transparent;
  padding: 0;
}

.msg-ai-footer {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-top: 0.25rem;
}

.msg-ai-actions {
  display: flex;
  gap: 0.125rem;
  opacity: 0;
  transition: opacity 0.15s;
}

.msg-ai:hover .msg-ai-actions {
  opacity: 1;
}

.msg-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.125rem;
  background: none;
  border: none;
  cursor: pointer;
  color: #c4c4c4;
  border-radius: 3px;
  font-size: 0.6875rem;
}

.msg-action:hover {
  color: #a1a1aa;
  background: #f4f4f5;
}

.msg-ai-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  font-size: 0.8125rem;
  line-height: 1.35;
  color: var(--text-muted, #8a8a8a);
}

.savings-indicator {
  color: #047857;
  font-weight: 500;
}
</style>

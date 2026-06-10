<template>
  <div
    class="msg-ai"
    :class="{ 'msg-ai--share-mode': shareMode, 'msg-ai--share-selected': shareSelected }"
    :data-message-id="message.messageId"
    :data-share-message-id="shareMessageId"
    :data-share-selected="shareSelected ? 'true' : undefined"
    @click="onMessageClick"
  >
    <button
      v-if="shareMode"
      type="button"
      class="chat-share-picker"
      :class="{ 'is-selected': shareSelected }"
      :aria-pressed="shareSelected"
      :title="shareSelected ? 'Remove from share image' : 'Add to share image'"
      @click.stop="emit('toggleShare', shareMessageId)"
    >
      <Icon :name="shareSelected ? 'check' : 'plus'" :size="13" />
    </button>
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
        :session-key="sessionKey"
        :auth-token="authToken"
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
  shareMode: boolean
  shareSelected: boolean
  shareMessageId: string
  assistantAvatarUrl: string
  renderMarkdown: (text: string) => string
  fmtTok: (value: number) => string
  toolCallGroups: (calls: ChatToolCall[], baseKey: string) => ChatToolCallGroup[]
  isToolGroupOpen: (groupId: string) => boolean
  isToolItemOpen: (renderKey: string) => boolean
  toolGroupStatusText: (group: ChatToolCallGroup) => string
  toolStatusText: (call: ChatToolCallRenderItem) => string
  toolSecondaryText: (call: ChatToolCallRenderItem) => string
  sessionKey?: string
  authToken?: string
}>()

const emit = defineEmits<{
  copy: [message: ChatRenderedMessage]
  regenerate: [message: ChatRenderedMessage]
  toggleShare: [messageId: string]
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

function onMessageClick(event: MouseEvent) {
  if (!props.shareMode) return
  if ((event.target as HTMLElement | null)?.closest('button,a,input,textarea,select')) return
  emit('toggleShare', props.shareMessageId)
}
</script>

<style scoped>
.msg-ai {
  position: relative;
  display: flex;
  gap: 0.625rem;
  width: min(calc(100% - 48px), 980px);
  margin: 0 auto;
  padding: 0.5rem 0;
  align-items: flex-start;
  max-width: calc(100% - 48px);
}

.msg-ai--share-mode {
  cursor: pointer;
  width: min(calc(100% - 16px), 1012px);
  max-width: calc(100% - 16px);
  box-sizing: border-box;
  padding: 0.5rem 1rem 0.5rem 2.5rem;
  border-radius: 0.875rem;
  transition: background 0.16s ease, box-shadow 0.16s ease;
}

.msg-ai--share-mode:hover {
  background: rgba(184, 68, 4, 0.045);
}

.msg-ai--share-selected {
  background: rgba(184, 68, 4, 0.07);
  box-shadow: inset 0 0 0 1px rgba(184, 68, 4, 0.16);
}

.chat-share-picker {
  position: absolute;
  left: 0.45rem;
  top: 0.65rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.45rem;
  height: 1.45rem;
  border: 1px solid rgba(32, 39, 34, 0.14);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.94);
  color: #6b716a;
  box-shadow: 0 6px 18px rgba(31, 35, 40, 0.08);
  cursor: pointer;
  transition: transform 0.14s ease, border-color 0.14s ease, color 0.14s ease;
}

.chat-share-picker:hover {
  transform: translateY(-1px);
  border-color: rgba(184, 68, 4, 0.35);
  color: #b84404;
}

.chat-share-picker.is-selected {
  border-color: rgba(184, 68, 4, 0.45);
  background: #b84404;
  color: #fff;
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
  color: rgba(82, 88, 81, 0.56);
}

.msg-ai-meta > span:not(.savings-indicator) {
  opacity: 0.72;
  transition: opacity 0.16s ease, color 0.16s ease;
}

.msg-ai:hover .msg-ai-meta > span:not(.savings-indicator) {
  opacity: 0.88;
}

.savings-indicator {
  position: relative;
  display: inline-flex;
  align-items: center;
  min-height: 1.25rem;
  padding: 0 0.45rem;
  overflow: hidden;
  border: 1px solid rgba(184, 68, 4, 0.18);
  border-radius: 999px;
  background:
    linear-gradient(135deg, rgba(255, 247, 237, 0.96), rgba(255, 255, 255, 0.78) 48%, rgba(240, 253, 244, 0.9)),
    radial-gradient(circle at 18% 0%, rgba(251, 191, 36, 0.34), transparent 42%);
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.85),
    0 5px 14px rgba(184, 68, 4, 0.08);
  color: #9a4b00;
  font-weight: 650;
  isolation: isolate;
}

.savings-indicator::after {
  content: '';
  position: absolute;
  inset: -40% auto -40% -60%;
  width: 42%;
  background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.82), transparent);
  transform: skewX(-18deg);
  animation: savingsSweep 3.4s ease-in-out infinite;
  opacity: 0.72;
  pointer-events: none;
}

@keyframes savingsSweep {
  0%, 42% {
    left: -60%;
  }
  72%, 100% {
    left: 118%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .savings-indicator::after {
    animation: none;
    display: none;
  }
}

@media (max-width: 640px) {
  .msg-ai--share-mode {
    width: min(calc(100% - 12px), 1012px);
    max-width: calc(100% - 12px);
    padding: 0.5rem 0.75rem 0.5rem 2.25rem;
  }

  .chat-share-picker {
    left: 0.35rem;
  }
}
</style>

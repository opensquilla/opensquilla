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
          <button
            type="button"
            class="msg-action"
            :class="{ 'msg-action--ok': copyState === 'ok', 'msg-action--err': copyState === 'err' }"
            :title="copyTitle"
            @click="onCopyClick"
          >
            <Icon :name="copyIconName" :size="12" />
          </button>
          <span class="msg-copy-live" aria-live="polite">{{ copyLiveText }}</span>
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
import { useCopyFeedback } from '@/composables/chat/useCopyFeedback'
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
  copyMessage: (message: ChatRenderedMessage) => Promise<boolean>
  sessionKey?: string
  authToken?: string
}>()

const emit = defineEmits<{
  regenerate: [message: ChatRenderedMessage]
  toggleShare: [messageId: string]
  downloadArtifact: [artifact: ArtifactPayload]
  toggleToolGroup: [groupId: string]
  toggleToolItem: [renderKey: string]
  showToolResult: [content: string, title: string]
}>()

const { copyState, copyIconName, copyTitle, copyLiveText, onCopyClick } = useCopyFeedback(
  () => props.copyMessage(props.message),
)

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
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.msg-ai--share-selected {
  background: color-mix(in srgb, var(--accent) 7%, transparent);
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 16%, transparent);
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
  border: 1px solid var(--border-strong);
  border-radius: 999px;
  background: var(--bg-surface);
  color: var(--text-muted);
  box-shadow: var(--shadow-md);
  cursor: pointer;
  transition: transform 0.14s ease, border-color 0.14s ease, color 0.14s ease;
}

.chat-share-picker:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--accent) 35%, transparent);
  color: var(--accent);
}

.chat-share-picker.is-selected {
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: var(--accent);
  color: var(--accent-foreground);
}

.msg-ai-avatar {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 0.0625rem;
  overflow: hidden;
  box-shadow: var(--shadow-xs);
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
  color: var(--text);
  word-break: break-word;
  margin-bottom: 0.5rem;
}

.msg-ai-text :deep(p) { margin: 0.375rem 0; }
.msg-ai-text :deep(p:first-child) { margin-top: 0; }
.msg-ai-text :deep(ul), .msg-ai-text :deep(ol) { margin: 0.375rem 0; padding-left: 1.25rem; }
.msg-ai-text :deep(li) { margin: 0.125rem 0; }
.msg-ai-text :deep(code) {
  background: var(--bg-hover);
  padding: 0.0625rem 0.25rem;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  color: var(--text-muted);
}
.msg-ai-text :deep(pre) {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
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
  color: var(--text-dim);
  border-radius: 3px;
  font-size: 0.6875rem;
}

.msg-action:hover {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.msg-action.msg-action--ok,
.msg-action.msg-action--ok:hover {
  color: var(--ok);
}

.msg-action.msg-action--err,
.msg-action.msg-action--err:hover {
  color: var(--danger);
}

.msg-copy-live {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip-path: inset(50%);
  white-space: nowrap;
}

.msg-ai-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  font-size: 0.8125rem;
  line-height: 1.35;
  color: color-mix(in srgb, var(--text-muted) 56%, transparent);
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
  border: 1px solid color-mix(in srgb, var(--accent) 18%, transparent);
  border-radius: 999px;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--accent) 8%, var(--bg-surface)), var(--bg-surface) 48%, color-mix(in srgb, var(--ok) 8%, var(--bg-surface))),
    radial-gradient(circle at 18% 0%, color-mix(in srgb, var(--warn) 34%, transparent), transparent 42%);
  box-shadow:
    inset 0 1px 0 color-mix(in srgb, var(--bg-surface) 85%, transparent),
    0 5px 14px color-mix(in srgb, var(--accent) 8%, transparent);
  color: var(--accent);
  font-weight: 650;
  isolation: isolate;
}

.savings-indicator::after {
  content: '';
  position: absolute;
  inset: -40% auto -40% -60%;
  width: 42%;
  background: linear-gradient(90deg, transparent, color-mix(in srgb, var(--bg-surface) 82%, transparent), transparent);
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

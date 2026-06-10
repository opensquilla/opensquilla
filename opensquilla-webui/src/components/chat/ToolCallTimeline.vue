<template>
  <template v-for="item in items" :key="item.key">
    <div v-if="item.type === 'text'" class="msg-ai-text" v-html="item.html" />
    <div v-else class="step-card">
      <div
        class="step-group"
        :class="{
          'step-group--running': item.group.isRunning,
          'step-group--error': item.group.isError,
          'is-open': isToolGroupOpen(item.group.groupId),
        }"
      >
        <button type="button" class="step-group-header" @click="$emit('toggleGroup', item.group.groupId)">
          <span class="step-icon">
            <Icon :name="item.group.iconName" :size="15" />
          </span>
          <span class="step-body">
            <span class="step-title-row">
              <span class="step-title">{{ item.group.label }}</span>
              <span v-if="item.group.calls.length > 1" class="step-count">{{ item.group.calls.length }} calls</span>
              <span v-if="item.group.secondary" class="step-secondary">{{ item.group.secondary }}</span>
            </span>
          </span>
          <span class="step-trailing">
            <span class="step-status">{{ toolGroupStatusText(item.group) }}</span>
            <Icon class="step-chevron" name="chevronRight" :size="14" />
          </span>
        </button>
        <div v-if="isToolGroupOpen(item.group.groupId)" class="step-group-members">
          <div
            v-for="call in item.group.calls"
            :key="call.renderKey"
            class="step-subitem"
            :class="{
              'step-item--running': call.isRunning,
              'step-item--success': call.status === 'success',
              'step-item--error': call.status === 'error',
              'is-open': isToolItemOpen(call.renderKey),
            }"
            @click="$emit('toggleItem', call.renderKey)"
          >
            <div class="step-body">
              <div class="step-title-row">
                <span class="step-subtitle">{{ call.displayName }}</span>
                <span v-if="toolSecondaryText(call)" class="step-secondary">{{ toolSecondaryText(call) }}</span>
              </div>
              <div v-if="call.inputPreview && isToolItemOpen(call.renderKey)" class="step-detail">{{ call.inputPreview }}</div>
              <div v-if="call.result && isToolItemOpen(call.renderKey)" class="step-result" :class="{ 'step-result--error': call.isError }">
                <pre class="step-result-pre">{{ call.resultPreview }}</pre>
                <button
                  v-if="call.result.length > 200"
                  class="step-view-btn"
                  @click.stop="$emit('showResult', call.result, call.displayName)"
                >
                  View full
                </button>
              </div>
            </div>
            <div class="step-trailing">
              <span class="step-status">{{ toolStatusText(call) }}</span>
              <Icon class="step-chevron" name="chevronRight" :size="14" />
            </div>
          </div>
        </div>
      </div>
    </div>
  </template>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
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
}>()

defineEmits<{
  toggleGroup: [groupId: string]
  toggleItem: [renderKey: string]
  showResult: [content: string, title: string]
}>()
</script>

<style scoped>
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

.step-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.25rem;
  overflow: hidden;
  margin: 0.625rem 0;
  box-shadow: var(--shadow-xs);
}

.step-group {
  border-radius: 7px;
}

.step-group + .step-group {
  margin-top: 0.125rem;
}

.step-group-header,
.step-subitem {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.625rem 0.875rem;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.12s ease, color 0.12s ease;
  min-height: 2.5rem;
  color: inherit;
}

.step-group-header {
  border: 0;
  background: transparent;
  font: inherit;
  text-align: left;
}

.step-subitem {
  position: relative;
  padding: 0.5625rem 0.75rem 0.5625rem 2.25rem;
}

.step-group-header:hover,
.step-subitem:hover {
  background: var(--bg-hover);
}

.step-group.is-open > .step-group-header,
.step-subitem.is-open {
  background: var(--bg-elevated);
}

.step-group--running > .step-group-header,
.step-item--running {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.step-group--running .step-icon,
.step-item--running .step-icon {
  color: var(--accent);
}

.step-group--error .step-title,
.step-group--error .step-status,
.step-item--error .step-title,
.step-item--error .step-subtitle,
.step-item--error .step-status {
  color: var(--danger);
}

.step-group-members {
  margin: 0.125rem 0 0.25rem;
  padding-left: 1.25rem;
}

.step-group-members::before {
  content: '';
  display: block;
  width: calc(100% - 1.25rem);
  height: 1px;
  margin: 0 0 0.125rem 1.25rem;
  background: var(--hairline);
}

.step-icon {
  width: 1.125rem;
  height: 1.125rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: var(--text-muted);
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-title-row {
  display: flex;
  align-items: baseline;
  gap: 0.625rem;
  min-width: 0;
}

.step-title {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text);
  line-height: 1.4;
  flex-shrink: 0;
}

.step-count {
  flex-shrink: 0;
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0.0625rem 0.375rem;
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-hover);
}

.step-subtitle {
  font-size: 0.765625rem;
  font-weight: 500;
  color: var(--text-muted);
  line-height: 1.4;
  flex-shrink: 0;
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-secondary {
  min-width: 0;
  color: var(--text-dim);
  font-size: 0.8125rem;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-detail {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: var(--text-muted);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow-y: auto;
}

.step-result {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.step-result--error {
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-surface));
  border-color: color-mix(in srgb, var(--danger) 30%, var(--border));
}

.step-result-pre {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow-y: auto;
  margin: 0;
}

.step-view-btn {
  margin-top: 0.25rem;
  padding: 0.125rem 0.375rem;
  font-size: 0.6875rem;
  color: var(--accent);
  background: transparent;
  border: none;
  cursor: pointer;
}

.step-view-btn:hover {
  text-decoration: underline;
}

.step-trailing {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-shrink: 0;
  color: var(--text-dim);
}

.step-status {
  font-size: 0.8125rem;
  color: var(--text-dim);
  white-space: nowrap;
}

.step-chevron {
  transition: transform 0.12s ease;
}

.step-group.is-open > .step-group-header .step-chevron,
.step-subitem.is-open .step-chevron {
  transform: rotate(90deg);
}
</style>

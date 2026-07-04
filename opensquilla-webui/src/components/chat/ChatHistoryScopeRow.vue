<template>
  <div v-if="visible" class="chat-history-scope" role="status">
    <button
      v-if="state.hasMore"
      type="button"
      class="chat-history-scope__button"
      :disabled="state.loading"
      @click="$emit('loadEarlier')"
    >
      {{ state.loading ? t('chat.loadingEllipsis') : t('chat.loadEarlier') }}
    </button>
    <span v-if="scopeText" class="chat-history-scope__text">{{ scopeText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { ChatHistoryState } from '@/composables/chat/useChatHistory'

const { t } = useI18n()

const props = defineProps<{
  state: ChatHistoryState
}>()

defineEmits<{
  loadEarlier: []
}>()

const scopeText = computed(() => {
  if (props.state.historyScope === 'compacted') return t('chat.scopeCompacted')
  if (props.state.historyScope === 'latest_window') return t('chat.scopeLatestWindow')
  return ''
})

const visible = computed(() => props.state.hasMore || Boolean(scopeText.value))
</script>

<style scoped>
.chat-history-scope {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  flex-wrap: wrap;
  width: var(--chat-col, min(calc(100% - 48px), 980px));
  margin: 0.5rem auto 0.75rem;
  color: var(--text-muted);
  font-size: 0.75rem;
}

.chat-history-scope__button {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0.25rem 0.75rem;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-full);
  background: var(--bg-surface);
  color: var(--text);
  cursor: pointer;
}

.chat-history-scope__button:hover {
  border-color: var(--border-focus);
  background: var(--bg-elevated);
}

.chat-history-scope__button:disabled {
  cursor: wait;
  opacity: 0.62;
}

.chat-history-scope__text {
  color: var(--text-dim);
}
</style>

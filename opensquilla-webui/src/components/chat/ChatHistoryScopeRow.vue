<template>
  <div v-if="visible" class="chat-history-scope" role="status">
    <button
      v-if="state.hasMore"
      type="button"
      class="chat-history-scope__button"
      :disabled="state.loading"
      @click="$emit('loadEarlier')"
    >
      {{ state.loading ? 'Loading...' : 'Load earlier messages' }}
    </button>
    <span v-if="scopeText" class="chat-history-scope__text">{{ scopeText }}</span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ChatHistoryState } from '@/composables/chat/useChatHistory'

const props = defineProps<{
  state: ChatHistoryState
}>()

defineEmits<{
  loadEarlier: []
}>()

const scopeText = computed(() => {
  if (props.state.historyScope === 'compacted') return 'Older content is represented by session summaries.'
  if (props.state.historyScope === 'latest_window') return 'Showing the latest message window.'
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
  width: min(calc(100% - 48px), 980px);
  margin: 0.5rem auto 0.75rem;
  color: #6b716a;
  font-size: 0.75rem;
}

.chat-history-scope__button {
  display: inline-flex;
  align-items: center;
  min-height: 30px;
  padding: 0.25rem 0.75rem;
  border: 1px solid #d9d9de;
  border-radius: 999px;
  background: #fff;
  color: #303034;
  cursor: pointer;
}

.chat-history-scope__button:hover {
  border-color: #b9bbc2;
  background: #f8f8f9;
}

.chat-history-scope__button:disabled {
  cursor: wait;
  opacity: 0.62;
}

.chat-history-scope__text {
  color: #7c827b;
}
</style>

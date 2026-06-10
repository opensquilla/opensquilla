<template>
  <div v-if="items.length > 0" class="chat-pending">
    <div class="chat-pending-header">
      <span
        class="chat-pending-label"
        title="Alt+&#8593; pulls the most recent back into the input &#183; ESC recovers all to input &#183; sends FIFO when the current response finishes"
      >
        Pending {{ items.length }}/{{ maxPending }}
      </span>
      <button
        v-if="items.length >= 2"
        class="chat-pending-clear"
        aria-label="Clear all pending messages"
        @click="$emit('clear')"
      >
        Clear all
      </button>
    </div>
    <div class="chat-pending-chips">
      <span
        v-for="(item, index) in items"
        :key="index"
        class="chat-pending-chip"
        :title="item.text"
      >
        <span class="chat-pending-text">{{ item.text.slice(0, 30) }}{{ item.text.length > 30 ? '...' : '' }}</span>
        <span v-if="item.attachments?.length" class="chat-pending-attch">&#128206;{{ item.attachments.length }}</span>
        <button
          class="chat-pending-chip-remove"
          :aria-label="`Remove pending message ${index + 1}`"
          title="Remove"
          @click="$emit('remove', index)"
        >
          &times;
        </button>
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Attachment } from '@/types/chat'

interface PendingQueueItem {
  text: string
  attachments?: Attachment[]
}

defineProps<{
  items: PendingQueueItem[]
  maxPending: number
}>()

defineEmits<{
  clear: []
  remove: [index: number]
}>()
</script>

<style scoped>
.chat-pending {
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--border);
  background: var(--bg-elevated);
  flex-shrink: 0;
}

.chat-pending-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 0.375rem;
}

.chat-pending-label {
  font-size: 0.8125rem;
  font-weight: 600;
  color: var(--text-muted);
}

.chat-pending-clear {
  font-size: 0.8125rem;
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
}

.chat-pending-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
}

.chat-pending-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  cursor: default;
}

.chat-pending-chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  width: 16px;
  height: 16px;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 0.875rem;
  line-height: 1;
}

.chat-pending-chip-remove:hover {
  color: var(--danger);
}

.chat-pending-attch {
  font-size: 0.8125rem;
}
</style>

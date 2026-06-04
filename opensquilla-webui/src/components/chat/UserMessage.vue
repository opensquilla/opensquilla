<template>
  <div class="msg-user" :data-message-id="message.messageId">
    <div class="msg-user-bubble" :class="{ 'msg-user-bubble--has-attachments': message.hasAttachments }">
      <template v-if="message.text">
        {{ stripTimePrefix(message.text) }}
      </template>
      <div v-if="message.attachments?.length" class="msg-attachments">
        <template v-for="attachment in message.attachments" :key="attachment.name">
          <img
            v-if="attachment.dataUrl || attachment.data"
            class="msg-thumb"
            :src="attachment.dataUrl || `data:${attachment.mime || 'image/png'};base64,${attachment.data}`"
            :alt="attachment.name"
          />
          <span v-else class="msg-file-chip" :title="attachment.name">
            <span class="msg-file-chip__icon" aria-hidden="true">file</span>
            <span class="msg-file-chip__name">{{ attachment.name }}</span>
            <span class="msg-file-chip__meta">{{ attachment.mime || 'attachment' }}</span>
          </span>
        </template>
      </div>
    </div>
    <div class="msg-user-actions">
      <button type="button" class="msg-action" title="Copy" @click="$emit('copy', message)">
        <Icon name="copy" :size="12" />
      </button>
      <button type="button" class="msg-action" title="Edit" @click="$emit('edit', message)">
        <Icon name="edit" :size="12" />
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import Icon from '@/components/Icon.vue'
import type { ChatRenderedMessage } from '@/types/chat'

defineProps<{
  message: ChatRenderedMessage
  stripTimePrefix: (text: string) => string
}>()

defineEmits<{
  copy: [message: ChatRenderedMessage]
  edit: [message: ChatRenderedMessage]
}>()
</script>

<style scoped>
.msg-user {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  width: min(calc(100% - 48px), 980px);
  margin: 0 auto;
  padding: 0.5rem 0;
  max-width: calc(100% - 48px);
}

.msg-user-bubble {
  background: #f4f4f5;
  color: #18181b;
  padding: 0.5rem 0.875rem;
  border-radius: 1rem;
  font-size: 0.875rem;
  line-height: 1.5;
  max-width: 82%;
  word-break: break-word;
}

.msg-user-actions {
  display: flex;
  gap: 0.125rem;
  margin-top: 0.125rem;
  opacity: 0;
  transition: opacity 0.15s;
  justify-content: flex-end;
}

.msg-user:hover .msg-user-actions {
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

.msg-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-top: 0.5rem;
}

.msg-thumb {
  max-width: 200px;
  max-height: 200px;
  border-radius: 0.375rem;
  object-fit: cover;
}

.msg-file-chip__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.125rem 0.375rem;
  background: var(--bg-secondary, #f5f5f5);
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
}

.msg-file-chip__name {
  font-weight: 500;
}

.msg-file-chip__meta {
  font-size: 0.8125rem;
  color: var(--text-muted, #999);
}

@media (max-width: 640px) {
  .msg-user-bubble {
    max-width: 90%;
  }
}
</style>

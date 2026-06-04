<template>
  <div class="msg-system-wrap">
    <div class="msg-system" :class="message.displayRole">
      <span class="msg-system-label">{{ message.roleLabel }}</span>
      <template v-if="message.displayRole === 'subagent'">
        <details class="chat-subagent-disclosure">
          <summary class="chat-subagent-disclosure-summary">{{ subagentSummary(message.text) }}</summary>
          <pre class="chat-subagent-disclosure-body">{{ subagentBody(message.text) }}</pre>
        </details>
      </template>
      <template v-else-if="message.text">
        {{ message.text }}
      </template>
    </div>
  </div>
</template>

<script setup lang="ts">
import type { ChatRenderedMessage } from '@/types/chat'

defineProps<{
  message: ChatRenderedMessage
  subagentSummary: (text: string) => string
  subagentBody: (text: string) => string
}>()
</script>

<style scoped>
.msg-system-wrap {
  display: flex;
  justify-content: center;
  padding: 0.375rem 2rem;
}

.msg-system {
  font-size: 0.8125rem;
  color: #a1a1aa;
  padding: 0.25rem 0.625rem;
  border-radius: 6px;
  max-width: 70%;
  text-align: center;
}

.msg-system.error {
  background: #fef2f2;
  color: #dc2626;
}

.msg-system-label {
  font-weight: 600;
  margin-right: 0.375rem;
}

.chat-subagent-disclosure {
  margin: 0;
}

.chat-subagent-disclosure-summary {
  font-weight: 500;
  cursor: pointer;
  padding: 0.25rem 0;
}

.chat-subagent-disclosure-body {
  padding: 0.5rem;
  background: var(--bg-tertiary, #e5e5e5);
  border-radius: 0.25rem;
  font-size: 0.8125rem;
  overflow-x: auto;
  max-height: 200px;
  overflow-y: auto;
}
</style>

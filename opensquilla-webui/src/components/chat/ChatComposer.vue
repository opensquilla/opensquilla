<template>
  <div ref="composerEl" class="chat-composer" :class="{ 'chat-composer--new-landing': isNewLanding }">
    <div class="chat-composer-inner">
      <div v-if="attachments.length > 0" class="chat-attachments">
        <div
          v-for="(att, i) in attachments"
          :key="att.local_id"
          class="attachment-chip"
          :class="{ 'attachment-chip--busy': att.kind === 'inline_pending' || att.kind === 'uploading' }"
          :data-mime="att.mime || ''"
        >
          <span class="attachment-chip__icon" aria-hidden="true">
            <span v-if="att.kind === 'inline_pending' || att.kind === 'uploading'" class="spinner attachment-chip__spinner" />
            <span v-else>file</span>
          </span>
          <span class="attachment-chip__name">{{ att.name }}</span>
          <span class="attachment-chip__meta">{{ attachmentMeta(att) }}</span>
          <button class="attachment-remove" title="Remove" @click="emit('removeAttachment', i)">&times;</button>
        </div>
      </div>
      <div class="chat-input-panel">
        <div class="chat-input-wrap">
          <textarea
            ref="textareaEl"
            v-model="inputText"
            class="chat-textarea"
            rows="1"
            :placeholder="placeholder"
            maxlength="100000"
            aria-label="Message to send"
            @input="emit('input')"
            @keydown="emit('keydown', $event)"
            @compositionstart="emit('compositionChange', true)"
            @compositionend="emit('compositionChange', false)"
          />
        </div>
        <div class="chat-input-footer">
          <div class="chat-input-actions chat-input-actions--left">
            <button class="btn btn--icon btn--ghost chat-plus-btn" title="Attach files: PNG, JPEG, GIF, WEBP, PDF, TXT, MD, HTML, CSV, JSON" aria-label="Attach files" @click="fileInputEl?.click()">
              <Icon name="plus" :size="18" />
            </button>
          </div>
          <div class="chat-input-actions chat-input-actions--right">
            <button class="btn btn--icon btn--primary chat-send-btn" :class="{ 'is-ready': hasSendContent }" :title="sendButtonTitle" aria-label="Send" @click="emit('send')">
              <Icon name="arrowUp" :size="17" />
            </button>
            <button v-if="isStreaming" class="btn btn--icon btn--danger chat-send-btn" title="Stop current response (Esc)" aria-label="Stop current response" @click="emit('stop')">
              <Icon name="stop" :size="16" />
            </button>
          </div>
        </div>
      </div>
    </div>
    <input
      ref="fileInputEl"
      type="file"
      accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,text/html,text/csv,application/json,.md,.markdown"
      multiple
      class="hidden"
      @change="emit('fileChange', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type { Attachment } from '@/types/chat'

interface ChatComposerExpose {
  composerElement: () => HTMLElement | null
  focusTextarea: () => void
  isTextareaFocused: () => boolean
  resizeTextarea: () => void
}

defineProps<{
  attachments: Attachment[]
  hasSendContent: boolean
  isStreaming: boolean
  isNewLanding: boolean
  placeholder: string
  sendButtonTitle: string
}>()

const emit = defineEmits<{
  compositionChange: [value: boolean]
  fileChange: [event: Event]
  input: []
  keydown: [event: KeyboardEvent]
  removeAttachment: [index: number]
  send: []
  stop: []
}>()

const inputText = defineModel<string>({ required: true })
const composerEl = ref<HTMLElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const fileInputEl = ref<HTMLInputElement | null>(null)

function attachmentMeta(att: Attachment): string {
  const size = typeof att.size === 'number'
    ? `${Math.max(1, Math.round(att.size / 1024))} KB`
    : ''
  return [att.mime || 'attachment', size].filter(Boolean).join(' · ')
}

function composerElement(): HTMLElement | null {
  return composerEl.value
}

function focusTextarea() {
  nextTick(() => textareaEl.value?.focus())
}

function isTextareaFocused(): boolean {
  return document.activeElement === textareaEl.value
}

function resizeTextarea() {
  nextTick(() => {
    const ta = textareaEl.value
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
  })
}

defineExpose<ChatComposerExpose>({
  composerElement,
  focusTextarea,
  isTextareaFocused,
  resizeTextarea,
})
</script>

<style scoped>
.hidden {
  display: none !important;
}

.chat-composer {
  padding: 0.75rem 1.5rem 1.875rem;
  border-top: 0;
  background: #fff;
  flex-shrink: 0;
}

.chat-composer--new-landing {
  width: min(calc(100% - 48px), 820px);
  margin: 0 auto;
  padding: 0;
  background: transparent;
}

.chat-composer-inner {
  width: min(100%, 820px);
  margin: 0 auto;
}

.chat-composer--new-landing .chat-composer-inner {
  width: 100%;
}

.chat-attachments {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
  margin-bottom: 0.5rem;
}

.attachment-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.25rem 0.5rem;
  background: #f9fafb;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
}

.attachment-chip--busy {
  opacity: 0.7;
}

.attachment-chip__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
}

.attachment-chip__spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--text-muted, #666);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.attachment-chip__name {
  font-weight: 500;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-chip__meta {
  color: var(--text-muted, #999);
  font-size: 0.6875rem;
}

.attachment-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  width: 16px;
  height: 16px;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted, #666);
  font-size: 0.875rem;
}

.attachment-remove:hover {
  color: #dc2626;
}

.chat-input-panel {
  display: flex;
  flex-direction: column;
  min-height: 128px;
  border: 1px solid #d9d9de;
  border-radius: 22px;
  background: #fff;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.chat-composer--new-landing .chat-input-panel {
  min-height: 148px;
  border-color: rgba(32, 39, 34, 0.10);
  border-radius: 24px;
  box-shadow:
    0 1px 2px rgba(31, 35, 40, 0.025),
    0 18px 42px rgba(31, 35, 40, 0.065);
}

.chat-composer--new-landing .chat-input-panel:focus-within {
  border-color: rgba(32, 39, 34, 0.18);
  box-shadow:
    0 1px 2px rgba(31, 35, 40, 0.025),
    0 22px 48px rgba(31, 35, 40, 0.08);
}

.chat-input-footer,
.chat-input-actions {
  display: flex;
  align-items: center;
}

.chat-input-footer {
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.25rem 0.625rem 0.625rem;
}

.chat-input-actions {
  gap: 0.25rem;
  min-width: 0;
}

.chat-input-actions--right {
  flex-shrink: 0;
}

.chat-input-wrap {
  flex: 1;
  min-width: 0;
  display: flex;
}

.chat-textarea {
  width: 100%;
  min-height: 68px;
  max-height: 160px;
  padding: 1rem 1rem 0.375rem;
  border: 0;
  border-radius: 0;
  background: transparent;
  color: #1a1a1a;
  font-size: 0.9375rem;
  line-height: 1.5;
  resize: none;
  outline: none;
  font-family: inherit;
}

.chat-composer--new-landing .chat-textarea {
  min-height: 86px;
  padding: 1.125rem 1.25rem 0.5rem;
}

.chat-textarea:focus {
  border-color: transparent;
  box-shadow: none;
}

.chat-input-panel:focus-within {
  border-color: #c9c9d1;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.06);
}

.btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.5rem 0.75rem;
  border-radius: 0.375rem;
  font-size: 0.875rem;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  transition: background 0.15s, border-color 0.15s;
}

.btn--icon {
  width: 34px;
  height: 34px;
  min-width: 34px;
  min-height: 34px;
  border-radius: 999px;
  padding: 0;
}

.chat-plus-btn {
  border: 1px solid #e1e1e5;
  color: #303034;
}

.btn--ghost {
  background: none;
  border-color: transparent;
  color: var(--text-muted, #666);
}

.btn--ghost:hover {
  background: var(--bg-secondary, #f5f5f5);
  color: var(--text-primary, #1a1a1a);
}

.chat-send-btn.btn--primary {
  background: #d6d6da;
  color: #fff;
  border-color: #d6d6da;
}

.chat-send-btn.btn--primary:hover {
  background: #c9c9ce;
  border-color: #c9c9ce;
}

.chat-send-btn.btn--primary.is-ready {
  background: #202722 !important;
  border-color: #202722 !important;
  color: #fff;
}

.chat-send-btn.btn--primary.is-ready:hover {
  background: #111612 !important;
  border-color: #111612 !important;
}

.chat-send-btn {
  color: #fff;
}

.btn--danger {
  background: #dc2626;
  color: #fff;
  border-color: #dc2626;
}

.btn--danger:hover {
  opacity: 0.9;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>

<template>
  <div ref="composerEl" class="chat-composer" :class="{ 'chat-composer--new-landing': isNewLanding }">
    <div class="chat-composer-inner">
      <div v-if="attachments.length > 0" class="chat-attachments">
        <div
          v-for="(att, i) in attachments"
          :key="att.local_id"
          class="attachment-chip"
          :class="{ 'attachment-chip--busy': isAttachmentBusy(att), 'attachment-chip--failed': att.kind === 'failed' }"
          :data-mime="att.mime || ''"
          :title="attachmentTitle(att)"
        >
          <span class="attachment-chip__icon" aria-hidden="true">
            <span v-if="isAttachmentBusy(att)" class="spinner attachment-chip__spinner" />
            <Icon v-else-if="att.kind === 'failed'" name="info" :size="15" />
            <img v-else-if="isImageDisplayAttachment(att) && att.dataUrl" class="attachment-chip__thumb" :src="att.dataUrl" alt="" />
            <Icon v-else :name="attachmentIcon(att)" :size="15" />
          </span>
          <span class="attachment-chip__name">{{ att.name }}</span>
          <span class="attachment-chip__meta">{{ attachmentMeta(att) }}</span>
          <button v-if="att.kind === 'failed' && att.file" class="attachment-action" title="Retry upload" aria-label="Retry upload" @click="emit('retryAttachment', i)">
            <Icon name="refresh" :size="12" />
          </button>
          <button class="attachment-action attachment-remove" :title="t('chat.remove')" :aria-label="t('chat.remove')" @click="emit('removeAttachment', i)">
            <Icon name="x" :size="12" />
          </button>
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
            :aria-label="t('chat.messageToSend')"
            @beforeinput="emit('beforeinput', $event)"
            @input="emit('input', $event)"
            @keydown="emit('keydown', $event)"
            @compositionstart="emit('compositionChange', true)"
            @compositionend="emit('compositionChange', false)"
          />
        </div>
        <div class="chat-input-footer">
          <div class="chat-input-actions chat-input-actions--left">
            <button class="btn btn--icon btn--ghost chat-plus-btn" :title="t('chat.attachFilesTitle')" :aria-label="t('chat.attachFiles')" @click="fileInputEl?.click()">
              <Icon name="plus" :size="18" />
            </button>
            <div class="chat-settings-anchor">
              <button
                class="btn btn--icon btn--ghost"
                :title="t('chat.composerSettings')"
                :aria-label="t('chat.composerSettings')"
                :aria-expanded="settingsOpen ? 'true' : 'false'"
                @click="settingsOpen = !settingsOpen"
              >
                <Icon name="settings" :size="17" />
              </button>
              <ChatComposerSettings
                v-if="settingsOpen"
                :elevated-mode="elevatedMode"
                :elevated-unavailable="elevatedUnavailable"
                :router-enabled="routerEnabled"
                :router-settings-busy="routerSettingsBusy"
                :visual-effects-enabled="routerVisualEffectsEnabled"
                :coding-mode-enabled="codingModeEnabled"
                :coding-mode-settings-busy="codingModeSettingsBusy"
                @close="settingsOpen = false"
                @set-elevated-mode="emit('setElevatedMode', $event)"
                @set-router-enabled="emit('setRouterEnabled', $event)"
                @set-visual-effects-enabled="emit('setVisualEffectsEnabled', $event)"
                @set-coding-mode-enabled="emit('setCodingModeEnabled', $event)"
              />
            </div>
            <button
              class="btn btn--icon btn--ghost"
              :class="{ 'is-active': voiceRecording }"
              :title="t('chat.recordVoice')"
              :aria-label="t('chat.recordVoice')"
              :disabled="voiceBusy"
              @click="emit('voiceInput')"
            >
              <Icon name="microphone" :size="17" />
            </button>
            <button class="btn btn--icon btn--ghost" :title="t('chat.exportMarkdown')" :aria-label="t('chat.exportMarkdown')" @click="emit('exportMarkdown')">
              <Icon name="download" :size="17" />
            </button>
          </div>
          <div class="chat-input-actions chat-input-actions--right">
            <Transition name="composer-ctl">
              <div v-if="isStreaming" class="chat-busy-mode" role="group" :aria-label="t('chat.deliveryModeLabel')">
                <button
                  class="chat-busy-mode__btn"
                  :class="{ 'is-active': busySendMode === 'queue' }"
                  :aria-pressed="busySendMode === 'queue' ? 'true' : 'false'"
                  :title="t('chat.queueModeHint')"
                  @click="emit('setBusySendMode', 'queue')"
                >
                  {{ t('chat.queueMode') }}
                </button>
                <button
                  class="chat-busy-mode__btn"
                  :class="{ 'is-active': busySendMode === 'steer' }"
                  :aria-pressed="busySendMode === 'steer' ? 'true' : 'false'"
                  :title="t('chat.steerModeHint')"
                  @click="emit('setBusySendMode', 'steer')"
                >
                  {{ t('chat.steerMode') }}
                </button>
              </div>
            </Transition>
            <button class="btn btn--icon btn--primary chat-send-btn" :class="{ 'is-ready': hasSendContent }" :title="sendButtonTitle" :aria-label="t('chat.send')" @click="emit('send')">
              <Icon name="arrowUp" :size="17" />
            </button>
            <Transition name="composer-ctl">
              <button v-if="isStreaming" class="btn btn--icon btn--danger chat-send-btn" :title="t('chat.stopResponseEsc')" :aria-label="t('chat.stopResponse')" @click="emit('stop')">
                <Icon name="stop" :size="16" />
              </button>
            </Transition>
          </div>
        </div>
      </div>
    </div>
    <input
      ref="fileInputEl"
      type="file"
      accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,text/html,text/csv,application/json,.md,.markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet,application/vnd.openxmlformats-officedocument.presentationml.presentation,.docx,.xlsx,.pptx,message/rfc822,application/vnd.ms-outlook,.eml,.mbox,.msg"
      multiple
      class="hidden"
      @change="emit('fileChange', $event)"
    />
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import Icon from '@/components/Icon.vue'
import type { IconName } from '@/utils/icons'
import ChatComposerSettings from '@/components/chat/ChatComposerSettings.vue'
import type { Attachment } from '@/types/chat'
import { isAttachmentBusy, isImageDisplayAttachment } from '@/utils/chat/attachments'

interface ChatComposerExpose {
  composerElement: () => HTMLElement | null
  focusTextarea: () => void
  isTextareaFocused: () => boolean
  resizeTextarea: () => void
}

defineProps<{
  attachments: Attachment[]
  busySendMode: 'queue' | 'steer'
  hasSendContent: boolean
  isStreaming: boolean
  isNewLanding: boolean
  placeholder: string
  sendButtonTitle: string
  elevatedMode: string
  elevatedUnavailable: boolean
  routerEnabled: boolean
  routerVisualEffectsEnabled: boolean
  routerSettingsBusy: boolean
  codingModeEnabled: boolean
  codingModeSettingsBusy: boolean
  voiceBusy: boolean
  voiceRecording: boolean
}>()

const emit = defineEmits<{
  beforeinput: [event: InputEvent]
  compositionChange: [value: boolean]
  fileChange: [event: Event]
  input: [event: Event]
  keydown: [event: KeyboardEvent]
  removeAttachment: [index: number]
  retryAttachment: [index: number]
  send: []
  setBusySendMode: [mode: 'queue' | 'steer']
  setElevatedMode: [mode: string]
  setRouterEnabled: [enabled: boolean]
  setVisualEffectsEnabled: [enabled: boolean]
  setCodingModeEnabled: [enabled: boolean]
  voiceInput: []
  exportMarkdown: []
  stop: []
}>()

const { t } = useI18n()

const inputText = defineModel<string>({ required: true })
const composerEl = ref<HTMLElement | null>(null)
const textareaEl = ref<HTMLTextAreaElement | null>(null)
const fileInputEl = ref<HTMLInputElement | null>(null)
const settingsOpen = ref(false)

function attachmentIcon(att: Attachment): IconName {
  return isImageDisplayAttachment(att) ? 'image' : 'fileText'
}

function attachmentMeta(att: Attachment): string {
  if (att.kind === 'failed') return att.error ? `FAILED · ${att.error}` : 'FAILED'
  const mime = att.mime || ''
  const subtype = mime.includes('/') ? mime.split('/')[1] : mime
  const label = subtype ? subtype.toUpperCase() : 'FILE'
  const size = typeof att.size === 'number'
    ? `${Math.max(1, Math.round(att.size / 1024))} KB`
    : ''
  return [label, size].filter(Boolean).join(' · ')
}

function attachmentTitle(att: Attachment): string {
  if (att.kind === 'failed') {
    return att.error ? `${att.name}: ${att.error}` : `${att.name}: failed`
  }
  return att.name
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
  background: var(--bg-surface);
  flex-shrink: 0;
}

.chat-composer--new-landing {
  width: min(calc(100% - 48px), 820px);
  margin: 0 auto;
  padding: 0;
  background: transparent;
}

.chat-composer-inner {
  width: min(100%, var(--composer-col, 820px));
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
  max-width: min(100%, 360px);
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
}

.attachment-chip--busy {
  opacity: 0.7;
}

.attachment-chip--failed {
  border-color: color-mix(in srgb, var(--danger) 38%, var(--border));
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-elevated));
}

.attachment-chip--failed .attachment-chip__icon,
.attachment-chip--failed .attachment-chip__meta {
  color: var(--danger);
}

.attachment-chip__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  color: var(--text-muted);
}

.attachment-chip__thumb {
  width: 16px;
  height: 16px;
  border-radius: 3px;
  object-fit: cover;
}

.attachment-chip__spinner {
  width: 12px;
  height: 12px;
  border: 2px solid var(--text-muted);
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.attachment-chip__name {
  font-weight: 500;
  max-width: 150px;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-chip__meta {
  color: var(--text-dim);
  font-size: 0.6875rem;
  min-width: 0;
  max-width: 150px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.attachment-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 16px;
  padding: 0;
  width: 16px;
  height: 16px;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted);
  font-size: 0.875rem;
}

.attachment-action:hover {
  color: var(--text);
}

.chat-input-panel {
  display: flex;
  flex-direction: column;
  min-height: 128px;
  border: 1px solid var(--border-strong);
  border-radius: 22px;
  background: var(--bg-surface);
  box-shadow: var(--shadow-xs);
  position: relative;
}

.chat-composer--new-landing .chat-input-panel {
  min-height: 148px;
  border-color: var(--border);
  border-radius: 24px;
  box-shadow: var(--shadow-lg);
}

.chat-composer--new-landing .chat-input-panel:focus-within {
  border-color: var(--border-focus);
  box-shadow: var(--shadow-xl);
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

.chat-settings-anchor {
  position: relative;
  display: inline-flex;
}

.chat-input-actions--right {
  flex-shrink: 0;
}

.chat-busy-mode {
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 999px;
  padding: 2px;
  gap: 2px;
  margin-right: var(--sp-1);
}

.chat-busy-mode__btn {
  border: 0;
  background: none;
  border-radius: 999px;
  padding: 0.125rem 0.5rem;
  font-size: var(--fs-xs);
  font-weight: 600;
  line-height: 1.4;
  color: var(--text-muted);
  cursor: pointer;
  transition: var(--transition);
}

.chat-busy-mode__btn:hover {
  color: var(--text);
}

.chat-busy-mode__btn.is-active {
  background: color-mix(in srgb, var(--accent) 14%, var(--bg-surface));
  color: var(--accent);
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
  color: var(--text);
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
  border-color: var(--border-focus);
  box-shadow: var(--shadow-sm);
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
  border: 1px solid var(--border);
  color: var(--text);
}

.btn--ghost.is-active {
  background: color-mix(in srgb, var(--ok) 12%, var(--bg-surface));
  color: var(--ok);
}

.chat-send-btn.btn--primary {
  background: var(--bg-hover);
  color: var(--text-dim);
  border-color: var(--bg-hover);
}

.chat-send-btn.btn--primary:hover {
  background: var(--bg-hover);
  border-color: var(--bg-hover);
}

.chat-send-btn.btn--primary.is-ready {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--accent-foreground);
}

.chat-send-btn.btn--primary.is-ready:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Streaming-only controls (Stop, Queue/Steer) ease in/out at turn boundaries
   instead of popping into the action cluster. */
.composer-ctl-enter-active,
.composer-ctl-leave-active {
  transition: opacity var(--dur-fast) var(--ease-out),
              transform var(--dur-fast) var(--ease-out);
}
.composer-ctl-enter-from,
.composer-ctl-leave-to {
  opacity: 0;
  transform: scale(0.9);
}

@media (prefers-reduced-motion: reduce) {
  .composer-ctl-enter-active,
  .composer-ctl-leave-active {
    transition: none;
  }
}
</style>

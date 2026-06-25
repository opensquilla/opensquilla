<template>
  <div
    class="msg-user"
    :class="{ 'msg-user--share-mode': shareMode, 'msg-user--share-selected': shareSelected }"
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
      :aria-label="shareSelected ? 'Remove from share image' : 'Add to share image'"
      @click.stop="emit('toggleShare', shareMessageId)"
    >
      <Icon v-if="shareSelected" name="check" :size="13" />
    </button>
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
    <div v-if="!shareMode" class="msg-user-actions">
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
      <button type="button" class="msg-action" title="Edit" @click="$emit('edit', message)">
        <Icon name="edit" :size="12" />
      </button>
      <time v-if="timeIso" class="msg-time" :datetime="timeIso" :title="timeFull">
        <span class="msg-time__abs">{{ timeAbs }}</span>
        <span class="msg-time__dot" aria-hidden="true">·</span>
        <span class="msg-time__rel">{{ timeRel }}</span>
      </time>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import Icon from '@/components/Icon.vue'
import { useCopyFeedback } from '@/composables/chat/useCopyFeedback'
import { useRelativeNow } from '@/composables/useRelativeNow'
import type { ChatRenderedMessage } from '@/types/chat'
import { absoluteTime, fullTime, isoTime, relativeTime } from '@/utils/messageTime'

const props = defineProps<{
  message: ChatRenderedMessage
  shareMode: boolean
  shareSelected: boolean
  shareMessageId: string
  stripTimePrefix: (text: string) => string
  copyMessage: (message: ChatRenderedMessage) => Promise<boolean>
}>()

const emit = defineEmits<{
  edit: [message: ChatRenderedMessage]
  toggleShare: [messageId: string]
}>()

const { copyState, copyIconName, copyTitle, copyLiveText, onCopyClick } = useCopyFeedback(
  () => props.copyMessage(props.message),
)

// Absolute label is static; only the relative label subscribes to the shared
// clock, so a tick re-evaluates one cheap computed per visible bubble.
const now = useRelativeNow()
const timeIso = computed(() => isoTime(props.message.ts))
const timeAbs = computed(() => absoluteTime(props.message.ts))
const timeRel = computed(() => relativeTime(props.message.ts, now.value))
const timeFull = computed(() => fullTime(props.message.ts))

function onMessageClick(event: MouseEvent) {
  if (!props.shareMode) return
  if ((event.target as HTMLElement | null)?.closest('button,a,input,textarea,select')) return
  emit('toggleShare', props.shareMessageId)
}
</script>

<style scoped>
.msg-user {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  /* Shared conversation column, defined on .chat — keeps user bubbles in the
     same column as assistant content at every viewport width. */
  width: var(--chat-col, min(calc(100% - 48px), 980px));
  margin: 0 auto;
  padding: 0.5rem 0;
  max-width: calc(100% - 48px);
}

.msg-user--share-mode {
  cursor: pointer;
  width: min(calc(100% - 16px), 1012px);
  max-width: calc(100% - 16px);
  box-sizing: border-box;
  padding: 0.5rem 2.5rem 0.5rem 1rem;
  border-radius: 0.875rem;
  transition: background 0.16s ease, box-shadow 0.16s ease;
}

.msg-user--share-mode:hover {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.msg-user--share-selected {
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  box-shadow: inset 0 0 0 2px var(--accent);
}

/* Checkbox-style selection indicator: empty outlined circle when unselected,
   accent-filled with a check when selected. Always visible in share mode. */
.chat-share-picker {
  position: absolute;
  right: 0.45rem;
  top: 0.65rem;
  z-index: 2;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  border: 2px solid var(--border-strong);
  border-radius: 999px;
  background: var(--bg-surface);
  color: var(--text-muted);
  box-shadow: var(--shadow-md);
  cursor: pointer;
  transition: transform 0.14s ease, border-color 0.14s ease, background 0.14s ease, color 0.14s ease;
}

.chat-share-picker:hover {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--accent) 55%, var(--border-strong));
}

.chat-share-picker:focus-visible {
  outline: none;
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

.chat-share-picker.is-selected {
  border-color: var(--accent);
  background: var(--accent);
  color: var(--accent-foreground);
}

@media (prefers-reduced-motion: reduce) {
  .chat-share-picker {
    transition: none;
  }
}

.msg-user-bubble {
  background: var(--bg-elevated);
  color: var(--text);
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

/* Touch screens have no hover to reveal the row — keep it visible there. */
@media (hover: none) {
  .msg-user-actions {
    opacity: 1;
  }
}

.msg-time {
  display: inline-flex;
  align-items: baseline;
  gap: 0.25rem;
  margin-left: 0.25rem;
  align-self: center;
  font-size: var(--fs-xs);
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.msg-time__rel {
  color: color-mix(in srgb, var(--text-dim) 80%, transparent);
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
  background: var(--bg-hover);
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
  color: var(--text-dim);
}

@media (max-width: 640px) {
  .msg-user--share-mode {
    width: min(calc(100% - 12px), 1012px);
    max-width: calc(100% - 12px);
    padding: 0.5rem 2.25rem 0.5rem 0.75rem;
  }

  .chat-share-picker {
    right: 0.35rem;
  }

  .msg-user-bubble {
    max-width: 90%;
  }
}
</style>

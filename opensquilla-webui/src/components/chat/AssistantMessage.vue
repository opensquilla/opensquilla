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
      :aria-label="shareSelected ? 'Remove from share image' : 'Add to share image'"
      @click.stop="emit('toggleShare', shareMessageId)"
    >
      <Icon v-if="shareSelected" name="check" :size="13" />
    </button>
    <div class="msg-ai-main">
      <ReasoningPart v-if="reasoningPart" :part="reasoningPart" />
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
        <TextPart v-if="standaloneTextPart" :part="standaloneTextPart" :sources="message.sources ?? []" @citation="onCitation" />
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

      <!-- Inline interrupts: approval / clarify requests that blocked the run,
           rendered after the body and before the ending deliverables. -->
      <InterruptPart
        v-for="part in interruptParts"
        :key="part.key"
        :part="part"
        @resolve="(id, decision, note) => $emit('resolveInterrupt', id, decision, note)"
        @extend="id => $emit('extendInterrupt', id)"
        @clarify-submit="fields => $emit('clarifySubmit', fields)"
        @clarify-dismiss="$emit('clarifyDismiss')"
      />

      <!-- What the agent did this turn: an expandable activity timeline of the
           accepted phase transitions, shown before the ending deliverables. -->
      <StatusHistoryPart
        v-if="statusHistory.length"
        :entries="statusHistory"
      />

      <div
        class="msg-ai-ending"
        :class="{ 'msg-ai-ending--done': showDoneBlock }"
        :data-testid="showDoneBlock ? 'done-block' : undefined"
      >
        <ChatArtifactList
          v-if="message.artifacts?.length"
          :artifacts="message.artifacts"
          :session-key="sessionKey"
          :auth-token="authToken"
          @download="$emit('downloadArtifact', $event)"
        />

        <SourcesRow v-if="message.toolCalls?.length" ref="sourcesRowRef" :calls="message.toolCalls" :sources="message.sources ?? []" />

        <div class="msg-ai-footer">
          <div v-if="message.meta" class="msg-ai-meta">
            <span v-if="message.meta.model" class="msg-meta__model">{{ message.meta.modelShort }}</span>
            <span v-if="message.meta.costUsd" class="msg-meta__cost">${{ message.meta.costUsd.toFixed(6).replace(/\.?0+$/, '') }}</span>
            <span v-if="message.meta.hasSaved" class="savings-indicator">{{ message.meta.savedLabel }}</span>
            <span
              v-if="hasMetaDetails"
              ref="metaMoreRef"
              class="msg-meta__more"
              @mouseenter="metaHovered = true"
              @mouseleave="metaHovered = false"
              @keydown.escape.stop="closeMetaDetails"
              @focusout="onMetaFocusOut"
            >
              <button
                ref="metaTriggerRef"
                type="button"
                class="msg-meta__more-btn"
                :aria-expanded="metaDetailsOpen"
                :aria-controls="metaDetailsId"
                aria-label="Usage details"
                @click="metaPinned = !metaPinned"
              >
                <Icon name="info" :size="12" />
              </button>
              <div
                v-if="metaDetailsOpen"
                :id="metaDetailsId"
                class="msg-meta-popover"
                role="group"
                aria-label="Usage details"
              >
                <div v-if="message.meta.hasTokens" class="msg-meta-popover__row">
                  <span class="msg-meta-popover__label">tokens</span>
                  <span class="msg-meta-popover__value">&#8593;{{ fmtTok(message.meta.input) }} &#8595;{{ fmtTok(message.meta.output) }}</span>
                </div>
                <div v-if="message.meta.cachedTokens" class="msg-meta-popover__row">
                  <span class="msg-meta-popover__label">cache</span>
                  <span class="msg-meta-popover__value">{{ fmtTok(message.meta.cachedTokens) }}</span>
                </div>
                <div v-if="message.meta.reasoningTokens" class="msg-meta-popover__row">
                  <span class="msg-meta-popover__label">think</span>
                  <span class="msg-meta-popover__value">{{ fmtTok(message.meta.reasoningTokens) }}</span>
                </div>
              </div>
            </span>
          </div>
          <div v-if="!shareMode" class="msg-ai-actions">
            <button
              type="button"
              class="msg-action"
              :class="{ 'msg-action--ok': copyState === 'ok', 'msg-action--err': copyState === 'err' }"
              :title="copyTitle"
              :aria-label="copyTitle"
              @click="onCopyClick"
            >
              <Icon :name="copyIconName" :size="12" />
            </button>
            <span class="msg-copy-live" aria-live="polite">{{ copyLiveText }}</span>
            <button type="button" class="msg-action" title="Regenerate" aria-label="Regenerate" @click="$emit('regenerate', message)">
              <Icon name="refresh" :size="12" />
            </button>
            <button
              v-if="isTip"
              type="button"
              class="msg-action msg-action--fork"
              data-testid="fork-conversation"
              :disabled="forkBusy"
              title="Fork conversation"
              aria-label="Fork conversation"
              @click="$emit('fork')"
            >
              <Icon name="fork" :size="12" />
            </button>
            <time v-if="timeIso" class="msg-time" :datetime="timeIso" :title="timeFull">
              <span class="msg-time__abs">{{ timeAbs }}</span>
              <span class="msg-time__dot" aria-hidden="true">·</span>
              <span class="msg-time__rel">{{ timeRel }}</span>
            </time>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ChatArtifactList from '@/components/chat/ChatArtifactList.vue'
import SourcesRow from '@/components/chat/SourcesRow.vue'
import ToolCallTimeline from '@/components/chat/ToolCallTimeline.vue'
import InterruptPart from '@/components/chat/parts/InterruptPart.vue'
import ReasoningPart from '@/components/chat/parts/ReasoningPart.vue'
import StatusHistoryPart from '@/components/chat/parts/StatusHistoryPart.vue'
import TextPart from '@/components/chat/parts/TextPart.vue'
import { useCopyFeedback } from '@/composables/chat/useCopyFeedback'
import { useRelativeNow } from '@/composables/useRelativeNow'
import type {
  ChatRenderedMessage,
  ChatStreamTimelineItem,
  ChatToolCall,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
} from '@/types/chat'
import type { ChatPart } from '@/types/parts'
import type { ArtifactPayload } from '@/types/rpc'
import { absoluteTime, fullTime, isoTime, relativeTime } from '@/utils/messageTime'

const props = defineProps<{
  message: ChatRenderedMessage
  index: number
  shareMode: boolean
  shareSelected: boolean
  shareMessageId: string
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
  /** True on the thread's last assistant message — the only place the whole-conversation fork action renders. */
  isTip?: boolean
  forkBusy?: boolean
}>()

const emit = defineEmits<{
  regenerate: [message: ChatRenderedMessage]
  toggleShare: [messageId: string]
  downloadArtifact: [artifact: ArtifactPayload]
  toggleToolGroup: [groupId: string]
  toggleToolItem: [renderKey: string]
  showToolResult: [content: string, title: string]
  fork: []
  resolveInterrupt: [id: string, decision: 'allow-once' | 'allow-always' | 'deny', note?: string]
  extendInterrupt: [id: string]
  clarifySubmit: [fields: Record<string, string>]
  clarifyDismiss: []
}>()

// Absolute label is static; only the relative label subscribes to the shared
// clock, so a tick re-evaluates one cheap computed per visible bubble.
const now = useRelativeNow()
const timeIso = computed(() => isoTime(props.message.ts))
const timeAbs = computed(() => absoluteTime(props.message.ts))
const timeRel = computed(() => relativeTime(props.message.ts, now.value))
const timeFull = computed(() => fullTime(props.message.ts))

// reasoning + standalone text now come pre-folded on message.parts (see toParts).
// The text part already carries pre-rendered, sanitized html, so this component
// no longer re-runs renderMarkdown for the body.
const reasoningPart = computed(
  () =>
    props.message.parts?.find(
      (part): part is Extract<ChatPart, { type: 'reasoning' }> => part.type === 'reasoning',
    ) ?? null,
)
// Standalone text only exists in the no-timeline body: toParts emits a single
// text part (key `${ownerKey}:text`) and never alongside a timeline.
const standaloneTextPart = computed(() =>
  props.message.timelineItems?.length
    ? null
    : props.message.parts?.find(
        (part): part is Extract<ChatPart, { type: 'text' }> => part.type === 'text',
      ) ?? null,
)
// Inline interrupt parts (approval / clarify) fold into the body order after
// text/tools and before the ending; render them through the shared adapter.
const interruptParts = computed(
  () =>
    props.message.parts?.filter(
      (part): part is Extract<ChatPart, { type: 'interrupt' }> => part.type === 'interrupt',
    ) ?? [],
)
// The persisted activity timeline for this finished turn. Empty (fold hidden)
// for OFF-mode turns and reloaded threads, which carry no snapshot.
const statusHistory = computed(() => props.message.statusHistory ?? [])

// A citation pill in the body asks the paired SourcesRow to reveal + highlight
// the source it points at. No-op when no SourcesRow is mounted (which only
// happens when there are no sources, so the body has no pills either).
const sourcesRowRef = ref<InstanceType<typeof SourcesRow> | null>(null)
function onCitation(sourceId: number) {
  sourcesRowRef.value?.focusSource(sourceId)
}

const { copyState, copyIconName, copyTitle, copyLiveText, onCopyClick } = useCopyFeedback(
  () => props.copyMessage(props.message),
)

const metaMoreRef = ref<HTMLElement | null>(null)
const metaTriggerRef = ref<HTMLButtonElement | null>(null)
const metaPinned = ref(false)
const metaHovered = ref(false)
const metaDetailsOpen = computed(() => metaPinned.value || metaHovered.value)

// A completed turn that produced artifacts ends with the deliverable block:
// artifact chips, then sources, then the receipt, grouped as one ending.
const showDoneBlock = computed(() =>
  !!props.message.artifacts?.length && !props.message.isStreaming && !props.message.interrupted,
)

const hasMetaDetails = computed(() => {
  const meta = props.message.meta
  if (!meta) return false
  return meta.hasTokens || meta.cachedTokens > 0 || meta.reasoningTokens > 0
})

const metaDetailsId = computed(
  () => `msg-meta-details-${props.message.messageId || props.message.id || props.index}`,
)

function closeMetaDetails() {
  if (!metaDetailsOpen.value) return
  metaPinned.value = false
  metaHovered.value = false
  metaTriggerRef.value?.focus()
}

function onMetaFocusOut(event: FocusEvent) {
  const next = event.relatedTarget
  if (next instanceof Node && metaMoreRef.value?.contains(next)) return
  if (next === null) return
  metaPinned.value = false
}

function onDocumentPointerDown(event: PointerEvent) {
  const root = metaMoreRef.value
  if (!root) return
  if (event.target instanceof Node && root.contains(event.target)) return
  metaPinned.value = false
  metaHovered.value = false
}

watch(metaDetailsOpen, open => {
  if (open) document.addEventListener('pointerdown', onDocumentPointerDown, true)
  else document.removeEventListener('pointerdown', onDocumentPointerDown, true)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown, true)
})

const legacyTimelineItems = computed<ChatStreamTimelineItem[]>(() => {
  const calls = props.message.toolCalls || []
  // message.id is always set ("${role}-${sourceIndex}") and equals the
  // composable's ownerKey when messageId is absent, so tool renderKeys match the
  // keys toParts folds. The final term only types the fallback and reconstructs
  // the same owner the composable used; it is unreachable while id is set.
  const baseKey = props.message.messageId || props.message.id || `${props.message.role}-${props.message.sourceIndex}`
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
  width: var(--chat-col, min(calc(100% - 48px), 980px));
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
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  box-shadow: inset 0 0 0 2px var(--accent);
}

/* Checkbox-style selection indicator: empty outlined circle when unselected,
   accent-filled with a check when selected. Always visible in share mode. */
.chat-share-picker {
  position: absolute;
  left: 0.45rem;
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

.msg-ai-main {
  flex: 1;
  min-width: 0;
  max-width: none;
  padding-top: 0.0625rem;
}

.msg-ai-footer {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-top: 0.25rem;
}

.msg-ai-ending--done {
  margin-top: 0.625rem;
  padding: 0.625rem 0.75rem;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: color-mix(in srgb, var(--bg-surface) 55%, transparent);
}

.msg-ai-ending--done :deep(.msg-artifacts) {
  margin: 0;
}

.msg-ai-ending--done :deep(.sources-row) {
  margin: 0.5rem 0 0;
}

.msg-ai-ending--done .msg-ai-footer {
  margin-top: 0.5rem;
  padding-top: 0.5rem;
  border-top: 1px solid var(--hairline);
}

.msg-ai-actions {
  display: flex;
  gap: 0.125rem;
  opacity: 0;
  transition: opacity 0.15s;
}

.msg-ai:hover .msg-ai-actions,
.msg-ai-actions:focus-within {
  opacity: 1;
}

/* Touch screens have no hover to reveal the cluster — keep it always visible
   and give the buttons real tap targets. */
@media (hover: none) {
  .msg-ai-actions {
    opacity: 1;
  }

  .msg-action {
    min-width: 2.75rem;
    min-height: 2.75rem;
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
  padding: 0.25rem;
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

.msg-action:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

/* Fork creates something new — its hover signal is the accent, not text-muted. */
.msg-action--fork:hover {
  color: var(--accent);
}

.msg-action--fork:disabled {
  cursor: progress;
  opacity: 0.55;
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
  align-items: center;
  min-width: 0;
  gap: 0.5rem;
  font-size: 0.8125rem;
  line-height: 1.35;
  color: color-mix(in srgb, var(--text-muted) 56%, transparent);
}

.msg-ai-meta > span:not(.savings-indicator):not(.msg-meta__more) {
  opacity: 0.72;
  transition: opacity 0.16s ease, color 0.16s ease;
}

.msg-ai:hover .msg-ai-meta > span:not(.savings-indicator):not(.msg-meta__more) {
  opacity: 0.88;
}

.msg-meta__cost {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.msg-meta__more {
  position: relative;
  display: inline-flex;
  align-items: center;
}

.msg-meta__more-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.25rem;
  height: 1.25rem;
  padding: 0;
  background: none;
  border: none;
  border-radius: 999px;
  color: var(--text-dim);
  cursor: pointer;
  transition: color var(--transition), background var(--transition);
}

.msg-meta__more-btn:hover,
.msg-meta__more-btn[aria-expanded='true'] {
  color: var(--text-muted);
  background: var(--bg-hover);
}

.msg-meta__more-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 18%, transparent);
}

.msg-meta-popover {
  position: absolute;
  bottom: calc(100% + 0.375rem);
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 10rem;
  max-width: min(18rem, calc(100vw - 2rem));
  padding: 0.5rem 0.625rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-md);
  box-shadow: var(--shadow-md);
  color: var(--text-muted);
  font-size: var(--fs-xs);
  line-height: 1.4;
  white-space: nowrap;
}

.msg-meta-popover__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.75rem;
}

.msg-meta-popover__label {
  color: var(--text-dim);
}

.msg-meta-popover__value {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  color: var(--text);
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
  animation: savingsSweep 5.6s ease-in-out infinite;
  opacity: 0.55;
  pointer-events: none;
}

@keyframes savingsSweep {
  0%, 62% {
    left: -60%;
  }
  84%, 100% {
    left: 118%;
  }
}

@media (prefers-reduced-motion: reduce) {
  .savings-indicator::after {
    animation: none;
    display: none;
  }
}

@media (max-width: 768px) {
  .msg-ai-footer {
    min-width: 0;
  }

  .msg-ai-meta {
    flex: 1;
    flex-wrap: nowrap;
    gap: 0.375rem;
  }

  .msg-meta__model {
    flex: 0 1 auto;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .msg-meta__cost,
  .savings-indicator,
  .msg-meta__more {
    flex-shrink: 0;
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

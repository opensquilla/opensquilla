<template>
  <div class="chat" :class="{ 'chat--new-landing': isNewChatLanding }">
    <!-- Header -->
    <div v-if="!isNewChatLanding" class="chat-header">
      <div class="chat-header-left">
        <label class="chat-label" :title="sessionKey">{{ currentChatTitle }}</label>
        <button
          class="chat-session-copy-btn"
          title="Copy session key"
          aria-label="Copy session key"
          @click="copySessionKey"
        >
          <Icon name="copy" :size="14" />
        </button>
      </div>
      <div class="chat-header-right">
        <span class="chip" :class="runStatusChipClass" :title="runStatusTitle">{{ runStatusLabel }}</span>
      </div>
    </div>

    <!-- Thread -->
    <div class="chat-body">
      <div
        ref="threadRef"
        class="chat-thread"
        role="region"
        aria-label="Chat conversation"
        :aria-busy="isStreaming"
        @scroll="onThreadScroll"
        @dragover.prevent="threadDragOver = true"
        @dragleave="threadDragOver = false"
        @drop.prevent="onThreadDrop"
        :class="{ 'drag-over': threadDragOver }"
      >
        <div v-if="isNewChatLanding" class="chat-landing-brand" aria-label="OpenSquilla new chat">
          <img class="chat-landing-lockup" :src="landingLockupUrl" alt="OpenSquilla" />
        </div>
        <div v-else-if="messages.length === 0 && !isStreaming" class="chat-empty">No messages yet.</div>

        <ChatMessageList
          :messages="renderedMessages"
          :assistant-avatar-url="assistantAvatarUrl"
          :strip-time-prefix="stripTimePrefix"
          :render-markdown="renderMarkdown"
          :fmt-tok="fmtTok"
          :subagent-summary="subagentSummary"
          :subagent-body="subagentBody"
          :tool-call-groups="toolCallGroups"
          :is-tool-group-open="isToolGroupOpen"
          :is-tool-item-open="isToolItemOpen"
          :tool-group-status-text="toolGroupStatusText"
          :tool-status-text="toolStatusText"
          :tool-secondary-text="toolSecondaryText"
          @copy-message="copyMessage"
          @edit-message="editMessage"
          @regenerate-message="regenerateMessage"
          @download-artifact="downloadArtifact"
          @toggle-tool-group="toggleToolGroup"
          @toggle-tool-item="toggleToolItem"
          @show-tool-result="showToolResultModal"
        >
          <template #router-strip="{ message: msg }">
            <RouterFxStrip :message="msg" />
          </template>
        </ChatMessageList>

        <!-- Streaming AI message (Kimi style) -->
        <div v-if="isStreaming && streamBubble" class="msg-ai" data-history-role="assistant" aria-live="polite">
          <div class="msg-ai-avatar">
            <img class="msg-ai-avatar__img" :src="assistantAvatarUrl" alt="" aria-hidden="true" />
          </div>
          <div class="msg-ai-main">
            <ToolCallTimeline
              :items="streamTimelineItems"
              :is-tool-group-open="isToolGroupOpen"
              :is-tool-item-open="isToolItemOpen"
              :tool-group-status-text="toolGroupStatusText"
              :tool-status-text="toolStatusText"
              :tool-secondary-text="toolSecondaryText"
              @toggle-group="toggleToolGroup"
              @toggle-item="toggleToolItem"
              @show-result="showToolResultModal"
            />

            <div v-if="streamActivityVisible" class="stream-activity" role="status" aria-live="polite">
              <span class="stream-activity-dot" aria-hidden="true" />
              <span class="stream-activity-text activity-shimmer">{{ streamActivityText }}</span>
            </div>

            <ChatArtifactList :artifacts="streamArtifacts" @download="downloadArtifact" />

          </div>
        </div>

        <!-- Thinking indicator -->
        <div v-if="thinkingVisible" class="msg-ai thinking" role="status" aria-live="polite">
          <div class="msg-ai-avatar">
            <img class="msg-ai-avatar__img" :src="assistantAvatarUrl" alt="" aria-hidden="true" />
          </div>
          <div class="msg-ai-main">
            <div class="thinking-status">
              <span class="stream-activity-dot" aria-hidden="true" />
              <span class="thinking-elapsed activity-shimmer" aria-live="off">{{ thinkingText }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <PendingQueue
      :items="pendingQueue"
      :max-pending="maxPending"
      @clear="clearPendingQueue"
      @remove="removePendingChip"
    />

    <!-- Compact status -->
    <div v-if="compactStatus.visible" class="chat-compact-status" :class="`chat-compact-status--${compactStatus.tone}`" role="status" aria-live="polite">
      <span :class="compactStatus.isBusy ? 'chat-compact-status__spinner' : 'chat-compact-status__dot'" aria-hidden="true" />
      <span class="chat-compact-status__text">{{ compactStatus.message }}</span>
      <span v-if="compactStatus.detail" class="chat-compact-status__detail">{{ compactStatus.detail }}</span>
    </div>

    <!-- Slash command menu -->
    <div v-if="slashOpen" class="chat-slash">
      <div
        v-for="(cmd, i) in filteredSlashCmds"
        :key="cmd.cmd"
        class="chat-slash-item"
        :class="{ 'chat-slash-item--active': i === slashIdx }"
        @click="selectSlashCmd(cmd)"
      >
        <span class="chat-slash-cmd">{{ cmd.cmd }}</span>
        <span class="chat-slash-desc">{{ cmd.desc }}</span>
      </div>
    </div>

    <ChatComposer
      ref="composerRef"
      v-model="inputText"
      :attachments="pendingAttachments"
      :has-send-content="hasSendContent"
      :is-streaming="isStreaming"
      :is-new-landing="isNewChatLanding"
      :placeholder="composerPlaceholder"
      :send-button-title="sendButtonTitle"
      @composition-change="composing = $event"
      @file-change="onFileInputChange"
      @input="onTextareaInput"
      @keydown="onTextareaKeydown"
      @remove-attachment="removeAttachment"
      @send="onSend"
      @stop="onStop"
    />

    <ToolResultModal
      :open="toolResultModal.open"
      :title="toolResultModal.title"
      :content="toolResultModal.content"
      @close="toolResultModal.open = false"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import { useAppStore } from '@/stores/app'
import ChatArtifactList from '@/components/chat/ChatArtifactList.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import PendingQueue from '@/components/chat/PendingQueue.vue'
import RouterFxStrip from '@/components/chat/RouterFxStrip.vue'
import ToolCallTimeline from '@/components/chat/ToolCallTimeline.vue'
import ToolResultModal from '@/components/chat/ToolResultModal.vue'
import Icon from '@/components/Icon.vue'
import { useChatAttachments } from '@/composables/chat/useChatAttachments'
import { useChatCompaction } from '@/composables/chat/useChatCompaction'
import { useChatComposerShortcuts } from '@/composables/chat/useChatComposerShortcuts'
import { useChatElevatedMode } from '@/composables/chat/useChatElevatedMode'
import { useChatFeatureToggles } from '@/composables/chat/useChatFeatureToggles'
import { useChatHistory } from '@/composables/chat/useChatHistory'
import { useChatMessageActions } from '@/composables/chat/useChatMessageActions'
import { useChatPendingQueue } from '@/composables/chat/useChatPendingQueue'
import { useMediaQuery } from '@/composables/chat/useMediaQuery'
import {
  fmtTok,
  truncate,
  useChatRenderedMessages,
} from '@/composables/chat/useChatRenderedMessages'
import { useChatRouterDecisionRuntime } from '@/composables/chat/useChatRouterDecisionRuntime'
import { useChatRpcEventHandlers } from '@/composables/chat/useChatRpcEventHandlers'
import { useChatRpcSubscriptions } from '@/composables/chat/useChatRpcSubscriptions'
import { useChatSend } from '@/composables/chat/useChatSend'
import { useChatSessionRoute } from '@/composables/chat/useChatSessionRoute'
import { useChatSessionRuntime } from '@/composables/chat/useChatSessionRuntime'
import { useChatSessionSubscription } from '@/composables/chat/useChatSessionSubscription'
import { useChatSlashCommands } from '@/composables/chat/useChatSlashCommands'
import { useChatStream } from '@/composables/chat/useChatStream'
import { useChatTextRendering } from '@/composables/chat/useChatTextRendering'
import { useChatUsageWidget } from '@/composables/chat/useChatUsageWidget'
import { useDocumentEvent } from '@/composables/useDocumentEvent'
import type {
  ChatMessage,
  ChatRunStatus,
  ChatRunStatusSource,
  ChatRunStatusState,
} from '@/types/chat'
import type {
  ArtifactPayload,
} from '@/types/rpc'
import { artifactDownloadUrl } from '@/utils/chat/artifacts'
import { copyTextWithFallback, downloadBlob } from '@/utils/browser'
import {
  toolCallGroups,
  toolGroupStatusText,
  toolSecondaryText,
  toolStatusText,
} from '@/utils/chat/toolDisplay'

/* ── Types ─────────────────────────────────────────────────────────── */

interface ChatComposerHandle {
  composerElement: () => HTMLElement | null
  focusTextarea: () => void
  isTextareaFocused: () => boolean
  resizeTextarea: () => void
}

type Message = ChatMessage

/* ── Constants ─────────────────────────────────────────────────────── */

const ROUTER_FX_GRID_CELLS = 12
const ROUTER_FX_DECOY_POOL = [
  'claude-sonnet-4.6',
  'claude-haiku-4.5',
  'gpt-5-mini',
  'gemini-2.5-flash',
  'deepseek-r1',
  'gpt-5',
  'claude-opus-4.7',
  'gemini-2.5-pro',
  'gemini-2.0-flash',
  'llama-4-405b',
  'mistral-large-3',
  'qwen-3-72b',
  'grok-3-mini',
  'sonar-large',
  'command-r-plus',
  'jamba-1.5-large',
]
const CHAT_RUN_STATUS_VALUES: ChatRunStatusState[] = [
  'queued',
  'running',
  'interrupted',
  'failed',
  'timeout',
  'cancelled',
]

const toolResultModal = ref({ open: false, title: '', content: '' })

/* ── Stores / Router ───────────────────────────────────────────────── */

const rpc = useRpcStore()
const appStore = useAppStore()
const isCompactViewport = useMediaQuery('(max-width: 480px)')
const isDesktopViewport = useMediaQuery('(min-width: 769px)')
const assistantAvatarUrl = computed(() => {
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base}/static/img/opensquilla-mark.png`
})
const landingLockupUrl = computed(() => {
  const base = document.getElementById('opensquilla-data')?.dataset.basePath || '/control'
  return `${base}/static/img/opensquilla-long-logo.png?v=20260601`
})

/* ── DOM refs ──────────────────────────────────────────────────────── */

const threadRef = ref<HTMLElement | null>(null)
const composerRef = ref<ChatComposerHandle | null>(null)

/* ── State ─────────────────────────────────────────────────────────── */

const sessionKey = ref('')
const inputText = ref('')
const aborted = ref(false)
const autoScroll = ref(true)
const composing = ref(false)
const messages = ref<Message[]>([])

// Session / UI
const lastHeaderRole = ref('')
const lastHeaderDay = ref('')
const threadDragOver = ref(false)

const chatElevatedMode = useChatElevatedMode({
  sessionKey,
})
const {
  elevatedMode,
  loadElevatedMode,
  setGlobalElevatedMode,
  normalizeElevatedMode,
} = chatElevatedMode

// Run status
const runStatus = ref<ChatRunStatus>({ status: 'idle', label: 'Idle', task: null })

// Epoch / seq
const currentEpoch = ref(0)
const lastStreamSeq = ref(0)
const activeTaskGroups = ref<Set<string>>(new Set())

// Pending session intent
const pendingSessionIntent = ref<string | null>(null)
let applySessionRunState: (source: ChatRunStatusSource | null | undefined) => void = () => {}
let resetComposerInputHistory: () => void = () => {}

const chatTextRendering = useChatTextRendering()
const {
  renderMarkdown,
  stripDirectiveTags,
  stripGeneratedArtifactMarkers,
  stripProtocolTextLeak,
  stripTimePrefix,
} = chatTextRendering

const chatStream = useChatStream({
  messages,
  lastHeaderRole,
  aborted,
  autoScroll,
  applySessionRunState: source => applySessionRunState(source),
  renderMarkdown,
  stripDirectiveTags,
  stripGeneratedArtifactMarkers,
  stripProtocolTextLeak,
  scrollToBottom,
})
const {
  isStreaming,
  streamArtifacts,
  streamBubble,
  streamHasVisibleOutput,
  streamTimelineItems,
  streamActivityVisible,
  streamActivityText,
  thinkingVisible,
  thinkingText,
  startStreaming,
  resetStreamForRouterReplay,
  resetLiveTurnState: resetStreamLiveTurnState,
  resetStreamIdleTimer,
  setStreamActivity,
  isToolGroupOpen,
  toggleToolGroup,
  isToolItemOpen,
  toggleToolItem,
  cleanup: cleanupStream,
} = chatStream

const chatRouterDecisionRuntime = useChatRouterDecisionRuntime({
  messages,
  sessionKey,
  isStreaming,
  streamBubble,
  streamHasVisibleOutput,
  startStreaming,
  resetStreamForRouterReplay,
  resetStreamIdleTimer,
  setStreamActivity,
  scrollToBottom,
})
const {
  pendingDecision,
  handleRouterControlReplay,
  queueRouterDecision,
  flushPendingRouterDecision,
  clearPendingRouterDecision,
} = chatRouterDecisionRuntime

const chatAttachments = useChatAttachments()
const {
  pendingAttachments,
  onFileInputChange,
  addAttachment,
  removeAttachment,
  hasPendingAttachmentWork,
} = chatAttachments

let sendCurrentInput: () => void = () => {}
let isCompactInFlightForCurrentSession: () => boolean = () => false
const chatPendingQueue = useChatPendingQueue({
  inputText,
  pendingAttachments,
  pendingSessionIntent,
  isStreaming,
  isBlocked: () => isCompactInFlightForCurrentSession(),
  autoResizeTextarea,
  sendCurrentInput: () => sendCurrentInput(),
  resetInputHistory: () => resetComposerInputHistory(),
  hasComposer: () => Boolean(composerRef.value),
})
const {
  pendingQueue,
  canQueueMore,
  maxPending,
  enqueuePendingInput,
  removePendingChip,
  clearPendingQueue,
  popPendingTail,
  popAllPendingIntoComposer,
  schedulePendingDrainAfterTerminal,
  cleanup: cleanupPendingQueue,
} = chatPendingQueue

const chatCompaction = useChatCompaction({
  sessionKey,
  schedulePendingDrainAfterTerminal,
  popAllPendingIntoComposer,
})
const {
  compactStatus,
  setCompactInFlight,
  hideCompactStatus,
  showCompactStatus,
  showCompactionToast,
  cleanup: cleanupCompaction,
} = chatCompaction
isCompactInFlightForCurrentSession = chatCompaction.isCompactInFlightForCurrentSession

const chatUsageWidget = useChatUsageWidget({
  rpc,
  sessionKey,
  tokenVizEnabled: () => appStore.features.tokenViz,
})
const {
  usageAccum,
  usageModel,
  resetSavingsPopupCooldown,
  saveWidgetState,
  restoreWidgetState,
  loadCurrentSessionUsage,
} = chatUsageWidget

const chatFeatureToggles = useChatFeatureToggles({
  rpc,
  setGlobalElevatedMode,
  loadCurrentSessionUsage,
})
const {
  routerSlots,
  routerModels,
  loadFeatureToggles,
} = chatFeatureToggles

const chatSessionRoute = useChatSessionRoute(sessionKey)
const {
  route,
  createSessionKey,
  hasNewChatRouteSignal,
  persistSession,
  resolveInitialSession,
} = chatSessionRoute

const chatRenderedMessages = useChatRenderedMessages({
  messages,
  sessionKey,
  routerSlots,
  routerModels,
  decoyPool: ROUTER_FX_DECOY_POOL,
  gridCells: ROUTER_FX_GRID_CELLS,
  renderMarkdown,
  stripGeneratedArtifactMarkers,
  stripTimePrefix,
  isSubagentCompletionMessage,
})
const { renderedMessages } = chatRenderedMessages

const chatHistory = useChatHistory({
  rpc,
  sessionKey,
  messages,
  lastHeaderRole,
  lastHeaderDay,
  stripTimePrefix,
  scrollToBottom,
})
const {
  loadHistory,
  scheduleHistorySync,
  cleanup: cleanupHistory,
} = chatHistory

const chatMessageActions = useChatMessageActions({
  messages,
  inputText,
  isStreaming,
  autoResizeTextarea,
  sendCurrentInput: () => sendCurrentInput(),
  focusComposer: () => composerRef.value?.focusTextarea(),
})
const {
  copyMessage,
  regenerateMessage,
  editMessage,
} = chatMessageActions

const chatSessionSubscription = useChatSessionSubscription({
  rpc,
  sessionKey,
  lastStreamSeq,
  runStatus,
  isStreaming,
  sessionRunStatus,
  loadHistory,
  resetStreamIdleTimer,
})
const {
  subscribeSession,
  unsubscribeSession,
} = chatSessionSubscription
applySessionRunState = chatSessionSubscription.applySessionRunState

const chatSessionRuntime = useChatSessionRuntime({
  sessionKey,
  messages,
  pendingSessionIntent,
  routerDecisionPending: pendingDecision,
  currentEpoch,
  lastStreamSeq,
  activeTaskGroups,
  aborted,
  lastHeaderRole,
  lastHeaderDay,
  usageAccum,
  usageModel,
  createSessionKey,
  persistSession,
  unsubscribeSession,
  subscribeSession,
  loadHistory,
  loadCurrentSessionUsage,
  applySessionRunState,
  setCompactInFlight,
  hideCompactStatus,
  clearPendingQueue,
  resetSavingsPopupCooldown,
  restoreWidgetState,
  resetStreamLiveTurnState,
})
const {
  consumeNewChatRouteSignal,
  resetCurrentSessionAfterSlash,
  switchToSession,
  newSession,
} = chatSessionRuntime

const chatSlashCommands = useChatSlashCommands({
  rpc,
  inputText,
  sessionKey,
  autoResizeTextarea,
  newSession,
  resetCurrentSession: resetCurrentSessionAfterSlash,
  setCompactInFlight,
  showCompactStatus,
})
const {
  slashOpen,
  slashIdx,
  filteredSlashCmds,
  loadSlashCommands,
  handleSlashInput,
  closeSlashMenu,
  selectSlashCmd,
  executeSlashCommand,
} = chatSlashCommands

const chatComposerShortcuts = useChatComposerShortcuts({
  inputText,
  composing,
  messages,
  pendingQueue,
  canQueueMore,
  slashOpen,
  slashIdx,
  filteredSlashCmds,
  isStreaming,
  autoResizeTextarea,
  handleSlashInput,
  closeSlashMenu,
  selectSlashCmd,
  popPendingTail,
  enqueuePendingInput,
  sendCurrentInput: () => sendCurrentInput(),
})
const {
  onTextareaInput,
  onTextareaKeydown,
} = chatComposerShortcuts
resetComposerInputHistory = chatComposerShortcuts.resetInputHistory

const chatSend = useChatSend({
  rpc,
  inputText,
  messages,
  sessionKey,
  elevatedMode,
  pendingAttachments,
  pendingSessionIntent,
  aborted,
  autoScroll,
  stream: chatStream,
  normalizeElevatedMode,
  persistSession,
  isCompactInFlightForCurrentSession,
  hasPendingAttachmentWork,
  enqueuePendingInput,
  popAllPendingIntoComposer,
  executeSlashCommand,
  closeSlashMenu,
  autoResizeTextarea,
  scrollToBottom,
})
const { onSend, onStop } = chatSend
sendCurrentInput = onSend

const rpcEventHandlers = useChatRpcEventHandlers({
  sessionKey,
  currentEpoch,
  lastStreamSeq,
  activeTaskGroups,
  aborted,
  messages,
  pendingQueue,
  usageAccum,
  usageModel,
  stream: chatStream,
  normalizeRunStatus,
  sessionRunStatus,
  applySessionRunState,
  queueRouterDecision,
  flushPendingRouterDecision,
  clearPendingRouterDecision,
  handleRouterControlReplay,
  showCompactionToast,
  scheduleHistorySync,
  schedulePendingDrainAfterTerminal,
  popAllPendingIntoComposer,
  saveWidgetState,
  subscribeSession,
  loadHistory,
  loadCurrentSessionUsage,
})
const chatRpcSubscriptions = useChatRpcSubscriptions(rpc, rpcEventHandlers.handlers)

// Unsubscribers
let unsubs: (() => void)[] = []
let composerResizeObserver: ResizeObserver | null = null

/* ── Computed ──────────────────────────────────────────────────────── */

const runStatusLabel = computed(() => runStatus.value.label)
const runStatusChipClass = computed(() => {
  const cls: Record<string, string> = {
    queued: 'chip-warn', running: 'chip-ok', interrupted: 'chip-warn',
    failed: 'chip-danger', timeout: 'chip-warn',
  }
  return cls[runStatus.value.status] || ''
})
const runStatusTitle = computed(() => {
  const task = runStatus.value.task
  const parts = [runStatus.value.label]
  if (task?.task_id) parts.push(task.task_id)
  if (task?.terminal_reason) parts.push(task.terminal_reason)
  return parts.filter(Boolean).join(' - ')
})

const isNewChatLanding = computed(() => {
  return messages.value.length === 0 &&
    !isStreaming.value &&
    pendingQueue.value.length === 0 &&
    !compactStatus.value.visible
})

const composerPlaceholder = computed(() => {
  if (isNewChatLanding.value) return '分配一个任务或提问任何问题'
  return isCompactViewport.value ? 'Message...' : 'Send a message...'
})

const hasSendContent = computed(() => {
  return inputText.value.trim().length > 0 || pendingAttachments.value.length > 0
})

const sendButtonTitle = computed(() => {
  if (isCompactInFlightForCurrentSession()) return 'Send (queues until compaction finishes)'
  if (isStreaming.value) return 'Send (queues for after current response)'
  return 'Send'
})

const currentChatTitle = computed(() => {
  const firstUser = messages.value.find(msg => msg.role === 'user' && stripTimePrefix(msg.text || '').trim())
  if (firstUser) {
    return truncate(stripTimePrefix(firstUser.text).replace(/\s+/g, ' ').trim(), 28)
  }
  const suffix = sessionKey.value.split(':').pop() || ''
  if (!suffix || suffix === 'default') return 'New chat'
  return `Chat ${suffix}`
})

/* ── Helpers ───────────────────────────────────────────────────────── */

function normalizeRunStatus(status: string): ChatRunStatusState {
  const value = String(status || '').toLowerCase()
  if (value === 'abandoned') return 'interrupted'
  if (value === 'killed') return 'cancelled'
  if (['succeeded', 'success', 'complete'].includes(value)) return 'idle'
  if (CHAT_RUN_STATUS_VALUES.includes(value as ChatRunStatusState)) return value as ChatRunStatusState
  return 'idle'
}

function runStatusLabelText(status: ChatRunStatusState): string {
  const labels: Record<string, string> = {
    queued: 'Queued', running: 'Running', interrupted: 'Interrupted',
    failed: 'Failed', timeout: 'Timed out', cancelled: 'Cancelled', idle: 'Idle',
  }
  return labels[status] || 'Idle'
}

function sessionRunStatus(source: ChatRunStatusSource | null | undefined): ChatRunStatus {
  const stateSource = source || {}
  const active = stateSource.active_task || stateSource.activeTask || null
  const last = stateSource.last_task || stateSource.lastTask || null
  const activeStatus = active ? normalizeRunStatus(active.status || '') : ''
  let status = normalizeRunStatus(stateSource.run_status || stateSource.runStatus || active?.status || last?.status || '')
  if (active && (activeStatus === 'queued' || activeStatus === 'running')) status = activeStatus
  const task = active || last || null
  return { status, label: runStatusLabelText(status), task }
}

/* ── Subagent ──────────────────────────────────────────────────────── */

function isSubagentCompletionMessage(role: string, text: string, options?: ChatMessage): boolean {
  if (role !== 'system' || !text) return false
  if (options?.provenanceSourceTool === 'subagent_completion') return true
  try {
    const parsed = JSON.parse(text)
    return parsed && parsed.type === 'subagent_completion'
  } catch { return false }
}

function subagentSummary(text: string): string {
  try {
    const parsed = JSON.parse(text)
    return 'Subagent: ' + (parsed.child_session_key || parsed.session_key || 'completion')
  } catch { return 'Subagent completion' }
}

function subagentBody(text: string): string {
  try {
    const parsed = JSON.parse(text)
    return JSON.stringify(parsed, null, 2)
  } catch { return text }
}

/* ── Artifacts ─────────────────────────────────────────────────────── */

async function downloadArtifact(artifact: ArtifactPayload) {
  const url = artifactDownloadUrl(artifact, window.location.origin)
  if (!url) return
  try {
    const headers: Record<string, string> = {}
    if (sessionKey.value) headers['x-opensquilla-session-key'] = sessionKey.value
    const response = await fetch(url, { method: 'GET', headers, credentials: 'same-origin' })
    if (!response.ok) {
      console.warn(`Download failed: HTTP ${response.status}`)
      return
    }
    const blob = await response.blob()
    downloadBlob(blob, artifact.name || 'artifact')
  } catch (err) {
    console.warn('Download failed:', err)
  }
}

function copySessionKey() {
  if (!sessionKey.value) return
  copyTextWithFallback(sessionKey.value).catch(() => {})
}

/* ── Streaming ─────────────────────────────────────────────────────── */

function scrollToBottom() {
  nextTick(() => {
    if (threadRef.value) {
      threadRef.value.scrollTop = threadRef.value.scrollHeight
    }
  })
}

function onThreadScroll() {
  if (!threadRef.value) return
  const gap = threadRef.value.scrollHeight - threadRef.value.scrollTop - threadRef.value.clientHeight
  autoScroll.value = gap < 60
}

/* ── Tool calls ────────────────────────────────────────────────────── */

function showToolResultModal(content: string, title = 'Tool Result') {
  toolResultModal.value = { open: true, title, content }
}

/* ── Attachments ───────────────────────────────────────────────────── */

function onThreadDrop(e: DragEvent) {
  threadDragOver.value = false
  if (e.dataTransfer?.files) {
    Array.from(e.dataTransfer.files).forEach(addAttachment)
  }
}

/* ── Textarea ──────────────────────────────────────────────────────── */

function autoResizeTextarea() {
  composerRef.value?.resizeTextarea()
}

/* ── Clipboard paste ───────────────────────────────────────────────── */

function onDocumentPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  for (let i = 0; i < items.length; i++) {
    if (items[i].type.startsWith('image/')) {
      const file = items[i].getAsFile()
      if (file) addAttachment(file)
    }
  }
}

/* ── Document keydown (ESC) ────────────────────────────────────────── */

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (e.defaultPrevented) return

  if (isStreaming.value) {
    e.preventDefault()
    onStop()
    return
  }

  if (pendingQueue.value.length > 0 && !composerRef.value?.isTextareaFocused()) {
    e.preventDefault()
    popAllPendingIntoComposer()
  }
}

/* ── Lifecycle ─────────────────────────────────────────────────────── */

onMounted(async () => {
  // Initialize session key
  const initialSession = resolveInitialSession()
  const startNewChatOnMount = initialSession.startNewChat
  sessionKey.value = initialSession.sessionKey
  persistSession(sessionKey.value, { updateRoute: !initialSession.hasUrlSession })

  // Load elevated mode
  loadElevatedMode()

  // Load feature toggles
  await loadFeatureToggles()

  // Subscribe to RPC events
  unsubs.push(chatRpcSubscriptions.subscribe())

  // Composer resize observer
  const composerEl = composerRef.value?.composerElement()
  if (composerEl) {
    composerResizeObserver = new ResizeObserver(() => {
      const h = composerRef.value?.composerElement()?.getBoundingClientRect().height || 0
      document.documentElement.style.setProperty('--composer-h', h + 'px')
    })
    composerResizeObserver.observe(composerEl)
  }

  // Load the requested chat state.
  if (startNewChatOnMount) {
    consumeNewChatRouteSignal()
  } else {
    subscribeSession()
    loadHistory()
  }
  loadSlashCommands()

  // Focus textarea on desktop
  if (isDesktopViewport.value) {
    composerRef.value?.focusTextarea()
  }
})

onUnmounted(() => {
  unsubs.forEach(fn => fn())
  unsubs = []
  cleanupPendingQueue()
  cleanupHistory()
  cleanupStream()
  cleanupCompaction()
  if (composerResizeObserver) { composerResizeObserver.disconnect(); composerResizeObserver = null }
  document.documentElement.style.removeProperty('--composer-h')
  unsubscribeSession()
})

useDocumentEvent('paste', onDocumentPaste)
useDocumentEvent('keydown', onDocumentKeydown)

// Watch for route changes
watch(() => route.query.session, (newSession) => {
  if (newSession && typeof newSession === 'string') {
    switchToSession(newSession)
  }
})

// Watch for "new chat" signals from the sidebar. The legacy ?new=1 signal is
// still accepted so older links do not silently restore the previous session.
watch(() => [route.query.newChat, route.query.new], () => {
  if (hasNewChatRouteSignal()) {
    consumeNewChatRouteSignal()
  }
})
</script>

<style scoped src="../styles/chat-view.css"></style>

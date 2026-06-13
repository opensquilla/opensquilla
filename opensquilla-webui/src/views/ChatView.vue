<template>
  <div class="chat" :class="{ 'chat--new-landing': isNewChatLanding }">
    <!-- Header -->
    <div v-if="!isNewChatLanding" class="chat-header">
      <div class="chat-header-left">
        <label class="chat-label" :title="sessionKey">{{ currentChatTitle }}</label>
        <button
          class="chat-session-copy-btn"
          :class="{ 'chat-session-copy-btn--ok': sessionCopyState === 'ok' }"
          :title="sessionCopyState === 'ok' ? 'Copied' : 'Copy session key'"
          :aria-label="sessionCopyState === 'ok' ? 'Copied' : 'Copy session key'"
          @click="onSessionCopyClick"
        >
          <Icon :name="sessionCopyIcon" :size="14" />
        </button>
        <span class="chat-copy-live" aria-live="polite">{{ sessionCopyLiveText }}</span>
      </div>
      <div class="chat-header-right">
        <button
          v-if="sessionArtifacts.length > 0"
          type="button"
          class="chat-share-btn chat-deliverables-btn"
          :title="`Deliverables (${sessionArtifacts.length})`"
          :aria-label="`Deliverables (${sessionArtifacts.length})`"
          @click="openDeliverables"
        >
          <Icon name="download" :size="14" />
          <span class="chat-share-btn__label">Deliverables ({{ sessionArtifacts.length }})</span>
        </button>
        <button
          v-if="!shareMode"
          ref="shareEntryBtnRef"
          type="button"
          class="chat-share-btn"
          :disabled="shareableMessageCount === 0"
          :title="shareableMessageCount === 0 ? 'Send a message first to share' : 'Select bubbles to save as a share image'"
          :aria-label="shareableMessageCount === 0 ? 'Send a message first to share' : 'Share'"
          @click="startShareMode"
        >
          <Icon name="share" :size="14" />
          <span class="chat-share-btn__label">Share</span>
        </button>
        <span class="chip" :class="runStatusChipClass" :title="runStatusTitle">{{ runStatusLabel }}</span>
      </div>
    </div>

    <!-- Thread -->
    <div class="chat-body">
      <!-- Share-mode banner: pinned above the scrolling thread, below the
           header, so it can never collide with the floating topbar cluster. -->
      <div
        v-if="shareMode"
        ref="shareBannerRef"
        class="chat-share-banner"
        tabindex="-1"
        role="group"
        aria-label="Share selected messages"
        data-testid="share-banner"
      >
        <span class="chat-share-banner__hint">Select bubbles to share</span>
        <span class="chat-share-banner__count" role="status" aria-live="polite">{{ selectedShareCount }} selected</span>
        <button
          type="button"
          class="chat-share-btn chat-share-btn--save"
          :disabled="selectedShareCount === 0 || shareSaving"
          :title="selectedShareCount === 0 ? 'Select at least one bubble first' : 'Save selected bubbles as PNG'"
          @click="saveShareImage"
        >
          <Icon name="download" :size="14" />
          <span>{{ shareSaving ? 'Saving…' : 'Save PNG' }}</span>
        </button>
        <button type="button" class="chat-share-btn" title="Cancel share selection" @click="endShareMode">
          Cancel
        </button>
      </div>
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
          <EmptyStateChips
            :key="landingAgentId"
            :agent-id="landingAgentId"
            :suppressed="landingPrefilled"
            @pick="applyLandingSuggestion"
          />
        </div>
        <div v-else-if="messages.length === 0 && !isStreaming" class="chat-empty">No messages yet.</div>
        <ChatHistoryScopeRow
          v-if="!isNewChatLanding"
          :state="historyState"
          @load-earlier="loadEarlierHistory"
        />

        <ChatMessageList
          :messages="renderedMessages"
          :session-key="sessionKey"
          :auth-token="readAuthToken()"
          :share-mode="shareMode"
          :selected-message-ids="selectedShareMessageIds"
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
          :copy-message="copyMessage"
          :fork-busy="forkInFlight"
          @fork-conversation="forkConversation"
          @edit-message="editMessage"
          @regenerate-message="regenerateMessage"
          @toggle-share-message="toggleShareMessage"
          @download-artifact="downloadArtifact"
          @toggle-tool-group="toggleToolGroup"
          @toggle-tool-item="toggleToolItem"
          @show-tool-result="showToolResultModal"
        >
          <template #router-strip="{ message: msg }">
            <RouterFxStrip :message="msg" />
          </template>
        </ChatMessageList>

        <!-- Invisible router-strip twin: holds the strip's slot in the layout
             from turn start until the routing decision arrives, so the real
             strip cannot shift the content below it. -->
        <RouterFxStrip
          v-if="routerStripReserve"
          class="router-fx-reserve"
          :message="routerStripReserve"
          aria-hidden="true"
        />

        <!-- Streaming AI message: the live run is promoted into a centered
             work card so it owns the focus while the agent works. -->
        <div v-if="isStreaming && streamBubble" class="msg-ai" data-history-role="assistant" aria-live="polite">
          <div class="msg-ai-main">
            <section
              class="work-card"
              :class="{ 'work-card--stale': streamActivityStale }"
              role="status"
              aria-live="polite"
            >
              <header v-if="streamActivityVisible" class="work-card__head stream-activity">
                <span class="work-card__dot" aria-hidden="true" />
                <span class="work-card__phase" :class="{ 'activity-shimmer': !streamActivityStale }">{{ streamPhaseLabel }}</span>
                <span v-if="streamPhaseElapsed" class="work-card__elapsed">{{ streamPhaseElapsed }}</span>
                <span class="work-card__step">{{ streamStepLabel }}</span>
              </header>

              <!-- Live model reasoning: collapsed by default, expandable mid-turn -->
              <details v-if="streamThinkingText" class="thinking-fold">
                <summary class="thinking-fold__summary">
                  <Icon class="thinking-fold__chevron" name="chevronRight" :size="12" />
                  <span>Thinking · {{ streamThinkingElapsedText }}</span>
                </summary>
                <div class="thinking-fold__body">{{ streamThinkingText }}</div>
              </details>

              <ToolCallTimeline
                v-if="streamTimelineItems.length"
                class="work-card__timeline"
                variant="checklist"
                :items="streamTimelineItems"
                :is-tool-group-open="isToolGroupOpen"
                :is-tool-item-open="isToolItemOpen"
                :tool-group-status-text="toolGroupStatusText"
                :tool-status-text="toolStatusText"
                :tool-secondary-text="toolSecondaryText"
                :tool-elapsed-text="streamToolElapsedText"
                @toggle-group="toggleToolGroup"
                @toggle-item="toggleToolItem"
                @show-result="showToolResultModal"
              />
            </section>

            <ChatArtifactList
              :artifacts="streamArtifacts"
              :session-key="sessionKey"
              :auth-token="readAuthToken()"
              @download="downloadArtifact"
            />

          </div>
        </div>

        <!-- Thinking indicator -->
        <div v-if="thinkingVisible" class="msg-ai thinking" role="status" aria-live="polite">
          <div class="msg-ai-main">
            <div class="thinking-status">
              <span class="stream-activity-dot" aria-hidden="true" />
              <span class="thinking-elapsed activity-shimmer" aria-live="off">{{ thinkingText }}</span>
            </div>
          </div>
        </div>

        <!-- In-thread approval cards: blocked runs ask for a decision here -->
        <ApprovalCard
          v-for="entry in approvalEntries"
          :key="entry.approval.id"
          :approval="entry.approval"
          :resolution="entry.resolution"
          :busy="approvalBusyIds.has(entry.approval.id)"
          :error="entry.error"
          @allow-once="resolveApproval(entry, 'allow-once')"
          @allow-always="resolveApproval(entry, 'allow-always')"
          @deny="note => resolveApproval(entry, 'deny', note)"
        />

        <!-- In-thread clarify card: pending agent questions render as a form -->
        <ClarifyCard
          v-if="pendingClarify"
          :request="pendingClarify"
          :submitted="clarifySubmitted"
          :busy="clarifyBusy"
          :error="clarifyError"
          @submit="submitClarify"
          @dismiss="dismissClarify"
        />
      </div>
    </div>

    <PendingQueue
      :items="pendingQueue"
      :max-pending="maxPending"
      :mode="isStreaming ? busySendMode : null"
      @clear="clearPendingQueue"
      @remove="removePendingChip"
    />

    <!-- Compaction maintenance card -->
    <div v-if="compactStatus.visible" class="chat-compact-status" :class="`chat-compact-status--${compactStatus.tone}`" role="status" aria-live="polite">
      <div class="chat-compact-status__head">
        <span class="chat-compact-status__dot" :class="{ 'chat-compact-status__dot--pulsing': compactStatus.isBusy }" aria-hidden="true" />
        <span class="chat-compact-status__title">{{ compactStatus.message }}</span>
        <span v-if="compactElapsed" class="chat-compact-status__elapsed">{{ compactElapsed }}</span>
      </div>
      <p v-if="compactStatus.detail" class="chat-compact-status__detail">{{ compactStatus.detail }}</p>
      <div v-if="compactGaugeVisible" class="chat-compact-status__gauge" aria-hidden="true">
        <span
          class="chat-compact-status__gauge-fill"
          :class="{
            'chat-compact-status__gauge-fill--breathing': compactStatus.isBusy,
            'chat-compact-status__gauge-fill--done': compactStatus.status === 'completed',
          }"
          :style="compactStatus.occupancyPercent !== null ? { width: `${compactStatus.occupancyPercent}%` } : undefined"
        />
      </div>
      <div v-if="compactGaugeVisible && compactStatus.occupancyPercent !== null" class="chat-compact-status__legend">
        <span>context {{ compactStatus.occupancyPercent }}%</span>
        <span v-if="compactStatus.contextWindowLabel">{{ compactStatus.contextWindowLabel }}</span>
      </div>
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
      :busy-send-mode="busySendMode"
      :has-send-content="hasSendContent"
      :is-streaming="isStreaming"
      :is-new-landing="isNewChatLanding"
      :placeholder="composerPlaceholder"
      :send-button-title="sendButtonTitle"
      :elevated-mode="elevatedMode"
      :elevated-unavailable="elevatedUnavailable"
      :router-enabled="routerEnabled"
      :router-visual-effects-enabled="routerVisualEffectsEnabled"
      :router-settings-busy="routerSettingsBusy"
      :voice-busy="voiceBusy"
      :voice-recording="voiceRecording"
      @composition-change="composing = $event"
      @file-change="onFileInputChange"
      @input="onTextareaInput"
      @keydown="onTextareaKeydown"
      @remove-attachment="removeAttachment"
      @set-busy-send-mode="busySendMode = $event"
      @set-elevated-mode="setComposerElevatedMode"
      @set-router-enabled="setComposerRouterEnabled"
      @set-visual-effects-enabled="setComposerVisualEffectsEnabled"
      @voice-input="onVoiceInput"
      @export-markdown="exportMarkdown"
      @send="onSend"
      @stop="onStop"
    />

    <ToolResultModal
      :open="toolResultModal.open"
      :title="toolResultModal.title"
      :content="toolResultModal.content"
      @close="toolResultModal.open = false"
    />

    <DeliverablesDrawer
      :open="deliverablesOpen"
      :artifacts="sessionArtifacts"
      :session-key="sessionKey"
      :auth-token="readAuthToken()"
      @close="deliverablesOpen = false"
      @download="downloadArtifact"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import { useAppStore } from '@/stores/app'
import ApprovalCard from '@/components/chat/ApprovalCard.vue'
import ChatArtifactList from '@/components/chat/ChatArtifactList.vue'
import DeliverablesDrawer from '@/components/chat/DeliverablesDrawer.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import ChatHistoryScopeRow from '@/components/chat/ChatHistoryScopeRow.vue'
import ChatMessageList from '@/components/chat/ChatMessageList.vue'
import ClarifyCard from '@/components/chat/ClarifyCard.vue'
import EmptyStateChips from '@/components/chat/EmptyStateChips.vue'
import PendingQueue from '@/components/chat/PendingQueue.vue'
import RouterFxStrip from '@/components/chat/RouterFxStrip.vue'
import ToolCallTimeline from '@/components/chat/ToolCallTimeline.vue'
import ToolResultModal from '@/components/chat/ToolResultModal.vue'
import Icon from '@/components/Icon.vue'
import { useChatApprovals } from '@/composables/chat/useChatApprovals'
import { useChatAttachments } from '@/composables/chat/useChatAttachments'
import { useChatCompaction } from '@/composables/chat/useChatCompaction'
import { useChatComposerShortcuts } from '@/composables/chat/useChatComposerShortcuts'
import { useChatElevatedMode } from '@/composables/chat/useChatElevatedMode'
import { useChatFeatureToggles } from '@/composables/chat/useChatFeatureToggles'
import { useChatHistory } from '@/composables/chat/useChatHistory'
import { useChatMarkdownExport } from '@/composables/chat/useChatMarkdownExport'
import { useChatMessageActions } from '@/composables/chat/useChatMessageActions'
import { useChatPendingQueue } from '@/composables/chat/useChatPendingQueue'
import { useChatShareExport } from '@/composables/chat/useChatShareExport'
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
import { useVoiceInput } from '@/composables/chat/useVoiceInput'
import { useDocumentEvent } from '@/composables/useDocumentEvent'
import { useToasts } from '@/composables/useToasts'
import type {
  ChatMessage,
  ChatRenderedMessage,
  ChatRunStatus,
  ChatRunStatusSource,
  ChatRunStatusState,
} from '@/types/chat'
import type {
  ArtifactPayload,
} from '@/types/rpc'
import { artifactDownloadUrl } from '@/utils/chat/artifacts'
import { copyTextWithFallback, downloadBlob } from '@/utils/browser'
import { useCopyFeedback } from '@/composables/chat/useCopyFeedback'
import {
  toolCallGroups,
  toolGroupStatusText,
  toolSecondaryText,
  toolStatusText,
} from '@/utils/chat/toolDisplay'
import { isShareableChatMessage } from '@/utils/chat/messageIdentity'
import { agentIdFromSessionKey } from '@/utils/chat/sessionKeys'

/* ── Types ─────────────────────────────────────────────────────────── */

interface ChatComposerHandle {
  composerElement: () => HTMLElement | null
  focusTextarea: () => void
  isTextareaFocused: () => boolean
  resizeTextarea: () => void
}

type Message = ChatMessage

/* ── Constants ─────────────────────────────────────────────────────── */

const CHAT_RUN_STATUS_VALUES: ChatRunStatusState[] = [
  'queued',
  'running',
  'approval_pending',
  'interrupted',
  'failed',
  'timeout',
  'cancelled',
]

const toolResultModal = ref({ open: false, title: '', content: '' })

/* ── Stores / Router ───────────────────────────────────────────────── */

const rpc = useRpcStore()
const appStore = useAppStore()
const router = useRouter()
const { pushToast } = useToasts()
const isCompactViewport = useMediaQuery('(max-width: 480px)')
const isDesktopViewport = useMediaQuery('(min-width: 769px)')
const landingAgentId = computed(() => agentIdFromSessionKey(sessionKey.value))
// True when the current draft opened with prefilled composer text (Sessions
// Hub task input); the landing suggestion chips stay out of the way then.
const landingPrefilled = ref(false)

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
const shareMode = ref(false)
const shareSaving = ref(false)
const selectedShareMessageIds = ref<Set<string>>(new Set())
const shareBannerRef = ref<HTMLElement | null>(null)
const shareEntryBtnRef = ref<HTMLButtonElement | null>(null)

const chatElevatedMode = useChatElevatedMode({
  sessionKey,
})
const {
  elevatedMode,
  elevatedUnavailable,
  loadElevatedMode,
  setElevatedMode,
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
  sanitizeCopyText,
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
  streamActivityStale,
  streamPhaseLabel,
  streamPhaseElapsed,
  streamStepLabel,
  streamToolElapsedText,
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
  busySendMode,
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
  compactElapsed,
  setCompactInFlight,
  hideCompactStatus,
  showCompactStatus,
  showCompactionToast,
  cleanup: cleanupCompaction,
} = chatCompaction
isCompactInFlightForCurrentSession = chatCompaction.isCompactInFlightForCurrentSession

// The context gauge stays up while compaction runs and settles on completed;
// skipped/failed/cancelled keep the card head only.
const compactGaugeVisible = computed(() =>
  compactStatus.value.isBusy || compactStatus.value.status === 'completed')

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
  routerEnabled,
  routerVisualEffectsEnabled,
  routerSettingsBusy,
  routerTierConfigs,
  loadFeatureToggles,
  setRouterEnabled,
  setRouterVisualEffectsEnabled,
  bindFeatureRefresh,
} = chatFeatureToggles

const chatSessionRoute = useChatSessionRoute(sessionKey)
const {
  route,
  createSessionKey,
  draftAgentId,
  goToDraft,
  hasLegacyNewChatQuery,
  isDraftRoute,
  persistSession,
  resolveInitialSession,
} = chatSessionRoute

const chatRenderedMessages = useChatRenderedMessages({
  messages,
  sessionKey,
  routerSlots,
  routerModels,
  routerTierConfigs,
  routerVisualEffectsEnabled,
  renderMarkdown,
  stripGeneratedArtifactMarkers,
  stripTimePrefix,
  isSubagentCompletionMessage,
})
const { renderedMessages, routerDecisionCells } = chatRenderedMessages

/**
 * Reserves the AI model router strip's space as soon as a turn starts
 * streaming, so the real strip landing ~1s later (when the router decision
 * push arrives) replaces an equally sized invisible twin instead of pushing
 * the live activity area down (cumulative layout shift).
 */
const routerStripReserve = computed<ChatRenderedMessage | null>(() => {
  if (!isStreaming.value || !routerEnabled.value || !routerVisualEffectsEnabled.value) return null
  const rendered = renderedMessages.value
  for (let i = rendered.length - 1; i >= 0; i--) {
    const msg = rendered[i]
    if (msg.isRouterStrip) return null
    if (msg.displayRole === 'user') break
  }
  const cells = routerDecisionCells({ tier: '', model: '' })
  if (cells.length <= 1) return null
  return {
    id: 'router-strip-reserve',
    role: 'router',
    displayRole: 'router',
    roleLabel: 'Router',
    text: '',
    timeStr: '',
    showHeader: false,
    isRouterStrip: true,
    routerState: 'pending',
    routerSource: 'none',
    routerStatic: true,
    gridCells: cells,
    winnerIdx: -1,
  }
})

const chatShareExport = useChatShareExport({
  threadRef,
  title: shareTitle,
})

const chatHistory = useChatHistory({
  rpc,
  sessionKey,
  messages,
  threadRef,
  lastHeaderRole,
  lastHeaderDay,
  stripTimePrefix,
  scrollToBottom,
})
const {
  historyState,
  loadHistory,
  loadEarlierHistory,
  scheduleHistorySync,
  cleanup: cleanupHistory,
} = chatHistory

const voiceInput = useVoiceInput()
const {
  voiceBusy,
  voiceRecording,
  toggleVoiceInput,
  cleanup: cleanupVoiceInput,
} = voiceInput

const chatMessageActions = useChatMessageActions({
  messages,
  inputText,
  isStreaming,
  sanitizeCopyText,
  stripTimePrefix,
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
  resetStreamLiveTurnState,
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
  resetCurrentSessionAfterSlash,
  startDraftSession,
  switchToSession,
} = chatSessionRuntime

const chatSlashCommands = useChatSlashCommands({
  rpc,
  inputText,
  sessionKey,
  autoResizeTextarea,
  newSession: () => goToDraft({ agentId: agentIdFromSessionKey(sessionKey.value) }),
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
  busySendMode,
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

// Deny notes ride the normal send path: queued while the turn is streaming,
// sent immediately otherwise.
function queueDenyFeedback(note: string) {
  if (isStreaming.value || isCompactInFlightForCurrentSession()) {
    enqueuePendingInput(note)
    return
  }
  const prior = inputText.value
  inputText.value = note
  void onSend()
  if (prior.trim()) {
    inputText.value = prior
    autoResizeTextarea()
  }
}

const chatApprovals = useChatApprovals({
  rpc,
  sessionKey,
  runStatus,
  onDenyFeedback: queueDenyFeedback,
  onSnapshotCount: count => appStore.setApprovalCount(count),
})
const {
  approvalEntries,
  approvalBusyIds,
  pendingClarify,
  clarifySubmitted,
  clarifyBusy,
  clarifyError,
  resolveApproval,
  submitClarify,
  dismissClarify,
} = chatApprovals

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
const {
  streamThinkingText,
  streamThinkingElapsedText,
  attachTurnReasoning,
} = rpcEventHandlers
const chatRpcSubscriptions = useChatRpcSubscriptions(rpc, rpcEventHandlers.handlers)

// History syncs replace the messages array; rows carry reasoning text but
// not the measured thinking duration — re-attach this session's records.
watch(messages, () => attachTurnReasoning())

// Unsubscribers
let unsubs: (() => void)[] = []
let composerResizeObserver: ResizeObserver | null = null

/* ── Computed ──────────────────────────────────────────────────────── */

const runStatusLabel = computed(() => runStatus.value.label)
const runStatusChipClass = computed(() => {
  const cls: Record<string, string> = {
    queued: 'chip-warn', running: 'chip-ok', approval_pending: 'chip-warn', interrupted: 'chip-warn',
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
  if (isNewChatLanding.value) return 'Assign a task or ask anything'
  return isCompactViewport.value ? 'Message...' : 'Send a message...'
})

const hasSendContent = computed(() => {
  return inputText.value.trim().length > 0 || pendingAttachments.value.length > 0
})

const sendButtonTitle = computed(() => {
  if (isCompactInFlightForCurrentSession()) return 'Send (queues until compaction finishes)'
  if (isStreaming.value) {
    return busySendMode.value === 'steer'
      ? 'Send (steers the current response now)'
      : 'Send (queues for after current response)'
  }
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

const chatMarkdownExport = useChatMarkdownExport({
  messages: renderedMessages,
  currentTitle: currentChatTitle,
})
const { exportMarkdown } = chatMarkdownExport

const shareableMessageCount = computed(() => renderedMessages.value.filter(isShareableChatMessage).length)
const selectedShareCount = computed(() => selectedShareMessageIds.value.size)

/* ── Helpers ───────────────────────────────────────────────────────── */

function readAuthToken(): string {
  try {
    return sessionStorage.getItem('opensquilla.wsToken') || ''
  } catch {
    return ''
  }
}

function setComposerElevatedMode(mode: string) {
  setElevatedMode(mode, { persist: true, sync: true })
}

async function setComposerRouterEnabled(enabled: boolean) {
  await setRouterEnabled(enabled)
  scheduleHistorySync()
}

function setComposerVisualEffectsEnabled(enabled: boolean) {
  setRouterVisualEffectsEnabled(enabled)
  scheduleHistorySync()
}

// A landing suggestion chip replaces the draft composer text; the user still
// reviews and sends it themselves.
function applyLandingSuggestion(text: string) {
  inputText.value = text
  autoResizeTextarea()
  composerRef.value?.focusTextarea()
}

function appendComposerText(text: string) {
  const next = String(text || '').trim()
  if (!next) return
  inputText.value = inputText.value.trim()
    ? `${inputText.value.trimEnd()}\n${next}`
    : next
  autoResizeTextarea()
  composerRef.value?.focusTextarea()
}

function onVoiceInput() {
  void toggleVoiceInput(appendComposerText)
}

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
    queued: 'Queued', running: 'Running', approval_pending: 'Approval pending', interrupted: 'Interrupted',
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
  if (active && (activeStatus === 'queued' || activeStatus === 'running' || activeStatus === 'approval_pending')) status = activeStatus
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
  const token = readAuthToken()
  const url = artifactDownloadUrl(artifact, window.location.origin, {
    sessionKey: sessionKey.value,
    includeSessionKey: false,
  })
  if (!url) return
  try {
    const headers: Record<string, string> = {}
    const sameOrigin = new URL(url, window.location.origin).origin === window.location.origin
    if (sameOrigin && sessionKey.value) headers['x-opensquilla-session-key'] = sessionKey.value
    if (sameOrigin && token) headers.Authorization = `Bearer ${token}`
    const response = await fetch(url, {
      method: 'GET',
      headers,
      credentials: sameOrigin ? 'same-origin' : 'omit',
    })
    if (!response.ok) {
      pushToast(`Download failed — HTTP ${response.status}`, { tone: 'danger' })
      return
    }
    const blob = await response.blob()
    downloadBlob(blob, artifact.name || 'artifact')
  } catch (err) {
    console.warn('Download failed:', err)
    pushToast('Download failed', { tone: 'danger' })
  }
}

/**
 * Every deliverable the current session has produced, deduped by identity.
 * Artifacts arrive on completed/replayed assistant turns (`message.artifacts`,
 * filled from chat.history and from the streamed turn that just ended) and on
 * the in-flight turn (`streamArtifacts`); both feed the per-session drawer.
 */
const sessionArtifacts = computed<ArtifactPayload[]>(() => {
  const seen = new Set<string>()
  const collected: ArtifactPayload[] = []
  const consider = (artifact: ArtifactPayload | undefined | null) => {
    if (!artifact) return
    const id = String(artifact.id || artifact.download_url || artifact.name || '')
    if (!id || seen.has(id)) return
    seen.add(id)
    collected.push(artifact)
  }
  for (const message of messages.value) {
    message.artifacts?.forEach(consider)
  }
  streamArtifacts.value.forEach(consider)
  return collected
})

const deliverablesOpen = ref(false)

function openDeliverables() {
  if (sessionArtifacts.value.length === 0) return
  deliverablesOpen.value = true
}

/* ── Fork ──────────────────────────────────────────────────────────── */

// Whole-conversation fork from the tip: the backend copies the transcript
// into a sibling session, then we navigate there the same way the session
// switcher does (route query change → switchToSession).
const forkInFlight = ref(false)

async function forkConversation() {
  const parentKey = sessionKey.value
  if (!parentKey || forkInFlight.value) return
  if (pendingSessionIntent.value === 'new_chat') return
  forkInFlight.value = true
  try {
    const res = await rpc.call<{ key?: string }>('sessions.fork', { key: parentKey })
    const childKey = typeof res?.key === 'string' ? res.key : ''
    if (!childKey) throw new Error('sessions.fork returned no key')
    router.push({ path: '/chat', query: { session: childKey } }).catch(() => {})
  } catch (err) {
    console.warn('Fork failed:', err)
    pushToast('Fork failed', { tone: 'danger' })
  } finally {
    forkInFlight.value = false
  }
}

const {
  copyState: sessionCopyState,
  copyIconName: sessionCopyIcon,
  copyLiveText: sessionCopyLiveText,
  onCopyClick: onSessionCopyClick,
} = useCopyFeedback(async () => {
  if (!sessionKey.value) return false
  try {
    await copyTextWithFallback(sessionKey.value)
    return true
  } catch {
    pushToast('Copy failed', { tone: 'danger' })
    return false
  }
})

/* ── Share export ──────────────────────────────────────────────────── */

function startShareMode() {
  if (shareableMessageCount.value === 0) return
  shareMode.value = true
  selectedShareMessageIds.value = new Set()
  nextTick(() => shareBannerRef.value?.focus())
}

function endShareMode() {
  // Exiting tears down the banner and the bubble pickers; if focus was inside
  // ANY of that mode UI it would drop to <body>, so return it to the entry
  // button in every case.
  const active = document.activeElement
  const modeUiHadFocus = !!shareBannerRef.value?.contains(active)
    || !!(active instanceof HTMLElement
      && active.closest('[data-share-control], .msg-user--share-mode, .msg-ai--share-mode'))
  shareMode.value = false
  selectedShareMessageIds.value = new Set()
  if (modeUiHadFocus) nextTick(() => shareEntryBtnRef.value?.focus())
}

function toggleShareMessage(messageId: string) {
  const next = new Set(selectedShareMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  selectedShareMessageIds.value = next
}

async function saveShareImage() {
  if (selectedShareMessageIds.value.size === 0 || shareSaving.value) return
  shareSaving.value = true
  try {
    await nextTick()
    const savedName = await chatShareExport.exportSelectedMessages(selectedShareMessageIds.value)
    endShareMode()
    if (savedName) pushToast(`Saved ${savedName}`, { duration: 4000 })
  } catch (err) {
    console.warn('Share image export failed:', err)
    pushToast('Share export failed', { tone: 'danger' })
  } finally {
    shareSaving.value = false
  }
}

// The export composable owns all filename composition and slugging (it is
// CJK-aware). Hand it the raw human title and nothing else — pre-mangling here
// (e.g. stripping non-ASCII) would erase Chinese titles before the slugger sees
// them, and pre-composing a filename only forced the composable to take it back
// apart.
function shareTitle(): string {
  return currentChatTitle.value
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
  let attachedImage = false
  for (let i = 0; i < items.length; i++) {
    if (items[i].type.startsWith('image/')) {
      const file = items[i].getAsFile()
      if (file) {
        addAttachment(file)
        attachedImage = true
      }
    }
  }
  // Screenshot tools put both the image and its local file path on the
  // clipboard; once we have attached the image, suppress the default paste so
  // the path text is not also dumped into the composer (and then sent to the
  // agent). Plain-text pastes with no image fall through unchanged.
  if (attachedImage) e.preventDefault()
}

/* ── Document keydown (ESC) ────────────────────────────────────────── */

function onDocumentKeydown(e: KeyboardEvent) {
  if (e.key !== 'Escape') return
  if (e.defaultPrevented) return

  if (shareMode.value) {
    e.preventDefault()
    endShareMode()
    return
  }

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

// One-shot composer prefill carried in history state (the Sessions Hub task
// input navigates here with it). Consumed on draft entry so reload or
// back/forward does not re-apply the text.
function consumeDraftPrefill() {
  const state = window.history.state as Record<string, unknown> | null
  const prefill = typeof state?.prefill === 'string' ? state.prefill : ''
  if (!prefill) return
  inputText.value = prefill
  landingPrefilled.value = true
  try {
    window.history.replaceState({ ...window.history.state, prefill: undefined }, '')
  } catch { /* ignore */ }
}

// Reset to a clean draft for the agent requested by the draft route. The
// provisional key stays out of the URL and storage until the first send.
function enterDraft() {
  landingPrefilled.value = false
  const agentId = draftAgentId()
  const isFreshDraft = pendingSessionIntent.value === 'new_chat'
    && messages.value.length === 0
    && !isStreaming.value
    && agentIdFromSessionKey(sessionKey.value) === agentId
  if (!isFreshDraft) startDraftSession(agentId)
  consumeDraftPrefill()
  if (isDesktopViewport.value) composerRef.value?.focusTextarea()
}

onMounted(async () => {
  // Initialize session key. Without an explicit ?session= the view opens as a
  // draft instead of restoring a previous session.
  const initialSession = resolveInitialSession()
  sessionKey.value = initialSession.sessionKey
  if (initialSession.draft) {
    pendingSessionIntent.value = 'new_chat'
    if (!isDraftRoute() || hasLegacyNewChatQuery()) goToDraft({ replace: true })
    consumeDraftPrefill()
  } else {
    persistSession(sessionKey.value, { updateRoute: false })
  }

  // Load elevated mode
  loadElevatedMode()

  // Load feature toggles
  await loadFeatureToggles()
  unsubs.push(bindFeatureRefresh(scheduleHistorySync))

  // Subscribe to RPC events
  unsubs.push(chatRpcSubscriptions.subscribe())
  unsubs.push(chatApprovals.subscribe())

  // Composer resize observer
  const composerEl = composerRef.value?.composerElement()
  if (composerEl) {
    composerResizeObserver = new ResizeObserver(() => {
      const h = composerRef.value?.composerElement()?.getBoundingClientRect().height || 0
      document.documentElement.style.setProperty('--composer-h', h + 'px')
    })
    composerResizeObserver.observe(composerEl)
  }

  // Load the requested chat state. Drafts subscribe so the first send can
  // stream, but have no history to load.
  subscribeSession()
  if (!initialSession.draft) loadHistory()
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
  cleanupVoiceInput()
  chatApprovals.cleanup()
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

// Entering the draft route resets to a clean draft for the requested agent.
watch(() => [route.path, route.query.agent], () => {
  if (isDraftRoute()) enterDraft()
})

// Legacy ?newChat=1 / ?new=1 links land on the draft route, then the params disappear.
watch(() => [route.query.newChat, route.query.new], () => {
  if (hasLegacyNewChatQuery()) goToDraft({ replace: true })
})

// A draft materializes its session key in the URL only when the first message
// actually goes out.
watch(pendingSessionIntent, (intent, previous) => {
  if (previous !== 'new_chat' || intent !== null) return
  if (!isDraftRoute()) return
  persistSession(sessionKey.value)
})

watch(sessionKey, () => {
  if (shareMode.value) endShareMode()
  deliverablesOpen.value = false
})

watch(shareableMessageCount, (count) => {
  if (count === 0 && shareMode.value) endShareMode()
})
</script>

<style scoped src="../styles/chat-view.css"></style>

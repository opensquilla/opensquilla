<template>
  <div
    class="chat"
    :class="{ 'chat--new-landing': isNewChatLanding, 'chat--drag-over': threadDragOver }"
    @dragenter="onChatDragEnter"
    @dragover="onChatDragOver"
    @dragleave="onChatDragLeave"
    @drop="onChatDrop"
  >
    <div v-if="threadDragOver" class="chat-drop-overlay" role="status" aria-live="polite" aria-atomic="true">
      <div class="chat-drop-overlay__frame" aria-hidden="true"></div>
      <div class="chat-drop-overlay__beacon">
        <span class="chat-drop-overlay__glyph" aria-hidden="true">
          <Icon name="fileText" :size="30" />
          <Icon class="chat-drop-overlay__plus" name="plus" :size="12" />
        </span>
        <span class="chat-drop-overlay__copy">
          <span class="chat-drop-overlay__title">{{ t('chat.dropOverlayTitle') }}</span>
          <span class="chat-drop-overlay__hint">{{ t('chat.dropOverlayHint') }}</span>
        </span>
      </div>
    </div>

    <!-- Header -->
    <div v-if="!isNewChatLanding" class="chat-header">
      <div class="chat-header-left">
        <label class="chat-label" :title="sessionKey">{{ currentChatTitle }}</label>
        <button
          class="chat-session-copy-btn"
          :class="{ 'chat-session-copy-btn--ok': sessionCopyState === 'ok' }"
          :title="sessionCopyState === 'ok' ? t('chat.copied') : t('chat.copySessionKey')"
          :aria-label="sessionCopyState === 'ok' ? t('chat.copied') : t('chat.copySessionKey')"
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
          :title="t('chat.deliverablesCount', { count: sessionArtifacts.length })"
          :aria-label="t('chat.deliverablesCount', { count: sessionArtifacts.length })"
          @click="openDeliverables"
        >
          <Icon name="download" :size="14" />
          <span class="chat-share-btn__label">{{ t('chat.deliverablesCount', { count: sessionArtifacts.length }) }}</span>
        </button>
        <button
          v-if="appStore.features.metaRuns"
          type="button"
          class="chat-share-btn"
          :title="t('chat.metaRunHistory')"
          :aria-label="t('chat.metaRunHistory')"
          @click="metaRunsHistoryOpen = true"
        >
          <Icon name="clock" :size="14" />
          <span class="chat-share-btn__label">{{ t('chat.runs') }}</span>
        </button>
        <button
          v-if="!shareMode"
          ref="shareEntryBtnRef"
          type="button"
          class="chat-share-btn"
          :disabled="shareableMessageCount === 0"
          :title="shareableMessageCount === 0 ? t('chat.shareSendFirst') : t('chat.shareSelectHint')"
          :aria-label="shareableMessageCount === 0 ? t('chat.shareSendFirst') : t('chat.share')"
          @click="startShareMode"
        >
          <Icon name="share" :size="14" />
          <span class="chat-share-btn__label">{{ t('chat.share') }}</span>
        </button>
        <span class="chat-chip" :class="runStatusChipClass" :title="runStatusTitle">{{ runStatusLabel }}</span>
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
        :aria-label="t('chat.shareSelectedMessages')"
        data-testid="share-banner"
      >
        <span class="chat-share-banner__hint">{{ t('chat.shareBannerHint') }}</span>
        <span class="chat-share-banner__count" role="status" aria-live="polite">{{ t('chat.shareSelectedCount', { count: selectedShareCount }) }}</span>
        <button
          type="button"
          class="chat-share-btn chat-share-btn--save"
          :disabled="selectedShareCount === 0 || shareSaving"
          :title="selectedShareCount === 0 ? t('chat.shareSelectAtLeastOne') : t('chat.shareSavePngHint')"
          @click="saveShareImage"
        >
          <Icon name="download" :size="14" />
          <span>{{ shareSaving ? t('chat.saving') : t('chat.savePng') }}</span>
        </button>
        <button type="button" class="chat-share-btn" :title="t('chat.shareCancelHint')" @click="endShareMode">
          {{ t('common.cancel') }}
        </button>
      </div>
      <div
        ref="threadRef"
        class="chat-thread"
        role="region"
        :aria-label="t('chat.conversation')"
        :aria-busy="isStreaming"
        @scroll="onThreadScroll"
      >
        <template v-if="isNewChatLanding">
          <div ref="agentSwitcherRef" class="chat-landing-agent">
            <button
              type="button"
              class="chat-landing-agent__btn"
              aria-haspopup="menu"
              :aria-expanded="agentSwitcherOpen"
              :title="t('chat.agentLabel', { name: landingAgentName })"
              @click.stop="toggleAgentSwitcher"
            >
              <Icon name="agents" :size="14" />
              <span class="chat-landing-agent__name">{{ landingAgentName }}</span>
              <Icon class="chat-landing-agent__chevron" name="chevronDown" :size="13" />
            </button>
            <div
              v-if="agentSwitcherOpen"
              class="chat-landing-agent__menu"
              role="menu"
              :aria-label="t('chat.chooseAgent')"
              @keydown="onAgentSwitcherKeydown"
            >
              <button
                v-for="agent in selectableAgents"
                :key="agent.id"
                type="button"
                class="chat-landing-agent__item"
                role="menuitemradio"
                :aria-checked="agent.id === landingAgentId"
                @click.stop="pickDraftAgent(agent.id)"
              >
                <span class="chat-landing-agent__item-name">{{ agent.name }}</span>
                <Icon
                  v-if="agent.id === landingAgentId"
                  class="chat-landing-agent__check"
                  name="check"
                  :size="14"
                />
              </button>
              <button
                type="button"
                class="chat-landing-agent__item chat-landing-agent__item--create"
                role="menuitem"
                @click.stop="createAgentFromSwitcher"
              >
                <Icon name="plus" :size="14" />
                <span>{{ t('chat.createAgent') }}</span>
              </button>
            </div>
          </div>
          <div class="chat-landing-brand" :aria-label="t('chat.newChatBrand')">
            <EmptyStateChips
              :key="landingAgentId"
              :agent-id="landingAgentId"
              :suppressed="landingPrefilled"
              @pick="applyLandingSuggestion"
            />
          </div>
        </template>
        <div v-else-if="messages.length === 0 && !isStreaming" class="chat-empty">{{ t('chat.noMessagesYet') }}</div>
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
          @resolve-interrupt="resolveInterrupt"
          @extend-interrupt="extendInterrupt"
          @clarify-submit="submitClarify"
          @clarify-dismiss="dismissClarify"
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

        <!-- MetaSkill run cards: preflight checkpoint + progress ribbon,
             grouped per run_id above the live activity area. -->
        <template v-for="runId in metaRuns.ribbonOrder.value" :key="`meta-${runId}`">
          <MetaPreflightCard
            v-if="metaRuns.preflights.value.has(runId)"
            :state="metaRuns.preflights.value.get(runId)!.state"
            :phase="metaRuns.preflights.value.get(runId)!.phase"
            :error-text="metaRuns.preflights.value.get(runId)!.errorText"
            @action="metaRuns.onPreflightAction"
          />
          <MetaRibbon
            v-if="metaRuns.ribbons.value.has(runId)"
            :run="metaRuns.ribbons.value.get(runId)!"
            @action="metaRuns.onRibbonAction"
            @chip-select="metaRuns.onChipSelect"
          />
        </template>

        <!-- Streaming AI message: the live run is promoted into a centered
             work card so it owns the focus while the agent works. -->
        <div v-if="isStreaming && streamBubble && answerRevealOpen" class="msg-ai" data-history-role="assistant" aria-live="polite">
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
              <details v-if="liveThinkingText" class="thinking-fold">
                <summary class="thinking-fold__summary">
                  <Icon class="thinking-fold__chevron" name="chevronRight" :size="12" />
                  <span>{{ t('chat.thinking') }} · {{ streamThinkingElapsedText }}</span>
                </summary>
                <div class="thinking-fold__body">{{ liveThinkingText }}</div>
              </details>

              <ToolCallTimeline
                v-if="liveTimelineItems.length"
                class="work-card__timeline"
                variant="checklist"
                :items="liveTimelineItems"
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

              <!-- Live typing caret: a blinking "still generating" affordance at
                   the tail of the streamed output. Only once real output exists
                   (never a lone bar under the header), and hidden when stale. -->
              <span v-if="!streamActivityStale && streamHasVisibleOutput" class="stream-caret" aria-hidden="true" />
            </section>

            <!-- Live inline interrupts (fold-driven): approval / clarify cards
                 that block the in-flight turn, rendered after the work-card body
                 and before the deliverables. -->
            <InterruptPart
              v-for="part in liveInterruptParts"
              :key="part.key"
              :part="part"
              @resolve="resolveInterrupt"
              @extend="extendInterrupt"
              @clarify-submit="(fields, request) => submitClarify(fields, request)"
              @clarify-dismiss="dismissClarify"
            />

            <ChatArtifactList
              :artifacts="liveArtifacts"
              :session-key="sessionKey"
              :auth-token="readAuthToken()"
              @download="downloadArtifact"
            />

          </div>
        </div>

        <!-- Thinking indicator -->
        <div v-if="thinkingVisible && answerRevealOpen" class="msg-ai thinking" role="status" aria-live="polite">
          <div class="msg-ai-main">
            <div class="thinking-status">
              <span class="stream-activity-dot" aria-hidden="true" />
              <span class="thinking-elapsed activity-shimmer" aria-live="off">{{ thinkingText }}</span>
            </div>
          </div>
        </div>

        <!-- Legacy standalone approval / clarify block. The interrupt parts now
             carry these through the fold (InterruptPart over the same cards), so
             this side-list only renders on the foldLiveTurn=0 rollback branch —
             the one-flag kill switch — to avoid a double-render. Kept for one
             release as the rollback lever, mirroring the foldLiveTurn discipline. -->
        <template v-if="foldLiveTurnMode === false">
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
            @extend="extendInterrupt(entry.approval.id)"
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
        </template>
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

    <!-- Composer dock: positioning context so the slash menu anchors directly
         above the composer in any layout. The new-chat landing centers the
         composer instead of pinning it to the bottom, so the menu must not
         anchor to the chat container's bottom edge. -->
    <div class="chat-composer-dock">
    <!-- Jump-to-latest: floats above the composer once the reader has scrolled up
         off the live edge, so a long streaming answer is never lost below the fold. -->
    <Transition name="jump-latest">
      <button
        v-if="showJumpToLatest"
        type="button"
        class="chat-jump-latest"
        :aria-label="t('chat.jumpToLatest')"
        :title="t('chat.jumpToLatest')"
        @click="jumpToLatest"
      >
        <Icon name="chevronRight" :size="14" class="chat-jump-latest__icon" />
        <span>{{ t('chat.latest') }}</span>
      </button>
    </Transition>
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
      :coding-mode-enabled="codingModeEnabled"
      :coding-mode-settings-busy="codingModeSettingsBusy"
      :voice-busy="voiceBusy"
      :voice-recording="voiceRecording"
      @composition-change="composing = $event"
      @beforeinput="onTextareaBeforeInput"
      @file-change="onFileInputChange"
      @input="onTextareaInput"
      @keydown="onTextareaKeydown"
      @remove-attachment="removeAttachment"
      @retry-attachment="retryAttachment"
      @set-busy-send-mode="busySendMode = $event"
      @set-elevated-mode="setComposerElevatedMode"
      @set-router-enabled="setComposerRouterEnabled"
      @set-visual-effects-enabled="setComposerVisualEffectsEnabled"
      @set-coding-mode-enabled="setComposerCodingModeEnabled"
      @voice-input="onVoiceInput"
      @export-markdown="exportMarkdown"
      @send="onSend"
      @stop="onStop"
    />
    </div>

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

    <MetaRunHistoryDrawer
      v-if="appStore.features.metaRuns"
      :open="metaRunsHistoryOpen"
      :rpc="rpc"
      :session-key="sessionKey"
      @close="metaRunsHistoryOpen = false"
    />

    <SharePreviewModal
      :open="!!sharePreview"
      :image-url="sharePreview?.url || ''"
      :filename="sharePreview?.filename || ''"
      :theme="shareTheme"
      :copy-supported="copySupported"
      :busy="shareSaving"
      @close="closeSharePreview"
      @download="onShareDownload"
      @copy="onShareCopy"
      @set-theme="onShareSetTheme"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch, watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'
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
import InterruptPart from '@/components/chat/parts/InterruptPart.vue'
import MetaPreflightCard from '@/components/chat/MetaPreflightCard.vue'
import MetaRibbon from '@/components/chat/MetaRibbon.vue'
import MetaRunHistoryDrawer from '@/components/chat/MetaRunHistoryDrawer.vue'
import PendingQueue from '@/components/chat/PendingQueue.vue'
import RouterFxStrip from '@/components/chat/RouterFxStrip.vue'
import SharePreviewModal from '@/components/chat/SharePreviewModal.vue'
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
import type { ShareExportTheme } from '@/composables/chat/useChatShareExport'
import { useMediaQuery } from '@/composables/chat/useMediaQuery'
import {
  fmtTok,
  truncate,
  useChatRenderedMessages,
} from '@/composables/chat/useChatRenderedMessages'
import { useChatRouterDecisionRuntime } from '@/composables/chat/useChatRouterDecisionRuntime'
import { useChatAnswerReveal } from '@/composables/chat/useChatAnswerReveal'
import { useChatRpcEventHandlers } from '@/composables/chat/useChatRpcEventHandlers'
import { useChatRpcSubscriptions } from '@/composables/chat/useChatRpcSubscriptions'
import { useChatSend } from '@/composables/chat/useChatSend'
import { useMetaRuns } from '@/composables/chat/useMetaRuns'
import { useAgentOptions } from '@/composables/useAgentOptions'
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
import type { InterruptViewState } from '@/types/parts'
import { artifactDownloadUrl } from '@/utils/chat/artifacts'
import { copyTextWithFallback, copyImageToClipboard, downloadBlob, shareCopyImageSupported } from '@/utils/browser'
import { useCopyFeedback } from '@/composables/chat/useCopyFeedback'
import { recordSessionNavigationDiag } from '@/utils/chat/sessionNavigationDiag'
import {
  toolCallGroups,
  toolGroupStatusText,
  toolSecondaryText,
  toolStatusText,
} from '@/utils/chat/toolDisplay'
import { isSendableAttachment } from '@/utils/chat/attachments'
import { isShareableChatMessage } from '@/utils/chat/messageIdentity'
import { agentIdFromSessionKey, normalizeAgentId } from '@/utils/chat/sessionKeys'

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
const { t } = useI18n()
const { pushToast } = useToasts()
const isCompactViewport = useMediaQuery('(max-width: 480px)')
const isDesktopViewport = useMediaQuery('(min-width: 769px)')
const landingAgentId = computed(() => agentIdFromSessionKey(sessionKey.value))
// True when the current draft opened with prefilled composer text (Sessions
// Hub task input); the landing suggestion chips stay out of the way then.
const landingPrefilled = ref(false)
// Holds the prefill text when the Sessions Hub hand-off requested a one-step
// send ("Start task"). Flushed in onMounted once the draft subscription is live
// so the first turn streams into this view. Empty string = nothing pending.
const pendingAutoSend = ref('')

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
const threadDragDepth = ref(0)
const shareMode = ref(false)
const shareSaving = ref(false)
const selectedShareMessageIds = ref<Set<string>>(new Set())
const shareBannerRef = ref<HTMLElement | null>(null)
const shareEntryBtnRef = ref<HTMLButtonElement | null>(null)
// Preview-before-download: Save renders the PNG to a blob and opens the modal
// instead of downloading blind. The view owns the object-URL lifecycle.
const sharePreview = ref<{ url: string; blob: Blob; filename: string } | null>(null)
const shareTheme = ref<ShareExportTheme>('light')
// Whether the browser can copy an image to the clipboard. Resolved once: the
// capability does not change within a session, and the modal hides Copy when false.
const copySupported = shareCopyImageSupported()

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
const runStatus = ref<ChatRunStatus>({ status: 'idle', label: t('chat.status.idle'), task: null })

// Epoch / seq
const currentEpoch = ref(0)
const lastStreamSeq = ref(0)
const activeTaskGroups = ref<Set<string>>(new Set())
// Task id whose output the live stream renders; binds late events to the
// current turn so a prior task can't leak into it (issue 344).
const activeStreamTaskId = ref<string>('')

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

// Resolution side-map for inline interrupt parts, owned here so it can be shared
// between the stream (which threads it into the turn-log fold) and the approvals
// composable (its sole writer). Constructed before the stream because the stream
// reads it at build time; the approvals composable, built later, drives it.
const interruptState = ref<ReadonlyMap<string, InterruptViewState>>(new Map())

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
  interruptState,
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
  assertLiveParity,
  useReducer: foldLiveTurnMode,
  foldedTurn,
  appendInterruptFrame,
  ensureInterruptBubble,
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
  addAttachments,
  removeAttachment,
  retryAttachment,
  hasPendingAttachmentWork,
} = chatAttachments

let sendCurrentInput: () => void = () => {}
// Late-bound: dispatchHiddenSend is created below (useChatSend) but the /meta
// slash handler (useChatSlashCommands, created earlier) needs it at call time.
let dispatchHiddenForMeta: (providerText: string, displayText: string) => void = () => {}
let isCompactInFlightForCurrentSession: () => boolean = () => false
let dispatchHiddenControl: (providerText: string, displayText: string) => void = () => {}
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
  dispatchHiddenControl: (providerText, displayText) => dispatchHiddenControl(providerText, displayText),
})
const {
  pendingQueue,
  canQueueMore,
  busySendMode,
  maxPending,
  enqueuePendingInput,
  enqueueHiddenControl,
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
  routerVisualMode,
  routerSettingsBusy,
  codingModeEnabled,
  codingModeSettingsBusy,
  routerTierConfigs,
  loadFeatureToggles,
  setRouterEnabled,
  setCodingModeEnabled,
  setRouterVisualEffectsEnabled,
  bindFeatureRefresh,
} = chatFeatureToggles

// Gate the live answer's reveal to a [MIN,MAX] window so the model-router panel
// decides (and animates) first, then the answer follows. Self-cleans via the
// composable's onScopeDispose.
const { answerRevealOpen, revealNow } = useChatAnswerReveal({
  isStreaming,
  routerEnabled,
  routerVisualEffectsEnabled,
  routerDecided: () => pendingDecision.value,
})

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

// In-draft agent switcher (new-chat landing): lets the user swap the draft's
// agent before the first message. Shares one agents.list path with the sidebar.
const { selectableAgents, loadAgents: loadAgentOptions } = useAgentOptions()
const agentSwitcherOpen = ref(false)
const agentSwitcherRef = ref<HTMLElement | null>(null)

const landingAgentName = computed(() => {
  const id = landingAgentId.value
  const match = selectableAgents.value.find(agent => agent.id === id)
  return match?.name || (id === 'main' ? t('chat.mainAgent') : id)
})

function toggleAgentSwitcher() {
  agentSwitcherOpen.value = !agentSwitcherOpen.value
  if (agentSwitcherOpen.value && selectableAgents.value.length <= 1) {
    void loadAgentOptions()
  }
  if (agentSwitcherOpen.value) {
    // Land focus on the checked agent if present, else the first item, so the
    // menu is keyboard-operable the moment it opens.
    nextTick(() => {
      const menu = agentSwitcherRef.value?.querySelector('.chat-landing-agent__menu')
      const items = menu?.querySelectorAll<HTMLElement>('.chat-landing-agent__item')
      if (!items?.length) return
      const checked = menu?.querySelector<HTMLElement>('[aria-checked="true"]')
      ;(checked ?? items[0]).focus()
    })
  }
}

function closeAgentSwitcher() {
  agentSwitcherOpen.value = false
}

// Arrow keys rove between the agent items (including "Create agent…"), wrapping
// at the ends; Escape closes and restores focus to the switcher trigger.
function onAgentSwitcherKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    e.preventDefault()
    closeAgentSwitcher()
    nextTick(() => agentSwitcherRef.value?.querySelector<HTMLElement>('.chat-landing-agent__btn')?.focus())
    return
  }
  // Tab must dismiss the open menu (WAI-ARIA menu pattern) and let focus move on
  // naturally — the outside-click handler does not fire on a keyboard Tab.
  if (e.key === 'Tab') {
    closeAgentSwitcher()
    return
  }
  if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp') return
  const menu = agentSwitcherRef.value?.querySelector('.chat-landing-agent__menu')
  const items = Array.from(menu?.querySelectorAll<HTMLElement>('.chat-landing-agent__item') ?? [])
  if (!items.length) return
  e.preventDefault()
  const current = items.indexOf(document.activeElement as HTMLElement)
  const delta = e.key === 'ArrowDown' ? 1 : -1
  const next = (current + delta + items.length) % items.length
  items[next]?.focus()
}

// Selecting an agent re-enters the draft for it. The draft carries no messages
// yet, so swapping with replace semantics is safe and leaves no history entry.
function pickDraftAgent(agentId: string) {
  closeAgentSwitcher()
  const id = normalizeAgentId(agentId)
  if (id === landingAgentId.value) return
  goToDraft({ agentId: id, replace: true })
}

function createAgentFromSwitcher() {
  closeAgentSwitcher()
  router.push('/agents')
}

useDocumentEvent('click', (e) => {
  if (!agentSwitcherOpen.value) return
  const host = agentSwitcherRef.value
  if (host && e.target instanceof Node && !host.contains(e.target)) closeAgentSwitcher()
})

const chatRenderedMessages = useChatRenderedMessages({
  messages,
  interruptState,
  sessionKey,
  routerSlots,
  routerModels,
  routerTierConfigs,
  routerVisualEffectsEnabled,
  routerVisualMode,
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
    routerStatic: false,
    routerPanel: routerVisualMode.value === 'legacy_grid' ? 'legacy-grid' : 'real-candidates',
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
  notify: (message: string) => pushToast(message, { duration: 6000 }),
  dispatchHidden: (providerText: string, displayText: string) => dispatchHiddenForMeta(providerText, displayText),
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
  onTextareaBeforeInput,
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
  activeStreamTaskId,
  autoScroll,
  stream: chatStream,
  normalizeElevatedMode,
  persistSession,
  isCompactInFlightForCurrentSession,
  hasPendingAttachmentWork,
  enqueuePendingInput,
  enqueueHiddenControl,
  popAllPendingIntoComposer,
  executeSlashCommand,
  closeSlashMenu,
  autoResizeTextarea,
  scrollToBottom,
})
const { onSend, onStop, dispatchHiddenSend, sendHiddenMetaPreflightConfirmation } = chatSend
sendCurrentInput = onSend
dispatchHiddenForMeta = dispatchHiddenSend
dispatchHiddenControl = dispatchHiddenSend

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
  stream: { isStreaming, appendInterruptFrame, ensureInterruptBubble },
  interruptState,
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
  resolveInterrupt,
  extendInterrupt,
  submitClarify,
  dismissClarify,
} = chatApprovals

const rpcEventHandlers = useChatRpcEventHandlers({
  sessionKey,
  currentEpoch,
  lastStreamSeq,
  activeTaskGroups,
  activeStreamTaskId,
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

// live-turn shadow parity: in DEV/SHADOW, re-check the fold against the legacy
// live surface whenever a frame lands (the fold and legacy refs are tracked by
// assertLiveParity). Injects the thinking text owned by the event handlers.
// No-op in prod/OFF; render stays legacy unless the fold is authoritative (ON).
watchEffect(() => assertLiveParity(streamThinkingText))

// flag-selected live render source. Only when the fold is
// authoritative (useReducer === true, opt-in via opensquilla.chat.foldLiveTurn=1)
// does the work-card body render from the fold; OFF and SHADOW return the
// IDENTICAL legacy refs, so with the flag off the render is byte-identical.
// The work-card head (phase/elapsed/step) stays on the legacy activity refs.
const liveTimelineItems = computed(() =>
  foldLiveTurnMode.value === true ? foldedTurn.value.timelineItems : streamTimelineItems.value,
)
const liveArtifacts = computed(() =>
  foldLiveTurnMode.value === true ? foldedTurn.value.artifacts : streamArtifacts.value,
)
const liveThinkingText = computed(() =>
  foldLiveTurnMode.value === true ? foldedTurn.value.thinkingText : streamThinkingText.value,
)
// Inline interrupt parts for the live turn come from the fold whenever it is
// active (ON or SHADOW — frames are appended in both). Only the foldLiveTurn=0
// OFF rollback renders the legacy standalone ApprovalCard/ClarifyCard block, so
// the two never both show. Unlike the work-card body (which has a legacy ref to
// fall back to in SHADOW), interrupts have no legacy live ref, so SHADOW must
// also render them from the fold.
const liveInterruptParts = computed(() =>
  foldLiveTurnMode.value === false
    ? []
    : foldedTurn.value.parts.filter(
        (part): part is Extract<typeof part, { type: 'interrupt' }> => part.type === 'interrupt',
      ),
)

const chatRpcSubscriptions = useChatRpcSubscriptions(rpc, rpcEventHandlers.handlers)

// MetaSkill run UI: preflight checkpoint + run-progress ribbon, driven by the
// four session.event.meta_* frames (delivered via the '*' wildcard, so this
// controller must not re-consume stream_seq).
const metaRuns = useMetaRuns({
  rpc,
  sessionKey,
  currentEpoch,
  lastStreamSeq,
  sendHiddenConfirmation: sendHiddenMetaPreflightConfirmation,
  scrollToStepCard,
  sendComposerText,
  lastUserMessageText,
  // The composer placeholder is a computed prop, so a true placeholder setter
  // is not exposed; surface the switch-skill hint via the toast path (keeping
  // focus) so the vanilla guidance is not silently dropped.
  setComposerPlaceholder: (hint: string) => pushToast(hint, { duration: 6000 }),
  focusComposer: () => composerRef.value?.focusTextarea(),
  pushToast,
})

// Refill the composer with `text` and fire the send path (mirrors vanilla's
// retry/replay tail: `_textarea.value = text; _autoResizeTextarea(); _onSend()`).
function sendComposerText(text: string) {
  const next = String(text || '')
  if (!next) return
  inputText.value = next
  autoResizeTextarea()
  void sendCurrentInput()
}

// The most recent user message text (mirrors vanilla `_latestUserMessageText`).
function lastUserMessageText(): string {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    if (messages.value[i]?.role === 'user') return messages.value[i].text || ''
  }
  return ''
}

// Resolve a step's in-thread tool card and scroll it into view (chip click /
// show-detail). The card carries data-tool-use-id="meta_step_<id>".
function scrollToStepCard(toolUseId: string) {
  const root = threadRef.value
  if (!root) return
  const card = root.querySelector(`[data-tool-use-id="${cssEscapeAttr(toolUseId)}"]`)
  if (card && typeof (card as HTMLElement).scrollIntoView === 'function') {
    const reduceMotion = typeof window !== 'undefined'
      && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    ;(card as HTMLElement).scrollIntoView({ block: 'center', behavior: reduceMotion ? 'auto' : 'smooth' })
  }
}

function cssEscapeAttr(value: string): string {
  if (typeof window !== 'undefined' && window.CSS && typeof window.CSS.escape === 'function') {
    return window.CSS.escape(value)
  }
  return String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '\\$&')
}

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
    queued: 'chat-chip-warn', running: 'chat-chip-ok', approval_pending: 'chat-chip-warn', interrupted: 'chat-chip-warn',
    failed: 'chat-chip-danger', timeout: 'chat-chip-warn',
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
  if (isNewChatLanding.value) return t('chat.placeholderLanding')
  return isCompactViewport.value ? t('chat.placeholderCompact') : t('chat.placeholder')
})

const hasSendContent = computed(() => {
  return inputText.value.trim().length > 0 || pendingAttachments.value.some(isSendableAttachment)
})

const sendButtonTitle = computed(() => {
  if (isCompactInFlightForCurrentSession()) return t('chat.sendQueuesUntilCompaction')
  if (isStreaming.value) {
    return busySendMode.value === 'steer'
      ? t('chat.sendSteers')
      : t('chat.sendQueues')
  }
  return t('chat.send')
})

const currentChatTitle = computed(() => {
  const firstUser = messages.value.find(msg => msg.role === 'user' && stripTimePrefix(msg.text || '').trim())
  if (firstUser) {
    return truncate(stripTimePrefix(firstUser.text).replace(/\s+/g, ' ').trim(), 28)
  }
  const suffix = sessionKey.value.split(':').pop() || ''
  if (!suffix || suffix === 'default') return t('chat.newChat')
  return t('chat.chatWithSuffix', { suffix })
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

async function setComposerCodingModeEnabled(enabled: boolean) {
  await setCodingModeEnabled(enabled)
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
    queued: t('chat.status.queued'),
    running: t('chat.status.running'),
    approval_pending: t('chat.status.approvalPending'),
    interrupted: t('chat.status.interrupted'),
    failed: t('chat.status.failed'),
    timeout: t('chat.status.timeout'),
    cancelled: t('chat.status.cancelled'),
    idle: t('chat.status.idle'),
  }
  return labels[status] || t('chat.status.idle')
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
    return t('chat.subagentPrefix') + (parsed.child_session_key || parsed.session_key || 'completion')
  } catch { return t('chat.subagentCompletion') }
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
      pushToast(t('chat.toast.downloadFailedHttp', { status: response.status }), { tone: 'danger' })
      return
    }
    const blob = await response.blob()
    downloadBlob(blob, artifact.name || 'artifact')
  } catch (err) {
    console.warn('Download failed:', err)
    pushToast(t('chat.toast.downloadFailed'), { tone: 'danger' })
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
const metaRunsHistoryOpen = ref(false)

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
    pushToast(t('chat.toast.forkFailed'), { tone: 'danger' })
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
    pushToast(t('chat.toast.copyFailed'), { tone: 'danger' })
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
  // Leaving share mode invalidates any open preview (the selection it rendered
  // is gone), so drop the modal and its object URL alongside the mode.
  if (sharePreview.value) {
    URL.revokeObjectURL(sharePreview.value.url)
    sharePreview.value = null
  }
  if (modeUiHadFocus) nextTick(() => shareEntryBtnRef.value?.focus())
}

function toggleShareMessage(messageId: string) {
  const next = new Set(selectedShareMessageIds.value)
  if (next.has(messageId)) next.delete(messageId)
  else next.add(messageId)
  selectedShareMessageIds.value = next
}

// Save renders the selected bubbles to a PNG blob and opens the preview modal;
// it no longer downloads directly. Share mode stays active while previewing so
// the user can still adjust the selection after closing the modal — it only
// ends once they commit with Download.
async function saveShareImage() {
  if (selectedShareMessageIds.value.size === 0 || shareSaving.value) return
  shareSaving.value = true
  try {
    await nextTick()
    const result = await chatShareExport.buildShareImage(selectedShareMessageIds.value, {
      theme: shareTheme.value,
    })
    if (!result) {
      pushToast(t('chat.toast.shareExportFailed'), { tone: 'danger' })
      return
    }
    const url = URL.createObjectURL(result.blob)
    sharePreview.value = { url, blob: result.blob, filename: result.filename }
  } catch (err) {
    console.warn('Share image export failed:', err)
    pushToast(t('chat.toast.shareExportFailed'), { tone: 'danger' })
  } finally {
    shareSaving.value = false
  }
}

function onShareDownload() {
  const preview = sharePreview.value
  if (!preview) return
  downloadBlob(preview.blob, preview.filename)
  pushToast(t('chat.toast.saved', { filename: preview.filename }), { duration: 4000 })
  // endShareMode revokes the preview URL and drops the modal, then exits share
  // mode (which remounts the header Share button); focus lands back on it. The
  // modal's Download button held focus, outside the banner, so endShareMode's
  // own conditional restore does not fire — focus the entry button explicitly.
  endShareMode()
  nextTick(() => shareEntryBtnRef.value?.focus())
}

async function onShareCopy() {
  const preview = sharePreview.value
  if (!preview) return
  const ok = await copyImageToClipboard(preview.blob)
  // Approved decision: the modal stays open after a copy so the user can copy
  // again or then download; only Download / Cancel / Escape closes it.
  pushToast(ok ? t('chat.toast.copiedToClipboard') : t('chat.toast.copyNotSupported'), {
    tone: ok ? undefined : 'danger',
  })
}

// Re-render the image in the chosen theme, swapping the object URL in place so
// the modal stays open and shows a busy state during the rebuild.
async function onShareSetTheme(next: ShareExportTheme) {
  if (next === shareTheme.value && sharePreview.value) return
  shareTheme.value = next
  if (!sharePreview.value || shareSaving.value) return
  shareSaving.value = true
  try {
    const result = await chatShareExport.buildShareImage(selectedShareMessageIds.value, { theme: next })
    if (!result) {
      pushToast(t('chat.toast.shareExportFailed'), { tone: 'danger' })
      return
    }
    const previous = sharePreview.value
    sharePreview.value = {
      url: URL.createObjectURL(result.blob),
      blob: result.blob,
      filename: result.filename,
    }
    if (previous) URL.revokeObjectURL(previous.url)
  } catch (err) {
    console.warn('Share image re-render failed:', err)
    pushToast(t('chat.toast.shareExportFailed'), { tone: 'danger' })
  } finally {
    shareSaving.value = false
  }
}

// Close the preview without leaving share mode: revoke the URL and restore
// focus. While share mode is still active the header Share button is unmounted
// (v-if="!shareMode"), so focus returns to the share banner — the mode's anchor
// and where startShareMode put it; only once the mode has ended does the entry
// button exist to receive focus.
function closeSharePreview() {
  const preview = sharePreview.value
  if (preview) URL.revokeObjectURL(preview.url)
  sharePreview.value = null
  nextTick(() => {
    if (shareMode.value) shareBannerRef.value?.focus()
    else shareEntryBtnRef.value?.focus()
  })
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

// Show the jump-to-latest affordance whenever the reader has scrolled up off the
// live edge (autoScroll releases at gap >= 60) and there is content to return to.
// Re-pinning autoScroll lets the stream resume following the bottom.
const showJumpToLatest = computed(() => !autoScroll.value && messages.value.length > 0)
function jumpToLatest() {
  autoScroll.value = true
  scrollToBottom()
}

/* ── Tool calls ────────────────────────────────────────────────────── */

function showToolResultModal(content: string, title = t('chat.toolResult')) {
  toolResultModal.value = { open: true, title, content }
}

/* ── Attachments ───────────────────────────────────────────────────── */

function dragEventHasFiles(e: DragEvent): boolean {
  const types = Array.from(e.dataTransfer?.types || [])
  return types.includes('Files')
}

function onChatDragEnter(e: DragEvent) {
  if (!dragEventHasFiles(e)) return
  e.preventDefault()
  threadDragDepth.value += 1
  threadDragOver.value = true
}

function onChatDragOver(e: DragEvent) {
  if (!dragEventHasFiles(e)) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'copy'
  threadDragOver.value = true
}

function onChatDragLeave(e: DragEvent) {
  if (!dragEventHasFiles(e)) return
  threadDragDepth.value = Math.max(0, threadDragDepth.value - 1)
  if (threadDragDepth.value === 0) {
    threadDragOver.value = false
  }
}

function onChatDrop(e: DragEvent) {
  e.preventDefault()
  threadDragDepth.value = 0
  threadDragOver.value = false
  if (!dragEventHasFiles(e)) return
  const files = Array.from(e.dataTransfer?.files || [])
  if (files.length === 0) return
  void addAttachments(files)
  composerRef.value?.focusTextarea()
}

/* ── Textarea ──────────────────────────────────────────────────────── */

function autoResizeTextarea() {
  composerRef.value?.resizeTextarea()
}

/* ── Clipboard paste ───────────────────────────────────────────────── */

function onDocumentPaste(e: ClipboardEvent) {
  const items = e.clipboardData?.items
  if (!items) return
  const files: File[] = []
  let attachedImage = false
  for (let i = 0; i < items.length; i++) {
    if (items[i].type.startsWith('image/')) {
      const file = items[i].getAsFile()
      if (file) {
        files.push(file)
        attachedImage = true
      }
    }
  }
  if (files.length > 0) void addAttachments(files)
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

  // The landing agent switcher closes first and hands focus back to its trigger.
  if (agentSwitcherOpen.value) {
    e.preventDefault()
    closeAgentSwitcher()
    nextTick(() => agentSwitcherRef.value?.querySelector<HTMLElement>('.chat-landing-agent__btn')?.focus())
    return
  }

  // The share preview modal owns Escape while it is open: it closes only the
  // preview (share mode stays active) via its own handler, so bail here and let
  // it run rather than tearing down the whole share mode underneath it.
  if (sharePreview.value) return

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
  // A Sessions Hub "Start task" hand-off also asks the draft to send the
  // prefill in one step; the actual flush waits for the subscription in onMounted.
  if (state?.autosend === true) pendingAutoSend.value = prefill
  try {
    window.history.replaceState({ ...window.history.state, prefill: undefined, autosend: undefined }, '')
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
    persistSession(sessionKey.value, { updateRoute: false, source: 'chatView.initialSession' })
  }

  // Load elevated mode
  loadElevatedMode()

  // Resolve agent display names for the in-draft switcher.
  void loadAgentOptions()

  // Load feature toggles
  await loadFeatureToggles()
  unsubs.push(bindFeatureRefresh(scheduleHistorySync))

  // Subscribe to RPC events
  unsubs.push(chatRpcSubscriptions.subscribe())
  unsubs.push(chatApprovals.subscribe())
  unsubs.push(metaRuns.subscribe())

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
  const sessionSubscription = subscribeSession()
  if (!initialSession.draft) loadHistory()
  loadSlashCommands()

  // Focus textarea on desktop
  if (isDesktopViewport.value) {
    composerRef.value?.focusTextarea()
  }

  // Sessions Hub "Start task" hand-off: send the prefilled draft in one step.
  // Wait for the subscription first so the first turn streams into this view
  // rather than being missed before sessions.messages.subscribe registers.
  if (pendingAutoSend.value) {
    const text = pendingAutoSend.value
    pendingAutoSend.value = ''
    await sessionSubscription
    sendComposerText(text)
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
  metaRuns.cleanup()
  if (composerResizeObserver) { composerResizeObserver.disconnect(); composerResizeObserver = null }
  document.documentElement.style.removeProperty('--composer-h')
  // Drop any live share-preview object URL so the blob can be reclaimed.
  if (sharePreview.value) {
    URL.revokeObjectURL(sharePreview.value.url)
    sharePreview.value = null
  }
  unsubscribeSession()
})

useDocumentEvent('paste', onDocumentPaste)
useDocumentEvent('keydown', onDocumentKeydown)

// Watch for route changes
watch(() => route.query.session, (newSession) => {
  if (newSession && typeof newSession === 'string') {
    recordSessionNavigationDiag('route.query.session', {
      from: sessionKey.value,
      to: newSession,
      routeSession: newSession,
    })
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
  persistSession(sessionKey.value, { source: 'chatView.draftMaterialized' })
})

watch(sessionKey, () => {
  if (shareMode.value) endShareMode()
  deliverablesOpen.value = false
})

watch(shareableMessageCount, (count) => {
  if (count === 0 && shareMode.value) endShareMode()
})

// Router-led turns hold the live answer/work-card reveal back for [MIN,MAX] ms,
// then mount a block of content at once. Re-pin the thread on that reveal so it
// lands at the bottom instead of below the fold.
watch(answerRevealOpen, (open) => {
  if (open && autoScroll.value) scrollToBottom()
})

// An approval/clarify interrupt is a user-blocking control, not answer content,
// so it must not sit behind the router-lead reveal window. With the fold
// authoritative (default), the gated work-card is the only interrupt surface,
// so reveal immediately when a live interrupt part appears — otherwise the card
// can stay invisible for up to the MAX backstop when no router decision lands.
watch(() => liveInterruptParts.value.length, (n, prev) => {
  if (n > (prev ?? 0)) revealNow()
})
</script>

<style scoped src="../styles/chat-view.css"></style>

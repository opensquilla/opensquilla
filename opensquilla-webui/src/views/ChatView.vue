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
        <span v-if="contextWarningVisible" class="chat-ctx-warn">Context &gt; 85%</span>
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

        <!-- Rendered messages -->
        <template v-for="(msg, idx) in renderedMessages" :key="msg.id || `${msg.role}-${idx}`">
          <!-- Router FX strip -->
          <div
            v-if="msg.isRouterStrip"
            class="router-fx"
            :data-state="msg.routerState"
            :data-source="msg.routerSource"
            :data-observe="msg.routerObserve ? 'true' : undefined"
            :data-static="msg.routerStatic ? 'true' : undefined"
            :data-settled="msg.routerSettled ? 'true' : undefined"
          >
            <div class="router-fx-header">
              <span class="glyph">&#8592;</span>
              <span class="title">model router</span>
              <span class="glyph">&#8594;</span>
            </div>
            <div class="router-fx-grid">
              <div
                v-for="(cell, ci) in msg.gridCells"
                :key="ci"
                class="router-fx-cell"
                :data-kind="cell.kind"
                :data-cell-idx="ci"
                :data-tiers="cell.tiers?.join(',')"
                :class="{ win: ci === msg.winnerIdx }"
              >
                <span class="nm">{{ cell.displayName }}</span>
              </div>
              <div
                v-if="Number(msg.winnerIdx) >= 0"
                class="router-fx-selector visible lock"
                :class="{ 'lock-impact': !msg.routerStatic && !msg.routerSettled }"
                :style="routerSelectorStyle(msg)"
                aria-hidden="true"
              />
              <div v-if="Number(msg.winnerIdx) >= 0 && !msg.routerStatic && !msg.routerSettled" class="router-fx-burst" :style="routerBurstStyle(msg)" aria-hidden="true">
                <i v-for="n in 6" :key="n" />
              </div>
            </div>
          </div>

          <!-- User message -->
          <div
            v-else-if="msg.displayRole === 'user'"
            class="msg-user"
            :data-message-id="msg.messageId"
          >
            <div class="msg-user-bubble" :class="{ 'msg-user-bubble--has-attachments': msg.hasAttachments }">
              <template v-if="msg.text">
                {{ stripTimePrefix(msg.text) }}
              </template>
              <!-- Attachments -->
              <div v-if="msg.attachments?.length" class="msg-attachments">
                <template v-for="att in msg.attachments" :key="att.name">
                  <img v-if="att.dataUrl || att.data" class="msg-thumb" :src="att.dataUrl || `data:${att.mime || 'image/png'};base64,${att.data}`" :alt="att.name" />
                  <span v-else class="msg-file-chip" :title="att.name">
                    <span class="msg-file-chip__icon" aria-hidden="true">file</span>
                    <span class="msg-file-chip__name">{{ att.name }}</span>
                    <span class="msg-file-chip__meta">{{ att.mime || 'attachment' }}</span>
                  </span>
                </template>
              </div>
            </div>
            <div class="msg-user-actions">
              <button type="button" class="msg-action" title="Copy" @click="copyMessage(msg)"><Icon name="copy" :size="12" /></button>
              <button type="button" class="msg-action" title="Edit" @click="editMessage(idx)"><Icon name="edit" :size="12" /></button>
            </div>
          </div>

          <!-- AI message -->
          <div
            v-else-if="msg.displayRole === 'assistant'"
            class="msg-ai"
            :data-message-id="msg.messageId"
          >
            <div class="msg-ai-avatar">
              <img class="msg-ai-avatar__img" :src="assistantAvatarUrl" alt="" aria-hidden="true" />
            </div>
            <div class="msg-ai-main">
              <template v-if="msg.timelineItems?.length">
                <template v-for="item in msg.timelineItems" :key="item.key">
                  <div v-if="item.type === 'text'" class="msg-ai-text" v-html="item.html" />
                  <div v-else class="step-card">
                    <div
                      class="step-group"
                      :class="{ 'step-group--running': item.group.isRunning, 'step-group--error': item.group.isError, 'is-open': isToolGroupOpen(item.group.groupId) }"
                    >
                      <button type="button" class="step-group-header" @click="toggleToolGroup(item.group.groupId)">
                        <span class="step-icon">
                          <Icon :name="item.group.iconName" :size="15" />
                        </span>
                        <span class="step-body">
                          <span class="step-title-row">
                            <span class="step-title">{{ item.group.label }}</span>
                            <span v-if="item.group.calls.length > 1" class="step-count">{{ item.group.calls.length }} 次</span>
                            <span v-if="item.group.secondary" class="step-secondary">{{ item.group.secondary }}</span>
                          </span>
                        </span>
                        <span class="step-trailing">
                          <span class="step-status">{{ toolGroupStatusText(item.group) }}</span>
                          <Icon class="step-chevron" name="chevronRight" :size="14" />
                        </span>
                      </button>
                      <div v-if="isToolGroupOpen(item.group.groupId)" class="step-group-members">
                        <div
                          v-for="tc in item.group.calls"
                          :key="tc.renderKey"
                          class="step-subitem"
                          :class="{ 'step-item--running': tc.isRunning, 'step-item--success': tc.status === 'success', 'step-item--error': tc.status === 'error', 'is-open': isToolItemOpen(tc.renderKey) }"
                          @click="toggleToolItem(tc.renderKey)"
                        >
                          <div class="step-body">
                            <div class="step-title-row">
                              <span class="step-subtitle">{{ tc.displayName }}</span>
                              <span v-if="toolSecondaryText(tc)" class="step-secondary">{{ toolSecondaryText(tc) }}</span>
                            </div>
                            <div v-if="tc.inputPreview && isToolItemOpen(tc.renderKey)" class="step-detail">{{ tc.inputPreview }}</div>
                            <div v-if="tc.result && isToolItemOpen(tc.renderKey)" class="step-result" :class="{ 'step-result--error': tc.isError }">
                              <pre class="step-result-pre">{{ tc.resultPreview }}</pre>
                              <button v-if="tc.result.length > 200" class="step-view-btn" @click.stop="showToolResultModal(tc.result, tc.displayName)">View full</button>
                            </div>
                          </div>
                          <div class="step-trailing">
                            <span class="step-status">{{ toolStatusText(tc) }}</span>
                            <Icon class="step-chevron" name="chevronRight" :size="14" />
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </template>
              </template>
              <template v-else>
                <div v-if="msg.text" class="msg-ai-text" v-html="renderMarkdown(msg.text)" />
              </template>

              <!-- Step card (legacy tool calls without timeline) -->
              <div v-if="!msg.timelineItems?.length && msg.toolCalls?.length" class="step-card">
                <div
                  v-for="group in toolCallGroups(msg.toolCalls, msg.messageId || msg.id || String(idx))"
                  :key="group.groupId"
                  class="step-group"
                  :class="{ 'step-group--running': group.isRunning, 'step-group--error': group.isError, 'is-open': isToolGroupOpen(group.groupId) }"
                >
                  <button type="button" class="step-group-header" @click="toggleToolGroup(group.groupId)">
                    <span class="step-icon">
                      <Icon :name="group.iconName" :size="15" />
                    </span>
                    <span class="step-body">
                      <span class="step-title-row">
                        <span class="step-title">{{ group.label }}</span>
                        <span v-if="group.calls.length > 1" class="step-count">{{ group.calls.length }} 次</span>
                        <span v-if="group.secondary" class="step-secondary">{{ group.secondary }}</span>
                      </span>
                    </span>
                    <span class="step-trailing">
                      <span class="step-status">{{ toolGroupStatusText(group) }}</span>
                      <Icon class="step-chevron" name="chevronRight" :size="14" />
                    </span>
                  </button>
                  <div v-if="isToolGroupOpen(group.groupId)" class="step-group-members">
                    <div
                      v-for="tc in group.calls"
                      :key="tc.renderKey"
                      class="step-subitem"
                      :class="{ 'step-item--running': tc.isRunning, 'step-item--success': tc.status === 'success', 'step-item--error': tc.status === 'error', 'is-open': isToolItemOpen(tc.renderKey) }"
                      @click="toggleToolItem(tc.renderKey)"
                    >
                      <div class="step-body">
                        <div class="step-title-row">
                          <span class="step-subtitle">{{ tc.displayName }}</span>
                          <span v-if="toolSecondaryText(tc)" class="step-secondary">{{ toolSecondaryText(tc) }}</span>
                        </div>
                        <div v-if="tc.inputPreview && isToolItemOpen(tc.renderKey)" class="step-detail">{{ tc.inputPreview }}</div>
                        <div v-if="tc.result && isToolItemOpen(tc.renderKey)" class="step-result" :class="{ 'step-result--error': tc.isError }">
                          <pre class="step-result-pre">{{ tc.resultPreview }}</pre>
                          <button v-if="tc.result.length > 200" class="step-view-btn" @click.stop="showToolResultModal(tc.result, tc.displayName)">View full</button>
                        </div>
                      </div>
                      <div class="step-trailing">
                        <span class="step-status">{{ toolStatusText(tc) }}</span>
                        <Icon class="step-chevron" name="chevronRight" :size="14" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>

              <!-- Artifacts -->
              <div v-if="msg.artifacts?.length" class="msg-artifacts">
                <div class="msg-artifact-files">
                  <ArtifactChip
                    v-for="art in msg.artifacts"
                    :key="art.id || art.name"
                    :artifact="art"
                    :category="artifactCategory(art)"
                    :icon-name="artifactIconName(art)"
                    :title="artifactFileTitle(art)"
                    :subtitle="artifactFileSubtitle(art)"
                    :action-label="artifactActionLabel(art)"
                    @download="downloadArtifact"
                  />
                </div>
              </div>

              <!-- Meta & Actions -->
              <div class="msg-ai-footer">
                <div v-if="msg.meta" class="msg-ai-meta">
                  <span v-if="msg.meta.model" class="msg-meta__model">{{ msg.meta.modelShort }}</span>
                  <span v-if="msg.meta.hasTokens">
                    &#8593;{{ fmtTok(msg.meta.input) }} &#8595;{{ fmtTok(msg.meta.output) }}
                  </span>
                  <span v-if="msg.meta.cachedTokens">cache:{{ fmtTok(msg.meta.cachedTokens) }}</span>
                  <span v-if="msg.meta.reasoningTokens">think:{{ fmtTok(msg.meta.reasoningTokens) }}</span>
                  <span v-if="msg.meta.costUsd">${{ msg.meta.costUsd.toFixed(6).replace(/\.?0+$/, '') }}</span>
                  <span v-if="msg.meta.hasSaved" class="savings-indicator">{{ msg.meta.savedLabel }}</span>
                </div>
                <div class="msg-ai-actions">
                  <button type="button" class="msg-action" title="Copy" @click="copyMessage(msg)"><Icon name="copy" :size="12" /></button>
                  <button type="button" class="msg-action" title="Regenerate" @click="regenerateMessage(idx)"><Icon name="refresh" :size="12" /></button>
                </div>
              </div>
            </div>
          </div>

          <!-- System / Subagent / Error messages -->
          <div
            v-else
            class="msg-system-wrap"
          >
            <div class="msg-system" :class="msg.displayRole">
              <span class="msg-system-label">{{ msg.roleLabel }}</span>
              <template v-if="msg.displayRole === 'subagent'">
                <details class="chat-subagent-disclosure">
                  <summary class="chat-subagent-disclosure-summary">{{ subagentSummary(msg.text) }}</summary>
                  <pre class="chat-subagent-disclosure-body">{{ subagentBody(msg.text) }}</pre>
                </details>
              </template>
              <template v-else-if="msg.text">
                {{ msg.text }}
              </template>
            </div>
          </div>
        </template>

        <!-- Streaming AI message (Kimi style) -->
        <div v-if="isStreaming && streamBubble" class="msg-ai" data-history-role="assistant" aria-live="polite">
          <div class="msg-ai-avatar">
            <img class="msg-ai-avatar__img" :src="assistantAvatarUrl" alt="" aria-hidden="true" />
          </div>
          <div class="msg-ai-main">
            <!-- Streaming timeline -->
            <template v-for="item in streamTimelineItems" :key="item.key">
              <div v-if="item.type === 'text'" class="msg-ai-text" v-html="item.html" />
              <div v-else class="step-card">
                <div
                  class="step-group"
                  :class="{ 'step-group--running': item.group.isRunning, 'step-group--error': item.group.isError, 'is-open': isToolGroupOpen(item.group.groupId) }"
                >
                  <button type="button" class="step-group-header" @click="toggleToolGroup(item.group.groupId)">
                    <span class="step-icon">
                      <Icon :name="item.group.iconName" :size="15" />
                    </span>
                    <span class="step-body">
                      <span class="step-title-row">
                        <span class="step-title">{{ item.group.label }}</span>
                        <span v-if="item.group.calls.length > 1" class="step-count">{{ item.group.calls.length }} 次</span>
                        <span v-if="item.group.secondary" class="step-secondary">{{ item.group.secondary }}</span>
                      </span>
                    </span>
                    <span class="step-trailing">
                      <span class="step-status">{{ toolGroupStatusText(item.group) }}</span>
                      <Icon class="step-chevron" name="chevronRight" :size="14" />
                    </span>
                  </button>
                  <div v-if="isToolGroupOpen(item.group.groupId)" class="step-group-members">
                    <div
                      v-for="tc in item.group.calls"
                      :key="tc.renderKey"
                      class="step-subitem"
                      :class="{ 'step-item--running': tc.isRunning, 'step-item--success': tc.status === 'success', 'step-item--error': tc.status === 'error', 'is-open': isToolItemOpen(tc.renderKey) }"
                      @click="toggleToolItem(tc.renderKey)"
                    >
                      <div class="step-body">
                        <div class="step-title-row">
                          <span class="step-subtitle">{{ tc.displayName }}</span>
                          <span v-if="toolSecondaryText(tc)" class="step-secondary">{{ toolSecondaryText(tc) }}</span>
                        </div>
                        <div v-if="tc.inputPreview && isToolItemOpen(tc.renderKey)" class="step-detail">{{ tc.inputPreview }}</div>
                        <div v-if="tc.result && isToolItemOpen(tc.renderKey)" class="step-result" :class="{ 'step-result--error': tc.isError }">
                          <pre class="step-result-pre">{{ tc.resultPreview }}</pre>
                          <button v-if="tc.result.length > 200" class="step-view-btn" @click.stop="showToolResultModal(tc.result, tc.displayName)">View full</button>
                        </div>
                      </div>
                      <div class="step-trailing">
                        <span class="step-status">{{ toolStatusText(tc) }}</span>
                        <Icon class="step-chevron" name="chevronRight" :size="14" />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>

            <div v-if="streamActivityVisible" class="stream-activity" role="status" aria-live="polite">
              <span class="stream-activity-dot" aria-hidden="true" />
              <span class="stream-activity-text activity-shimmer">{{ streamActivityText }}</span>
            </div>

            <!-- Stream artifacts -->
            <div v-if="streamArtifacts.length" class="msg-artifacts">
              <div class="msg-artifact-files">
                <ArtifactChip
                  v-for="art in streamArtifacts"
                  :key="art.id || art.name"
                  :artifact="art"
                  :category="artifactCategory(art)"
                  :icon-name="artifactIconName(art)"
                  :title="artifactFileTitle(art)"
                  :subtitle="artifactFileSubtitle(art)"
                  :action-label="artifactActionLabel(art)"
                  @download="downloadArtifact"
                />
              </div>
            </div>

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

    <!-- Pending queue -->
    <div v-if="pendingQueue.length > 0" class="chat-pending">
      <div class="chat-pending-header">
        <span class="chat-pending-label" title="Alt+&#8593; pulls the most recent back into the input &#183; ESC recovers all to input &#183; sends FIFO when the current response finishes">Pending {{ pendingQueue.length }}/{{ MAX_PENDING }}</span>
        <button v-if="pendingQueue.length >= 2" class="chat-pending-clear" aria-label="Clear all pending messages" @click="clearPendingQueue">Clear all</button>
      </div>
      <div class="chat-pending-chips">
        <span
          v-for="(p, i) in pendingQueue"
          :key="i"
          class="chat-pending-chip"
          :title="p.text"
        >
          <span class="chat-pending-text">{{ p.text.slice(0, 30) }}{{ p.text.length > 30 ? '...' : '' }}</span>
          <span v-if="p.attachments?.length" class="chat-pending-attch">&#128206;{{ p.attachments.length }}</span>
          <button class="chat-pending-chip-remove" :aria-label="`Remove pending message ${i + 1}`" title="Remove" @click="removePendingChip(i)">&times;</button>
        </span>
      </div>
    </div>

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

    <!-- Tool Result Modal -->
    <div v-if="toolResultModal.open" class="tool-modal-overlay" @click.self="toolResultModal.open = false">
      <div class="tool-modal">
        <div class="tool-modal__header">
          <h3 class="tool-modal__title">{{ toolResultModal.title }}</h3>
          <button class="btn btn--icon btn--ghost" title="Close" aria-label="Close" @click="toolResultModal.open = false">
            <Icon name="x" :size="16" />
          </button>
        </div>
        <pre class="tool-modal__body">{{ toolResultModal.content }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import { useAppStore } from '@/stores/app'
import ArtifactChip from '@/components/chat/ArtifactChip.vue'
import ChatComposer from '@/components/chat/ChatComposer.vue'
import Icon from '@/components/Icon.vue'
import { useMediaQuery } from '@/composables/chat/useMediaQuery'
import type { Attachment } from '@/types/chat'
import type { IconName } from '@/utils/icons'
import type {
  ArtifactPayload,
  ChatHistoryResponse,
  ChatSendParams,
  ChatSendResponse,
  CompactionPayload,
  RouterDecisionPayload,
  SessionMessagesSubscribeParams,
  SessionMessagesSubscribeResponse,
  SessionEventPayload,
  TextDeltaPayload,
  ToolDeltaPayload,
  ToolResultPayload,
  ToolUsePayload,
} from '@/types/rpc'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

/* ── Types ─────────────────────────────────────────────────────────── */

interface PendingItem {
  text: string
  attachments: Attachment[]
  intent: string | null
}

interface ChatComposerHandle {
  composerElement: () => HTMLElement | null
  focusTextarea: () => void
  isTextareaFocused: () => boolean
  resizeTextarea: () => void
}

interface Message {
  role: string
  text: string
  ts: string | number | null
  routerDecision?: RouterDecisionPayload | null
  artifacts?: ArtifactPayload[]
  tool_calls?: any[]
  timeline?: any[]
  attachments?: Attachment[]
  provenanceKind?: string
  provenanceSourceSessionKey?: string
  provenanceSourceTool?: string
  interrupted?: boolean
  messageId?: string
  usage?: any
  turn_usage?: any
  model?: string
  input?: number
  input_tokens?: number
  output?: number
  output_tokens?: number
  restoredFromHistory?: boolean
}

interface RouterCell {
  kind: 'real' | 'decoy'
  tier?: string
  tiers?: string[]
  displayName: string
}

interface StreamToolCall {
  toolId: string
  name: string
  displayName: string
  groupId?: string
  inputRaw?: string
  inputPreview: string
  isRunning: boolean
  status: '' | 'success' | 'error'
  isError: boolean
  result: string
  resultPreview: string
  isOpen: boolean
}

type ToolCallRenderItem = StreamToolCall & {
  renderKey: string
}

interface ToolCallGroup {
  groupId: string
  operationKey: string
  label: string
  iconName: IconName
  calls: ToolCallRenderItem[]
  secondary: string
  isRunning: boolean
  isError: boolean
  status: '' | 'success' | 'error'
}

interface StreamSegment {
  type: 'text' | 'tool-group'
  raw?: string
  html?: string
  dirty?: boolean
  groupId?: string
  operationKey?: string
}

type StreamTimelineItem =
  | { type: 'text'; key: string; html: string }
  | { type: 'tool-group'; key: string; group: ToolCallGroup }

interface RenderedMessage {
  id?: string
  role: string
  displayRole: string
  roleLabel: string
  text: string
  timeStr: string
  showHeader: boolean
  isStreaming?: boolean
  messageId?: string
  hasAttachments?: boolean
  attachments?: Attachment[]
  toolCalls?: any[]
  timelineItems?: StreamTimelineItem[]
  artifacts?: ArtifactPayload[]
  meta?: any
  interrupted?: boolean
  provenanceKind?: string
  daySeparator?: boolean
  dayLabel?: string
  isRouterStrip?: boolean
  routerState?: string
  routerSource?: string
  routerObserve?: boolean
  routerStatic?: boolean
  routerSettled?: boolean
  gridCells?: RouterCell[]
  winnerIdx?: number
}

/* ── Constants ─────────────────────────────────────────────────────── */

const WEBCHAT_SESSION_KEY = 'agent:main:webchat:default'
const ELEVATED_MODE_KEY = 'opensquilla.elevatedMode'
const ELEVATED_MODE_VERSION_KEY = 'opensquilla.elevatedMode.version'
const ELEVATED_MODE_STORAGE_VERSION = '2'
const DEFAULT_STREAM_IDLE_TIMEOUT_MS = 210000
const INLINE_THRESHOLD_BYTES = 2_000_000
const ATTACHMENT_TEXT_HARD_CAP_BYTES = INLINE_THRESHOLD_BYTES
const ATTACHMENT_IMAGE_HARD_CAP_BYTES = 5 * 1024 * 1024
const ATTACHMENT_PDF_HARD_CAP_BYTES = 30 * 1024 * 1024
const MAX_PENDING = 5
const THINKING_DELAY_MS = 400
const THINKING_TTL_MS = 60000
const SQUILLA_VERBS = ['正在组织下一步', '正在梳理上下文', '正在等待模型响应', '正在准备输出']
const SQUILLA_DWELL_MS = 2500

const ATTACHMENT_IMAGE_MIMES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const ATTACHMENT_TEXT_MIMES = ['text/plain', 'text/markdown', 'text/html', 'text/csv', 'application/json']
const ATTACHMENT_ALLOWED_MIMES = [...ATTACHMENT_IMAGE_MIMES, 'application/pdf', ...ATTACHMENT_TEXT_MIMES]
const ATTACHMENT_EXTENSION_MIMES: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', pdf: 'application/pdf', txt: 'text/plain', md: 'text/markdown',
  markdown: 'text/markdown', html: 'text/html', htm: 'text/html', csv: 'text/csv', json: 'application/json',
}

const ROUTER_FX_GRID_COLS = 4
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

const toolResultModal = ref({ open: false, title: '', content: '' })

const ARTIFACT_MIME_CATEGORIES: Record<string, string> = {
  'application/json': 'data', 'application/ndjson': 'data', 'application/pdf': 'document',
  'application/x-ndjson': 'data', 'text/csv': 'data', 'text/html': 'document',
  'text/markdown': 'document', 'text/plain': 'document', 'text/tab-separated-values': 'data',
}

const ARTIFACT_EXTENSION_CATEGORIES: Record<string, string> = {
  csv: 'data', htm: 'document', html: 'document', ipynb: 'data', json: 'data',
  jsonl: 'data', log: 'document', markdown: 'document', md: 'document',
  ndjson: 'data', pdf: 'document', sql: 'code', tsv: 'data', txt: 'document',
}

/* ── Stores / Router ───────────────────────────────────────────────── */

const rpc = useRpcStore()
const appStore = useAppStore()
const route = useRoute()
const router = useRouter()
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
const isStreaming = ref(false)
const aborted = ref(false)
const autoScroll = ref(true)
const composing = ref(false)
const messages = ref<Message[]>([])
const pendingAttachments = ref<Attachment[]>([])
const pendingQueue = ref<PendingItem[]>([])
const nextAttachmentId = ref(1)
const pendingRouterDecision = ref<{ payload: RouterDecisionPayload; decision: RouterDecisionPayload } | null>(null)

// Streaming
const streamRaw = ref('')
const streamSegments = ref<StreamSegment[]>([])
const streamArtifacts = ref<ArtifactPayload[]>([])
const streamToolCalls = ref<StreamToolCall[]>([])
const openToolGroups = ref<Set<string>>(new Set())
const openToolItems = ref<Set<string>>(new Set())
let streamToolGroupSeq = 0
const streamBubble = ref(false)
const streamShowHeader = ref(false)
const streamHasVisibleOutput = computed(() => {
  return streamSegments.value.length > 0 ||
    streamToolCalls.value.length > 0 ||
    streamArtifacts.value.length > 0
})
const streamActivity = ref({ label: '正在发送', startedAt: 0 })
const streamActivityTick = ref(0)
let streamActivityTimer: ReturnType<typeof setInterval> | null = null
const streamActivityVisible = computed(() => {
  return isStreaming.value &&
    streamBubble.value &&
    !streamHasVisibleOutput.value
})
const streamActivityText = computed(() => {
  streamActivityTick.value
  const startedAt = streamActivity.value.startedAt || Date.now()
  const seconds = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
  const base = seconds >= 10 && streamActivity.value.label === '正在组织下一步'
    ? '仍在等待模型响应'
    : streamActivity.value.label
  return `${base} · ${seconds}s`
})
const streamTimelineItems = computed<StreamTimelineItem[]>(() => {
  const groupsById = new Map(toolCallGroups(streamToolCalls.value, 'stream').map(group => [group.groupId, group]))
  return streamSegments.value.flatMap((seg, idx): StreamTimelineItem[] => {
    if (seg.type === 'text') {
      if (!seg.raw && !seg.html) return []
      return [{ type: 'text', key: `text-${idx}`, html: seg.html || '' }]
    }
    const group = seg.groupId ? groupsById.get(seg.groupId) : null
    return group ? [{ type: 'tool-group', key: seg.groupId || `tool-${idx}`, group }] : []
  })
})

// Thinking
const thinkingVisible = ref(false)
const thinkingText = ref('')
let thinkingTimer: ReturnType<typeof setInterval> | null = null
let thinkingDelayTimer: ReturnType<typeof setTimeout> | null = null
let thinkingStartTime = 0

// Session / UI
const lastHeaderRole = ref('')
const lastHeaderDay = ref('')
const threadDragOver = ref(false)
const toolbarPopoverOpen = ref(false)

// Elevated mode
const elevatedMode = ref('')
const globalElevatedMode = ref('')
const elevatedUnavailable = ref(false)

// Router
const routerEnabled = ref(false)
const toolbarState = ref({ bypass: false, router: true })
const routerFxSlotList = ref<string[]>([])
const routerFxModels = ref<Record<string, string>>({})

// Run status
const runStatus = ref({ status: 'idle', label: 'Idle', task: null as any })

// Context
const contextStatus = ref<any>(null)
const contextWarningVisible = computed(() => {
  const status = contextStatus.value || {}
  const tokens = Number(status.contextTokens || status.context_tokens)
  const windowTokens = Number(status.contextWindowTokens || status.context_window_tokens)
  let pressure = Number(status.pressure || status.contextPressure || status.context_pressure)
  if (pressure == null && tokens != null && windowTokens > 0) pressure = tokens / windowTokens
  if (pressure != null) pressure = Math.min(1, Math.max(0, pressure))
  return tokens != null && windowTokens > 0 && pressure != null && pressure >= 0.85
})

// Slash commands
const slashOpen = ref(false)
const slashIdx = ref(0)
const slashCmds = ref<any[]>([])
const filteredSlashCmds = ref<any[]>([])
const slashCatalogLoaded = ref(false)

// Compact
const compactInFlight = ref(false)
const compactInFlightKey = ref('')
const compactStatus = ref({ visible: false, message: '', detail: '', tone: 'info', isBusy: false })

// History
const inputHistoryIdx = ref<number | null>(null)
const inputHistoryDraft = ref('')

// Stream idle
const streamIdleTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const streamIdleTimeoutMs = ref(DEFAULT_STREAM_IDLE_TIMEOUT_MS)
const streamIdlePausedForApproval = ref(false)

// Epoch / seq
const currentEpoch = ref(0)
const lastStreamSeq = ref(0)
const activeTaskGroups = ref<Set<string>>(new Set())

// Pending session intent
const pendingSessionIntent = ref<string | null>(null)

// Savings / usage
const usageAccum = ref({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null as number | null, routedTurns: 0, sessionSaved: 0 })
const usageModel = ref('')
const savingsPopupLastTs = ref(0)
const lastSavingsPopupIdentity = ref('')

// Unsubscribers
let unsubs: (() => void)[] = []
let renderRafId: number | null = null
let renderDirty = false
let pendingDrainTimer: ReturnType<typeof setTimeout> | null = null
let historySyncTimer: ReturnType<typeof setTimeout> | null = null
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

const effectiveElevatedMode = computed(() => {
  const m = elevatedMode.value || globalElevatedMode.value
  return m === 'on' || m === 'bypass' || m === 'full' ? m : ''
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

const renderedMessages = computed((): RenderedMessage[] => {
  const result: RenderedMessage[] = []
  let prevDay = ''
  let prevRole = ''
  // Track the index of the last router strip emitted within the current
  // turn (resets on every `user` message). Within a turn we only ever
  // show ONE router strip; later decisions update that strip in place so
  // the selector animates from old tier → new tier instead of stacking
  // multiple animations.
  let turnRouterIdx = -1
  let turnIdx = 0

  for (let i = 0; i < messages.value.length; i++) {
    const msg = messages.value[i]
    const day = dayKey(msg.ts)

    // Track day changes for grouping, but keep the thread visually pure.
    if (day && day !== prevDay) {
      prevDay = day
      prevRole = ''
    }

    if (msg.role === 'user') { turnRouterIdx = -1; turnIdx++ }

    const routerDecision = normalizeRouterDecision(msg.routerDecision || (msg.provenanceKind === 'router_decision' ? msg : null))
    if (routerDecision) {
      const cells = routerDecisionCells(routerDecision)
      const winnerIdx = routerWinnerCellIndex(cells, routerDecision.tier)
      const stripItem: RenderedMessage = {
        id: `router-turn-${turnIdx}`,
        role: 'router',
        displayRole: 'router',
        roleLabel: 'Router',
        text: '',
        timeStr: msg.ts ? relTime(msg.ts) : '',
        showHeader: false,
        isRouterStrip: true,
        routerState: routerDecisionState(routerDecision),
        routerSource: routerDecision.source || 'none',
        routerObserve: routerDecision.routing_applied === false,
        routerStatic: msg.restoredFromHistory === true,
        routerSettled: (msg as any).routerSettled === true,
        gridCells: cells,
        winnerIdx,
        messageId: msg.messageId,
      }
      if (turnRouterIdx >= 0) {
        stripItem.routerSettled = true
        result[turnRouterIdx] = stripItem
      } else {
        result.push(stripItem)
        turnRouterIdx = result.length - 1
      }
      prevRole = ''
      continue
    }

    const usageRouterDecision = routerDecisionFromUsage(msg)
    if (usageRouterDecision) {
      const cells = routerDecisionCells(usageRouterDecision)
      const winnerIdx = routerWinnerCellIndex(cells, usageRouterDecision.tier)
      const stripItem: RenderedMessage = {
        id: `router-turn-${turnIdx}`,
        role: 'router',
        displayRole: 'router',
        roleLabel: 'Router',
        text: '',
        timeStr: msg.ts ? relTime(msg.ts) : '',
        showHeader: false,
        isRouterStrip: true,
        routerState: routerDecisionState(usageRouterDecision),
        routerSource: usageRouterDecision.source || 'none',
        routerObserve: usageRouterDecision.routing_applied === false,
        routerStatic: msg.restoredFromHistory === true,
        routerSettled: (msg as any).routerSettled === true,
        gridCells: cells,
        winnerIdx,
        messageId: `${msg.messageId || i}-router`,
      }
      if (turnRouterIdx >= 0) {
        stripItem.routerSettled = true
        result[turnRouterIdx] = stripItem
      } else {
        result.push(stripItem)
        turnRouterIdx = result.length - 1
      }
      prevRole = ''
    }

    const isSubagent = isSubagentCompletionMessage(msg.role, msg.text, msg)
    const displayRole = isSubagent ? 'subagent' : msg.role
    const roleLabel = displayRole === 'user' ? 'You' : displayRole === 'assistant' ? 'Assistant' : displayRole === 'subagent' ? 'Sub-agent' : displayRole.charAt(0).toUpperCase() + displayRole.slice(1)
    const collapsible = displayRole === 'user' || displayRole === 'assistant'
    const sameGroup = collapsible && displayRole === prevRole && day === prevDay && day !== ''
    if (collapsible) prevRole = displayRole

    const timeStr = msg.ts ? relTime(msg.ts) : ''

    // Meta
    let meta = null
    if (msg.usage || msg.turn_usage) {
      const u = msg.usage || msg.turn_usage || {}
      const model = msg.model || u.model || u.routed_model || ''
      const input = Number(msg.input ?? msg.input_tokens ?? u.input_tokens ?? u.inputTokens ?? 0)
      const output = Number(msg.output ?? msg.output_tokens ?? u.output_tokens ?? u.outputTokens ?? 0)
      const cached = Number(u.cached_tokens || 0)
      const reasoning = Number(u.reasoning_tokens || 0)
      const cost = Number(u.cost_usd || 0)
      const hasTier = !!(u.routed_tier && u.routing_source && u.routing_source !== 'none')
      const turnSavedPct = typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0 ? u.total_savings_pct : 0
      const hasSaved = hasTier && turnSavedPct > 0 && !u.__savings_ui_suppressed
      meta = {
        model, modelShort: model.includes('/') ? model.split('/').pop() : model,
        input, output, hasTokens: input > 0 || output > 0,
        cachedTokens: cached, reasoningTokens: reasoning,
        costUsd: cost, hasSaved, turnSavedPct,
        savedLabel: turnSavedPct > 0 ? `Saved ~${Math.round(turnSavedPct)}%` : 'Cost optimized',
      }
    }

    const ownerKey = msg.messageId || `${msg.role}-${i}`
    const toolCalls = normalizeToolCalls(msg.tool_calls)
    const timelineItems = normalizeMessageTimeline(msg, ownerKey)
    result.push({
      id: `${msg.role}-${i}`,
      role: msg.role,
      displayRole,
      roleLabel,
      text: msg.role === 'assistant' ? stripGeneratedArtifactMarkers(msg.text) : msg.text,
      timeStr,
      showHeader: !sameGroup,
      messageId: msg.messageId,
      hasAttachments: !!msg.attachments?.length,
      attachments: msg.attachments,
      toolCalls,
      timelineItems,
      artifacts: msg.artifacts,
      meta,
      interrupted: msg.interrupted,
      provenanceKind: msg.provenanceKind,
    })
  }

  return result
})

/* ── Helpers ───────────────────────────────────────────────────────── */

function relTime(ts: string | number | null): string {
  if (!ts) return ''
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

function fmtTok(n: number): string {
  if (!n) return '0'
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${+(n / 1_000).toFixed(1)}k`
  return String(n)
}

function dayKey(ts: string | number | null): string {
  if (!ts) return ''
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toISOString().slice(0, 10)
}

function truncate(s: string, max = 200): string {
  if (!s || s.length <= max) return s || ''
  return s.slice(0, max) + '…'
}

function normalizeRouterDecision(raw: any): any | null {
  if (!raw || typeof raw !== 'object') return null
  const tier = String(raw.tier || raw.routed_tier || '').trim()
  if (!tier) return null
  return {
    ...raw,
    tier,
    model: raw.model || raw.routed_model || '',
    baseline_model: raw.baseline_model || raw.baselineModel || '',
  }
}

function routerDecisionFromUsage(msg: Message): any | null {
  const usage = msg.usage || msg.turn_usage
  if (!usage || usage.routing_source === 'none') return null
  const tier = typeof usage.routed_tier === 'string' ? usage.routed_tier : ''
  if (!tier) return null
  return normalizeRouterDecision({
    tier,
    model: usage.routed_model || usage.model || msg.model || '',
    source: usage.routing_source || 'none',
    confidence: typeof usage.routing_confidence === 'number' ? usage.routing_confidence : 0,
    fallback: usage.routing_source === 'fallback',
    routing_applied: usage.routing_applied !== false,
    rollout_phase: usage.rollout_phase || 'full',
  })
}

function routerDecisionState(decision: any): string {
  if (decision.routing_applied === false) return 'observe'
  if (decision.fallback) return 'fallback'
  return 'settled'
}

function shortModelName(model: string): string {
  const raw = String(model || '').trim()
  if (!raw) return ''
  const last = raw.includes('/') ? raw.split('/').pop() || raw : raw
  return last.replace(/^claude-/, '').replace(/^gpt-/, 'gpt-')
}

function routerFxStripProvider(name: string): string {
  const raw = String(name || '').trim()
  if (!raw) return ''
  const idx = raw.lastIndexOf('/')
  return idx >= 0 ? raw.slice(idx + 1) : raw
}

function routerFxHashSeed(key: string): number {
  let h = 0x811c9dc5
  const s = String(key || '')
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i)
    h = Math.imul(h, 0x01000193)
  }
  return h >>> 0
}

function routerFxMulberry32(seed: number): () => number {
  let state = seed >>> 0
  return () => {
    state = (state + 0x6D2B79F5) >>> 0
    let t = state
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

function routerFxShuffle<T>(items: T[], seedKey: string): T[] {
  const rng = routerFxMulberry32(routerFxHashSeed(seedKey))
  const arr = items.slice()
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1))
    ;[arr[i], arr[j]] = [arr[j], arr[i]]
  }
  return arr
}

function routerFxSortTiers(list: string[]): string[] {
  return list.slice().sort((a, b) => {
    const am = /^t(\d+)$/.exec(a)
    const bm = /^t(\d+)$/.exec(b)
    if (am && bm) return parseInt(am[1], 10) - parseInt(bm[1], 10)
    if (am) return -1
    if (bm) return 1
    return a.localeCompare(b)
  })
}

function routerDecisionCells(decision: any): RouterCell[] {
  const winnerTier = String(decision.tier || '').toLowerCase()
  const configuredTiers = routerFxSlotList.value.length ? routerFxSlotList.value.slice() : []
  if (winnerTier && !configuredTiers.includes(winnerTier)) configuredTiers.push(winnerTier)
  const sourceTiers = configuredTiers.length ? configuredTiers : (winnerTier ? [winnerTier] : [])
  const realByModel = new Map<string, RouterCell>()

  for (const tier of sourceTiers) {
    const model = routerFxModels.value[tier] || (tier === winnerTier ? String(decision.model || '') : '')
    if (!model && tier !== winnerTier) continue
    const key = model || `winner:${tier}`
    const existing = realByModel.get(key)
    if (existing) {
      existing.tiers = [...(existing.tiers || []), tier]
      continue
    }
    realByModel.set(key, {
      kind: 'real',
      tier,
      tiers: [tier],
      displayName: shortModelName(routerFxStripProvider(model)) || 'selected model',
    })
  }

  const realCells = Array.from(realByModel.values())
  const realNames = new Set(realCells.map(cell => cell.displayName).filter(Boolean))
  const decoys: RouterCell[] = []
  for (const name of ROUTER_FX_DECOY_POOL) {
    if (realCells.length + decoys.length >= ROUTER_FX_GRID_CELLS) break
    if (realNames.has(name)) continue
    decoys.push({ kind: 'decoy', displayName: name })
  }
  while (realCells.length + decoys.length < ROUTER_FX_GRID_CELLS) {
    decoys.push({ kind: 'decoy', displayName: '-' })
  }
  const seedKey = `${sessionKey.value}:${decision.tier || ''}:${decision.model || ''}:${decision.messageId || ''}`
  return routerFxShuffle([...realCells, ...decoys], seedKey)
}

function routerWinnerCellIndex(cells: RouterCell[], tier: string): number {
  const norm = String(tier || '').toLowerCase()
  return cells.findIndex(cell => cell.kind === 'real' && (cell.tiers || []).includes(norm))
}

function routerSelectorStyle(msg: RenderedMessage): Record<string, string> {
  const idx = Math.max(0, Number(msg.winnerIdx ?? 0))
  const col = idx % ROUTER_FX_GRID_COLS
  const row = Math.floor(idx / ROUTER_FX_GRID_COLS)
  const lefts = [
    '8px',
    'calc(((100% - 28px) / 4) + 12px)',
    'calc(((100% - 28px) / 2) + 16px)',
    'calc(((100% - 28px) * 3 / 4) + 20px)',
  ]
  return {
    '--router-left': lefts[col] || '8px',
    '--router-top': `${8 + row * 34}px`,
  }
}

function routerBurstStyle(msg: RenderedMessage): Record<string, string> {
  const idx = Math.max(0, Number(msg.winnerIdx ?? 0))
  const col = idx % ROUTER_FX_GRID_COLS
  const row = Math.floor(idx / ROUTER_FX_GRID_COLS)
  const lefts = [
    'calc(((100% - 28px) / 8) + 8px)',
    'calc(((100% - 28px) * 3 / 8) + 12px)',
    'calc(((100% - 28px) * 5 / 8) + 16px)',
    'calc(((100% - 28px) * 7 / 8) + 20px)',
  ]
  return {
    '--router-burst-left': lefts[col] || 'calc(12.5% + 4.5px)',
    '--router-burst-top': `${23 + row * 34}px`,
  }
}

function normalizeToolCalls(raw: any[] | undefined): any[] {
  if (!raw || !Array.isArray(raw)) return []
  const merged: any[] = []
  const byId = new Map<string, any>()

  raw.forEach((tc: any, index: number) => {
    const name = normalizeToolName(tc)
    if (!name) return
    if (isInternalToolName(name)) return
    const input = normalizeToolInputText(tc)
    const result = tc.result || tc.content || tc.output || ''
    const resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
    const isError = !!(tc.is_error || tc.isError || tc.error || (tc.execution_status && ['error', 'timeout', 'cancelled'].includes(tc.execution_status.status)))
    const toolId = tc.tool_use_id || tc.toolId || tc.id || `${name}:${index}`
    let item = byId.get(toolId)
    if (!item) {
      item = {
        toolId,
        name,
        displayName: toolDisplayName(name, input),
        groupId: tc.groupId || tc.group_id,
        inputRaw: input,
        inputPreview: '',
        isRunning: false,
        status: '' as '' | 'success' | 'error',
        isError: false,
        result: '',
        resultPreview: '',
        isOpen: false,
      }
      byId.set(toolId, item)
      merged.push(item)
    }
    if (!item.inputPreview && input) {
      item.inputRaw = input
      item.inputPreview = truncate(input, 200)
      item.displayName = toolDisplayName(item.name, input)
    }
    if (resultStr) {
      item.result = resultStr
      item.resultPreview = truncate(resultStr, 200)
      item.status = isError ? 'error' : 'success'
    }
    if (isError) {
      item.isError = true
      item.status = 'error'
    }
  })

  return merged.map((tc: any) => ({
    toolId: tc.toolId,
    name: tc.name,
    displayName: tc.displayName,
    groupId: tc.groupId,
    inputRaw: tc.inputRaw,
    inputPreview: tc.inputPreview,
    isRunning: tc.isRunning,
    status: tc.status,
    isError: tc.isError,
    result: tc.result,
    resultPreview: tc.resultPreview,
    isOpen: false,
  }))
}

function normalizeMessageTimeline(msg: Message, ownerKey: string): StreamTimelineItem[] {
  if (msg.role !== 'assistant') return []
  const explicitTimeline = Array.isArray(msg.timeline) ? msg.timeline : []
  if (explicitTimeline.length) {
    const calls = normalizeToolCalls(msg.tool_calls)
    return timelineFromSegments(explicitTimeline, calls, ownerKey)
  }
  const rawSegments = Array.isArray(msg.tool_calls) ? msg.tool_calls : []
  const hasPersistedTimeline = rawSegments.some((seg: any) => ['text', 'tool_use', 'tool_result'].includes(String(seg?.type || '')))
  if (!hasPersistedTimeline) return []
  return timelineFromPersistedSegments(rawSegments, ownerKey)
}

function timelineFromSegments(segments: any[], calls: StreamToolCall[], ownerKey: string): StreamTimelineItem[] {
  const groupsById = new Map(toolCallGroups(calls, ownerKey).map(group => [group.groupId, group]))
  return segments.flatMap((seg: any, idx: number): StreamTimelineItem[] => {
    if (seg?.type === 'text') {
      const raw = String(seg.raw ?? seg.text ?? '')
      return raw ? [{ type: 'text', key: `${ownerKey}:timeline:text:${idx}`, html: renderMarkdown(raw) }] : []
    }
    if (seg?.type === 'tool-group') {
      const groupId = String(seg.groupId || seg.group_id || '')
      const group = groupId ? groupsById.get(groupId) : null
      return group ? [{ type: 'tool-group', key: groupId, group }] : []
    }
    return []
  })
}

function timelineFromPersistedSegments(segments: any[], ownerKey: string): StreamTimelineItem[] {
  const items: StreamTimelineItem[] = []
  const callsById = new Map<string, StreamToolCall>()
  let groupSeq = 0

  const appendToolItem = (segment: any, index: number): StreamToolCall | null => {
    const name = normalizeToolName(segment)
    if (!name || isInternalToolName(name)) return null
    const toolId = segment.tool_use_id || segment.toolId || segment.id || `${name}:${index}`
    let call = callsById.get(toolId)
    if (!call) {
      const operationKey = toolOperationKey(name)
      const last = items[items.length - 1]
      let group = last?.type === 'tool-group' && last.group.operationKey === operationKey
        ? last.group
        : null
      if (!group) {
        group = {
          groupId: `${ownerKey}:timeline:tool-group:${operationKey}:${groupSeq++}`,
          operationKey,
          label: toolActionLabel(name),
          iconName: toolIconName(name),
          calls: [],
          secondary: '',
          isRunning: false,
          isError: false,
          status: '',
        }
        items.push({ type: 'tool-group', key: group.groupId, group })
      }
      const input = normalizeToolInputText(segment)
      call = {
        toolId,
        name,
        displayName: toolDisplayName(name, input),
        groupId: group.groupId,
        inputRaw: input,
        inputPreview: truncate(input, 200),
        isRunning: false,
        status: '',
        isError: false,
        result: '',
        resultPreview: '',
        isOpen: false,
        renderKey: `${ownerKey}:tool:${toolId}:${group.calls.length}`,
      } as ToolCallRenderItem
      group.calls.push(call as ToolCallRenderItem)
      callsById.set(toolId, call)
    }
    return call
  }

  segments.forEach((segment: any, index: number) => {
    const type = String(segment?.type || '')
    if (type === 'text') {
      const raw = String(segment.text || segment.raw || '')
      if (raw) items.push({ type: 'text', key: `${ownerKey}:timeline:text:${index}`, html: renderMarkdown(raw) })
      return
    }
    if (type === 'tool_use') {
      appendToolItem(segment, index)
      return
    }
    if (type === 'tool_result') {
      const call = appendToolItem(segment, index)
      if (!call) return
      const result = segment.result || segment.content || segment.output || ''
      const resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
      const input = normalizeToolInputText(segment)
      if (input && !call.inputPreview) {
        call.inputRaw = input
        call.inputPreview = truncate(input, 200)
        call.displayName = toolDisplayName(call.name, input)
      }
      call.isRunning = false
      call.isError = toolResultIsError(segment)
      call.status = call.isError ? 'error' : 'success'
      call.result = resultStr
      call.resultPreview = truncate(resultStr, 200)
    }
  })

  for (const item of items) {
    if (item.type !== 'tool-group') continue
    item.group.isRunning = item.group.calls.some(tc => tc.isRunning)
    item.group.isError = item.group.calls.some(tc => tc.isError || tc.status === 'error')
    item.group.status = item.group.isError ? 'error' : (item.group.calls.every(tc => tc.status === 'success') ? 'success' : '')
    item.group.secondary = item.group.calls.length === 1
      ? toolSecondaryText(item.group.calls[0])
      : summarizeToolGroup(item.group.calls)
  }

  return items
}

function normalizeToolName(raw: any): string {
  const value = raw?.name ?? raw?.tool_name ?? raw?.toolName ?? raw?.function?.name
  const name = typeof value === 'string' ? value.trim() : ''
  return name && name !== 'tool' ? name : ''
}

function isInternalToolName(name: string): boolean {
  return name === 'router_control'
}

function normalizeToolInputText(raw: any): string {
  const value = raw?.input ?? raw?.arguments ?? ''
  if (value == null) return ''
  if (typeof value === 'string') {
    const text = value.trim()
    return isEmptyToolPreview(text) ? '' : text
  }
  if (Array.isArray(value) && value.length === 0) return ''
  if (typeof value === 'object' && Object.keys(value).length === 0) return ''
  const text = JSON.stringify(value, null, 2)
  return isEmptyToolPreview(text) ? '' : text
}

function isEmptyToolPreview(text: string): boolean {
  const value = String(text || '').trim()
  return !value || value === '""' || value === "''" || value === '{}' || value === '[]'
}

function normalizeAgentId(agentId: string): string {
  const raw = String(agentId || '').trim().toLowerCase()
  if (!raw || raw === 'default') return 'main'
  const normalized = raw.replace(/[^a-z0-9_-]/g, '-').replace(/^-+|-+$/g, '')
  return normalized && normalized !== 'default' ? normalized : 'main'
}

function agentIdFromSessionKey(key: string): string {
  if (!key.startsWith('agent:')) return 'main'
  return normalizeAgentId(key.split(':')[1] || 'main')
}

function webchatSessionKey(agentId: string, suffix = 'default'): string {
  return 'agent:' + normalizeAgentId(agentId) + ':webchat:' + suffix
}

function canonicalSessionKey(key: string): string {
  const value = (key || '').trim()
  if (!value || value === 'default' || value === 'webchat:default') return WEBCHAT_SESSION_KEY
  if (value.startsWith('agent:default:')) return 'agent:main:' + value.slice('agent:default:'.length)
  if (value.startsWith('sess-')) return 'agent:main:webchat:' + value.slice('sess-'.length)
  return value
}

function normalizeElevatedMode(mode: string): string {
  return mode === 'on' || mode === 'bypass' || mode === 'full' ? mode : ''
}

function isApprovalBypassMode(mode: string): boolean {
  return mode === 'bypass' || mode === 'full'
}

function normalizeRunStatus(status: string): string {
  const value = String(status || '').toLowerCase()
  if (value === 'abandoned') return 'interrupted'
  if (value === 'killed') return 'cancelled'
  if (['succeeded', 'success', 'complete'].includes(value)) return 'idle'
  if (['queued', 'running', 'interrupted', 'failed', 'timeout', 'cancelled'].includes(value)) return value
  return 'idle'
}

function runStatusLabelText(status: string): string {
  const labels: Record<string, string> = {
    queued: 'Queued', running: 'Running', interrupted: 'Interrupted',
    failed: 'Failed', timeout: 'Timed out', cancelled: 'Cancelled', idle: 'Idle',
  }
  return labels[status] || 'Idle'
}

function sessionRunStatus(source: any): { status: string; label: string; task: any } {
  source = source || {}
  const active = source.active_task || source.activeTask || null
  const last = source.last_task || source.lastTask || null
  const activeStatus = active ? normalizeRunStatus(active.status) : ''
  let status = normalizeRunStatus(source.run_status || source.runStatus || active?.status || last?.status || '')
  if (active && (activeStatus === 'queued' || activeStatus === 'running')) status = activeStatus
  const task = active || last || null
  return { status, label: runStatusLabelText(status), task }
}

function isAllowedAttachmentMime(mime: string): boolean {
  return typeof mime === 'string' && ATTACHMENT_ALLOWED_MIMES.includes(mime)
}

function isImageAttachmentMime(mime: string): boolean {
  return typeof mime === 'string' && ATTACHMENT_IMAGE_MIMES.includes(mime)
}

function canStageAttachmentMime(mime: string): boolean {
  return mime === 'application/pdf' || isImageAttachmentMime(mime)
}

function attachmentHardCapBytes(mime: string): number {
  if (mime === 'application/pdf') return ATTACHMENT_PDF_HARD_CAP_BYTES
  if (isImageAttachmentMime(mime)) return ATTACHMENT_IMAGE_HARD_CAP_BYTES
  if (['text/plain', 'text/markdown', 'text/html', 'text/csv', 'application/json'].includes(mime)) return ATTACHMENT_TEXT_HARD_CAP_BYTES
  return ATTACHMENT_IMAGE_HARD_CAP_BYTES
}

function resolveAttachmentMime(file: File): string {
  const name = file.name || ''
  const ext = name.includes('.') ? name.split('.').pop()?.toLowerCase() || '' : ''
  const extensionMime = ATTACHMENT_EXTENSION_MIMES[ext]
  if (file.type && isAllowedAttachmentMime(file.type)) return file.type
  return extensionMime || file.type || 'application/octet-stream'
}

/* ── Markdown / Text processing ────────────────────────────────────── */

const DIRECTIVE_TAG_RE = /\[\[\s*(?:reply_to_current|reply_to\s*:\s*[^\]\n]+)\s*\]\]\s*/g
const GENERATED_ARTIFACT_MARKER_RE = /(?:^|\s*)\[generated artifact omitted:\s*[^\]\n]+?\]\s*/gi
const PROTOCOL_TEXT_MARKER_RE = /<\s*(?:minimax:tool_call|tool_calls?|tvoe_calls|invoke\b|parameter\b|effect_calls\b|details\b|angle\s+brackets\b)/i
const TIME_PREFIX_RE = /^\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}[+\-]\d{2}:\d{2} (?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) [A-Za-z0-9_+\-/]+\]\n/

function stripDirectiveTags(text: string): string {
  return text.replace(DIRECTIVE_TAG_RE, '').replace(/^\n+/, '')
}

function stripGeneratedArtifactMarkers(text: string): string {
  text = String(text || '')
  if (!text.includes('[generated artifact omitted:')) return text
  return text.replace(/\r\n/g, '\n').replace(GENERATED_ARTIFACT_MARKER_RE, '').replace(/[ \t]{2,}/g, ' ').replace(/\n{3,}/g, '\n\n').trim()
}

function stripProtocolTextLeak(text: string): string {
  text = String(text || '')
  if (!text) return text
  const match = PROTOCOL_TEXT_MARKER_RE.exec(text)
  if (!match) return text
  return text.slice(0, match.index).trimEnd()
}

function stripTimePrefix(text: string): string {
  return typeof text === 'string' ? text.replace(TIME_PREFIX_RE, '') : text
}

const markdownCache = new Map<string, string>()
const MARKDOWN_CACHE_MAX = 500

function renderMarkdown(text: string): string {
  text = stripProtocolTextLeak(stripDirectiveTags(stripGeneratedArtifactMarkers(text)))
  if (!text) return ''

  const cached = markdownCache.get(text)
  if (cached !== undefined) return cached

  const rawHtml = marked.parse(text, { async: false, breaks: true }) as string
  const html = DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: [
      'p', 'br', 'hr', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li', 'blockquote', 'pre', 'code',
      'strong', 'em', 'del', 'a', 'table', 'thead',
      'tbody', 'tr', 'th', 'td', 'div', 'span', 'sup',
    ],
    ALLOWED_ATTR: ['href', 'title', 'alt', 'target', 'rel'],
    ALLOWED_URI_REGEXP: /^(?:https?|mailto|#):/i,
  })

  if (markdownCache.size >= MARKDOWN_CACHE_MAX) {
    const firstKey = markdownCache.keys().next().value
    if (firstKey !== undefined) markdownCache.delete(firstKey)
  }
  markdownCache.set(text, html)
  return html
}

/* ── Subagent ──────────────────────────────────────────────────────── */

function isSubagentCompletionMessage(role: string, text: string, options?: any): boolean {
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

function artifactMime(artifact: ArtifactPayload): string {
  return artifact?.mime ? String(artifact.mime).toLowerCase() : ''
}

function artifactName(artifact: ArtifactPayload): string {
  return artifact?.name ? String(artifact.name) : 'artifact'
}

function artifactExtension(name: string): string {
  const trimmed = String(name || '').trim().toLowerCase()
  const idx = trimmed.lastIndexOf('.')
  if (idx < 0 || idx === trimmed.length - 1) return ''
  return trimmed.slice(idx + 1)
}

function artifactCategory(artifact: ArtifactPayload): string {
  const mime = artifactMime(artifact)
  if (mime.startsWith('image/')) return 'visual'
  if (ARTIFACT_MIME_CATEGORIES[mime]) return ARTIFACT_MIME_CATEGORIES[mime]
  if (!mime || mime === 'application/octet-stream') {
    const ext = artifactExtension(artifactName(artifact))
    if (ARTIFACT_EXTENSION_CATEGORIES[ext]) return ARTIFACT_EXTENSION_CATEGORIES[ext]
  }
  return 'file'
}

function artifactCategoryLabel(artifact: ArtifactPayload): string {
  const cat = artifactCategory(artifact)
  switch (cat) {
    case 'data': return 'data'
    case 'document': return 'doc'
    case 'code': return 'code'
    default: return 'file'
  }
}

function artifactIconName(artifact: ArtifactPayload): IconName {
  const cat = artifactCategory(artifact)
  if (cat === 'visual') return 'image'
  if (cat === 'data') return 'table'
  if (cat === 'code') return 'fileCode'
  return 'fileText'
}

function artifactFileTitle(artifact: ArtifactPayload): string {
  return artifactName(artifact)
}

function artifactFileSubtitle(artifact: ArtifactPayload): string {
  const label = artifactCategoryLabel(artifact)
  const meta = artifactMeta(artifact)
  const action = artifactActionLabel(artifact) === '预览' ? '预览文件' : '下载文件'
  return [action, label.toUpperCase(), meta].filter(Boolean).join(' · ')
}

function artifactActionLabel(artifact: ArtifactPayload): string {
  const cat = artifactCategory(artifact)
  return cat === 'visual' || cat === 'document' ? '预览' : '下载'
}

function artifactMeta(artifact: ArtifactPayload): string {
  const mime = artifact?.mime ? String(artifact.mime) : ''
  const size = artifact?.size ? `${Math.max(1, Math.round(Number(artifact.size) / 1024))} KB` : ''
  return [mime, size].filter(Boolean).join(' · ')
}

function artifactDownloadUrl(artifact: ArtifactPayload): string {
  let raw = artifact?.download_url ? String(artifact.download_url) : ''
  if (!raw && artifact?.id) raw = `/api/v1/artifacts/${encodeURIComponent(artifact.id)}`
  if (!raw) return ''
  try {
    const url = new URL(raw, window.location.origin)
    url.searchParams.delete('sessionKey')
    url.searchParams.delete('session_key')
    return url.pathname + url.search + url.hash
  } catch { return raw }
}

async function downloadArtifact(artifact: ArtifactPayload) {
  const url = artifactDownloadUrl(artifact)
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
    const objUrl = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = objUrl
    a.download = artifact.name || 'artifact'
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(objUrl)
  } catch (err) {
    console.warn('Download failed:', err)
  }
}

/* ── Session management ────────────────────────────────────────────── */

function genKey(): string {
  return webchatSessionKey(agentIdFromSessionKey(sessionKey.value), Math.random().toString(36).slice(2, 10))
}

function routeStringParam(value: unknown): string {
  return typeof value === 'string' ? value : ''
}

function persistSession(key: string, options: { updateRoute?: boolean } = {}) {
  sessionKey.value = canonicalSessionKey(key)
  try { localStorage.setItem('opensquilla_active_session', sessionKey.value) } catch {}
  if (options.updateRoute === false) return
  if (routeStringParam(route.query.session) === sessionKey.value) return
  router.replace({ path: '/chat', query: { session: sessionKey.value } }).catch(() => {})
}

function hasNewChatRouteSignal(): boolean {
  return route.query.newChat === '1' || route.query.new === '1'
}

function consumeNewChatRouteSignal() {
  newSession()
}

function readSessionFromUrl(): string {
  return routeStringParam(route.query.session)
}

function readAgentFromUrl(): string {
  return routeStringParam(route.query.agent)
}

function loadElevatedMode() {
  let mode = ''
  let version = ''
  try {
    mode = localStorage.getItem(ELEVATED_MODE_KEY) || ''
    version = localStorage.getItem(ELEVATED_MODE_VERSION_KEY) || ''
  } catch {}
  if (mode === 'full' && version !== ELEVATED_MODE_STORAGE_VERSION) {
    mode = 'bypass'
    try {
      localStorage.setItem(ELEVATED_MODE_KEY, mode)
      localStorage.setItem(ELEVATED_MODE_VERSION_KEY, ELEVATED_MODE_STORAGE_VERSION)
    } catch {}
  }
  setElevatedMode(mode, { persist: false, toast: false, sync: true })
}

function setElevatedMode(mode: string, options: { persist?: boolean; toast?: boolean; sync?: boolean } = {}) {
  const normalized = normalizeElevatedMode(mode)
  elevatedMode.value = normalized
  if (options.persist !== false) {
    try {
      if (normalized) {
        localStorage.setItem(ELEVATED_MODE_KEY, normalized)
        localStorage.setItem(ELEVATED_MODE_VERSION_KEY, ELEVATED_MODE_STORAGE_VERSION)
      } else {
        localStorage.removeItem(ELEVATED_MODE_KEY)
        localStorage.removeItem(ELEVATED_MODE_VERSION_KEY)
      }
    } catch {}
  }
  toolbarState.value.bypass = isApprovalBypassMode(effectiveElevatedMode.value)
  if (options.sync) syncElevatedMode(normalized)
}

async function syncElevatedMode(mode: string) {
  if (!sessionKey.value || elevatedUnavailable.value) return
  try {
    const resp = await fetch('/api/elevated-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionKey: sessionKey.value, mode: mode || 'off' }),
    })
    if (resp.status === 403) {
      elevatedUnavailable.value = true
      try {
        localStorage.removeItem(ELEVATED_MODE_KEY)
        localStorage.removeItem(ELEVATED_MODE_VERSION_KEY)
      } catch {}
      elevatedMode.value = ''
      console.warn('Bypass requires a local owner session (loopback only).')
      return
    }
    if (!resp.ok) throw new Error('HTTP ' + resp.status)
  } catch (err: any) {
    console.warn('Failed to sync bypass mode:', err.message)
  }
}

/* ── Session switching ─────────────────────────────────────────────── */

function resetLiveTurnState() {
  hideThinkingIndicator()
  clearStreamActivity()
  clearStreamIdleTimer()
  streamIdlePausedForApproval.value = false
  isStreaming.value = false
  aborted.value = false
  streamRaw.value = ''
  streamSegments.value = []
  streamArtifacts.value = []
  streamToolCalls.value = []
  streamBubble.value = false
  pendingRouterDecision.value = null
}

function resetSessionRuntimeState() {
  currentEpoch.value = 0
  lastStreamSeq.value = 0
  activeTaskGroups.value.clear()
  resetLiveTurnState()
}

function switchToSession(key: string) {
  if (!key || key === sessionKey.value) {
    return
  }
  unsubscribeSession()
  sessionKey.value = canonicalSessionKey(key)
  persistSession(key)
  resetSessionRuntimeState()
  messages.value = []
  pendingSessionIntent.value = null
  clearPendingDrainAfterTerminalTimer()
  setCompactInFlight(false)
  hideCompactStatus()
  pendingQueue.value = []
  applySessionRunState({ run_status: 'idle' })
  contextStatus.value = null
  lastHeaderRole.value = ''
  lastHeaderDay.value = ''
  usageAccum.value = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null, routedTurns: 0, sessionSaved: 0 }
  usageModel.value = ''
  resetSavingsPopupCooldown()
  restoreWidgetState()
  loadCurrentSessionUsage()
  subscribeSession()
  loadHistory()
}

function newSession() {
  unsubscribeSession()
  const key = genKey()
  sessionKey.value = key
  persistSession(key)
  resetSessionRuntimeState()
  clearPendingDrainAfterTerminalTimer()
  setCompactInFlight(false)
  hideCompactStatus()
  pendingSessionIntent.value = 'new_chat'
  pendingQueue.value = []
  messages.value = []
  contextStatus.value = null
  lastHeaderRole.value = ''
  lastHeaderDay.value = ''
  usageAccum.value = { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, cost: null, routedTurns: 0, sessionSaved: 0 }
  usageModel.value = ''
  resetSavingsPopupCooldown()
  subscribeSession()
  console.info('New chat session:', key)
}

function copySessionKey() {
  if (!sessionKey.value) return
  navigator.clipboard.writeText(sessionKey.value).catch(() => {
    const ta = document.createElement('textarea')
    ta.value = sessionKey.value
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch {}
    ta.remove()
  })
}

/* ── RPC / Events ──────────────────────────────────────────────────── */

async function subscribeSession() {
  if (!sessionKey.value) return
  const key = sessionKey.value
  const sinceStreamSeq = lastStreamSeq.value
  try {
    await rpc.waitForConnection()
    if (key !== sessionKey.value) return
    const params: SessionMessagesSubscribeParams = { key, since_stream_seq: sinceStreamSeq }
    const res = await rpc.call<SessionMessagesSubscribeResponse>('sessions.messages.subscribe', params)
    if (key !== sessionKey.value) return
    if (res && res.subscribed === false) throw new Error('No subscription manager available')
    applySessionRunState(res)
    if (res && res.replay_complete === false) {
      lastStreamSeq.value = typeof res.current_stream_seq === 'number'
        ? Math.max(lastStreamSeq.value, res.current_stream_seq)
        : lastStreamSeq.value
      loadHistory()
    } else if (res && typeof res.current_stream_seq === 'number') {
      lastStreamSeq.value = Math.max(lastStreamSeq.value, res.current_stream_seq)
    }
    if (isStreaming.value) resetStreamIdleTimer()
  } catch (err: any) {
    console.warn('Session stream subscription failed:', err?.message || err)
  }
}

async function unsubscribeSession() {
  if (!sessionKey.value) return
  try {
    await rpc.call('sessions.messages.unsubscribe', { key: sessionKey.value })
  } catch { /* ignore */ }
}

function applySessionRunState(source: any) {
  const state = sessionRunStatus(source)
  runStatus.value = state
}

function isCurrentSessionPayload(payload: SessionEventPayload): boolean {
  const key = payload?.key || payload?.session_key || payload?.sessionKey || ''
  return !key || !sessionKey.value || key === sessionKey.value
}

function taskGroupId(payload: SessionEventPayload): string {
  const id = payload?.group_id
  return typeof id === 'string' && id ? id : ''
}

function noteTaskGroupActive(payload: SessionEventPayload) {
  const gid = taskGroupId(payload)
  if (gid) activeTaskGroups.value.add(gid)
  applySessionRunState(activeTaskGroupRunState(payload))
}

function noteTaskGroupTerminal(payload: SessionEventPayload, terminalStatus: string) {
  const gid = taskGroupId(payload)
  if (gid) activeTaskGroups.value.delete(gid)
  if (activeTaskGroups.value.size > 0) {
    applySessionRunState(activeTaskGroupRunState(payload))
    return
  }
  applySessionRunState({
    run_status: terminalStatus === 'failed' ? 'failed' : 'idle',
    last_task: { ...(payload || {}), status: terminalStatus },
  })
}

function activeTaskGroupRunState(payload: SessionEventPayload = {}) {
  return {
    run_status: 'running',
    active_task: { ...(payload || {}), status: 'running', task_group_count: activeTaskGroups.value.size },
  }
}

function sessionChangeIsTerminal(payload: SessionEventPayload): boolean {
  const reason = String(payload?.reason || '').toLowerCase()
  if (reason === 'turn_complete' || reason === 'task_terminal') return true
  const lifecycle = String(payload?.status || '').toLowerCase()
  if (['done', 'failed', 'killed', 'timeout'].includes(lifecycle)) return true
  const runStatus = normalizeRunStatus(String(payload?.run_status || payload?.runStatus || ''))
  return ['failed', 'timeout', 'cancelled', 'interrupted'].includes(runStatus)
}

function syncTerminalSessionChange(payload: SessionEventPayload = {}) {
  if (!isCurrentSessionPayload(payload)) return false
  activeTaskGroups.value.clear()
  const state = sessionRunStatus(payload)
  const interrupted = state.status === 'cancelled' || state.status === 'interrupted'
  if (isStreaming.value) endStreaming(interrupted ? { reason: 'aborted' } : undefined)
  applySessionRunState(payload)
  scheduleHistorySync()
  if (interrupted) {
    popAllPendingIntoComposer()
  } else {
    schedulePendingDrainAfterTerminal()
  }
  return true
}

/* ── Streaming ─────────────────────────────────────────────────────── */

function setStreamActivity(label: string) {
  streamActivity.value = { label, startedAt: Date.now() }
  streamActivityTick.value++
  if (!streamActivityTimer) {
    streamActivityTimer = setInterval(() => {
      streamActivityTick.value++
    }, 1000)
  }
}

function clearStreamActivity() {
  if (streamActivityTimer) {
    clearInterval(streamActivityTimer)
    streamActivityTimer = null
  }
  streamActivityTick.value++
}

function startStreaming() {
  isStreaming.value = true
  applySessionRunState({ run_status: 'running', active_task: { status: 'running' } })
  streamRaw.value = ''
  streamSegments.value = []
  streamArtifacts.value = []
  streamToolCalls.value = []
  openToolGroups.value = new Set()
  openToolItems.value = new Set()
  streamToolGroupSeq = 0
  streamBubble.value = true
  streamShowHeader.value = lastHeaderRole.value !== 'assistant'
  pendingRouterDecision.value = null
  setStreamActivity('正在发送')
  autoScroll.value = true
  resetStreamIdleTimer()
}

function endStreaming(opts?: { reason?: string }) {
  const wasAborted = opts?.reason === 'aborted'
  hideThinkingIndicator()
  clearStreamActivity()
  clearStreamIdleTimer()
  streamIdlePausedForApproval.value = false

  if (streamBubble.value) {
    const cleanedText = stripProtocolTextLeak(stripDirectiveTags(stripGeneratedArtifactMarkers(streamRaw.value))).trim()

    // Suppress sentinel tokens
    const SENTINELS = ['NO_REPLY', 'HEARTBEAT_OK']
    if (!wasAborted && SENTINELS.includes(cleanedText)) {
      streamBubble.value = false
      isStreaming.value = false
      streamRaw.value = ''
      streamSegments.value = []
      streamToolCalls.value = []
      streamArtifacts.value = []
      return
    }

    // Aborted with no output
    if (wasAborted && !cleanedText) {
      streamBubble.value = false
      isStreaming.value = false
      streamRaw.value = ''
      streamSegments.value = []
      streamToolCalls.value = []
      streamArtifacts.value = []
      return
    }

    if (!cleanedText && streamArtifacts.value.length === 0 && streamToolCalls.value.length === 0) {
      streamBubble.value = false
      isStreaming.value = false
      streamRaw.value = ''
      streamSegments.value = []
      streamToolCalls.value = []
      streamArtifacts.value = []
      return
    }

    // Record the message
    const historyToolCalls = streamToolCalls.value.map(streamToolCallToHistoryCall)
    const historyTimeline = streamTimelineSnapshot(cleanedText)
    messages.value.push({
      role: 'assistant',
      text: cleanedText,
      ts: new Date().toISOString(),
      artifacts: streamArtifacts.value.slice(),
      tool_calls: historyToolCalls,
      timeline: historyTimeline,
      interrupted: wasAborted || undefined,
    })
  }

  streamBubble.value = false
  isStreaming.value = false
  streamRaw.value = ''
  streamSegments.value = []
  streamToolCalls.value = []
  streamArtifacts.value = []
}

function resetStreamForRouterReplay() {
  streamRaw.value = ''
  streamSegments.value = []
  streamArtifacts.value = []
  streamToolCalls.value = []
  streamToolGroupSeq = 0
  streamBubble.value = true
  streamShowHeader.value = lastHeaderRole.value !== 'assistant'
  setStreamActivity('正在切换模型')
  renderDirty = false
  if (renderRafId) {
    clearTimeout(renderRafId)
    renderRafId = null
  }
}

function removeTrailingRouterStrips() {
  // No-op retained for back-compat. We no longer pop router strips on
  // router_control_replay — the next router_decision coalesces into the
  // existing strip so the selector slides via CSS transition.
}
void removeTrailingRouterStrips

function handleRouterControlReplay() {
  if (!isStreaming.value) startStreaming()
  pendingRouterDecision.value = null
  resetStreamForRouterReplay()
  // Do NOT remove the existing router strip — the next router_decision will
  // arrive immediately and we want to coalesce into the existing strip so
  // the selector slides via transition instead of remounting and replaying.
  resetStreamIdleTimer()
  scrollToBottom()
}

function appendDelta(text: string) {
  if (aborted.value) return
  if (!isStreaming.value) startStreaming()
  clearStreamActivity()
  streamRaw.value += text

  // Update or create text segment
  const lastSegment = streamSegments.value[streamSegments.value.length - 1]
  if (!lastSegment || lastSegment.type !== 'text') {
    streamSegments.value.push({ type: 'text', raw: text, html: '', dirty: true })
  } else {
    const seg = lastSegment
    seg.raw = (seg.raw || '') + text
    seg.dirty = true
  }

  // Debounced render — throttle to every 80ms to avoid re-parsing markdown on every token
  renderDirty = true
  if (!renderRafId) {
    renderRafId = setTimeout(flushRender, 80)
  }
}

function flushRender() {
  renderRafId = null
  if (!renderDirty) return

  for (const seg of streamSegments.value) {
    if (seg.type === 'text' && seg.dirty) {
      seg.html = renderMarkdown(seg.raw || '')
      seg.dirty = false
    }
  }

  renderDirty = false
  if (autoScroll.value) scrollToBottom()
}

function showThinkingIndicator() {
  if (streamBubble.value) {
    if (!streamHasVisibleOutput.value) setStreamActivity('正在组织下一步')
    return
  }
  if (thinkingVisible.value || thinkingDelayTimer) return
  thinkingStartTime = Date.now()
  thinkingDelayTimer = setTimeout(() => {
    thinkingDelayTimer = null
    if (streamBubble.value) return
    thinkingVisible.value = true
    updateThinkingText()
    thinkingTimer = setInterval(updateThinkingText, 1000)
  }, THINKING_DELAY_MS)
}

function updateThinkingText() {
  const elapsed = Date.now() - thinkingStartTime
  const seconds = Math.floor(elapsed / 1000)
  const verb = SQUILLA_VERBS[Math.floor(elapsed / SQUILLA_DWELL_MS) % SQUILLA_VERBS.length]
  thinkingText.value = `${verb} · ${seconds}s`
  if (seconds >= THINKING_TTL_MS / 1000) {
    hideThinkingIndicator()
    messages.value.push({ role: 'system', text: 'Still waiting for agent response...', ts: new Date().toISOString() })
  }
}

function hideThinkingIndicator() {
  if (thinkingDelayTimer) { clearTimeout(thinkingDelayTimer); thinkingDelayTimer = null }
  if (thinkingTimer) { clearInterval(thinkingTimer); thinkingTimer = null }
  thinkingVisible.value = false
}

function resetStreamIdleTimer() {
  clearStreamIdleTimer()
  if (!isStreaming.value || streamIdlePausedForApproval.value) return
  streamIdleTimer.value = setTimeout(() => {
    if (isStreaming.value && !streamIdlePausedForApproval.value) {
      endStreaming()
      const seconds = Math.round(streamIdleTimeoutMs.value / 1000)
      messages.value.push({ role: 'error', text: `Response timed out -- no events received for ${seconds}s`, ts: new Date().toISOString() })
    }
  }, streamIdleTimeoutMs.value)
}

function clearStreamIdleTimer() {
  if (streamIdleTimer.value) { clearTimeout(streamIdleTimer.value); streamIdleTimer.value = null }
}

function scrollToBottom() {
  nextTick(() => {
    if (threadRef.value) {
      threadRef.value.scrollTop = threadRef.value.scrollHeight
    }
  })
}

function appendRouterDecision(payload: RouterDecisionPayload, decision = normalizeRouterDecision(payload)) {
  if (!decision) return
  const messageId = payload?.stream_seq
    ? `router-${sessionKey.value}-${payload.stream_seq}`
    : `router-${sessionKey.value}-${Date.now()}`
  const last = messages.value[messages.value.length - 1]
  if (last?.messageId === messageId) return
  // Coalesce router decisions within the same turn — when the model makes a
  // tool call that re-routes (e.g. user asks to switch models), update the
  // turn's existing strip in place AND mark it settled so the strip's
  // selector slides via CSS transition instead of replaying the keyframes.
  if (isStreaming.value) {
    for (let i = messages.value.length - 1; i >= 0; i--) {
      const m = messages.value[i]
      if (m.role === 'user') break
      if (m.role === 'router' && m.provenanceKind === 'router_decision') {
        m.routerDecision = decision
        m.messageId = messageId
        m.ts = new Date().toISOString()
        ;(m as any).routerSettled = true
        scrollToBottom()
        return
      }
    }
  }
  messages.value.push({
    role: 'router',
    text: '',
    ts: new Date().toISOString(),
    routerDecision: decision,
    provenanceKind: 'router_decision',
    messageId,
  })
  scrollToBottom()
}

function queueRouterDecision(payload: RouterDecisionPayload) {
  const decision = normalizeRouterDecision(payload)
  if (!decision) return
  if (isStreaming.value && streamBubble.value && !streamHasVisibleOutput.value) {
    const model = shortModelName(decision.model || decision.routed_model || '')
    setStreamActivity(model ? `模型路由完成 · ${model}` : '模型路由完成')
  }
  // Show the router strip immediately so the user sees which model was picked
  // before the response starts streaming. Keep the pending ref for the
  // abort/clear path, but the bubble is already on screen.
  pendingRouterDecision.value = { payload, decision }
  appendRouterDecision(payload, decision)
}

function flushPendingRouterDecision() {
  const pending = pendingRouterDecision.value
  if (!pending) return
  pendingRouterDecision.value = null
  appendRouterDecision(pending.payload, pending.decision)
}

function clearPendingRouterDecision() {
  pendingRouterDecision.value = null
}

function onThreadScroll() {
  if (!threadRef.value) return
  const gap = threadRef.value.scrollHeight - threadRef.value.scrollTop - threadRef.value.clientHeight
  autoScroll.value = gap < 60
}

/* ── Tool calls ────────────────────────────────────────────────────── */

function toolCallGroups(calls: StreamToolCall[] | undefined, ownerKey: string): ToolCallGroup[] {
  if (!calls?.length) return []
  const groups: ToolCallGroup[] = []

  calls.forEach((call, index) => {
    const operationKey = toolOperationKey(call.name)
    const renderKey = `${ownerKey}:tool:${call.toolId || call.name || index}:${index}`
    const last = groups[groups.length - 1]
    if (!last || last.operationKey !== operationKey || (call.groupId && last.groupId !== call.groupId)) {
      groups.push({
        groupId: call.groupId || `${ownerKey}:tool-group:${operationKey}:${groups.length}`,
        operationKey,
        label: toolActionLabel(call.name),
        iconName: toolIconName(call.name),
        calls: [],
        secondary: '',
        isRunning: false,
        isError: false,
        status: '',
      })
    }

    groups[groups.length - 1].calls.push({ ...call, renderKey })
  })

  groups.forEach(group => {
    group.isRunning = group.calls.some(tc => tc.isRunning)
    group.isError = group.calls.some(tc => tc.isError || tc.status === 'error')
    group.status = group.isError ? 'error' : (group.calls.every(tc => tc.status === 'success') ? 'success' : '')
    group.secondary = group.calls.length === 1
      ? toolSecondaryText(group.calls[0])
      : summarizeToolGroup(group.calls)
  })

  return groups
}

function summarizeToolGroup(calls: StreamToolCall[]): string {
  const running = calls.filter(tc => tc.isRunning).length
  const done = calls.filter(tc => tc.status === 'success').length
  const failed = calls.filter(tc => tc.status === 'error').length
  const sample = calls.map(tc => toolSecondaryText(tc)).find(Boolean)
  const parts = []
  if (running) parts.push(`${running} 个运行中`)
  if (done) parts.push(`${done} 个完成`)
  if (failed) parts.push(`${failed} 个失败`)
  if (sample) parts.push(sample)
  return parts.join(' · ')
}

function isToolGroupOpen(groupId: string): boolean {
  return openToolGroups.value.has(groupId)
}

function toggleToolGroup(groupId: string) {
  const next = new Set(openToolGroups.value)
  next.has(groupId) ? next.delete(groupId) : next.add(groupId)
  openToolGroups.value = next
}

function isToolItemOpen(itemId: string): boolean {
  return openToolItems.value.has(itemId)
}

function toggleToolItem(itemId: string) {
  const next = new Set(openToolItems.value)
  next.has(itemId) ? next.delete(itemId) : next.add(itemId)
  openToolItems.value = next
}

function ensureStreamToolCall(payload: any, options: { running: boolean }): StreamToolCall | null {
  if (!payload) return null
  const name = normalizeToolName(payload)
  if (!name) return null
  if (isInternalToolName(name)) return null
  if (!isStreaming.value) startStreaming()
  const input = normalizeToolInputText(payload)
  const toolId = payload.tool_use_id || payload.toolUseId || payload.id || `${name}:${payload.stream_seq || Date.now()}`

  const existing = streamToolCalls.value.find(tc => tc.toolId === toolId)
  if (existing) {
    if (input) {
      existing.inputRaw = input
      existing.inputPreview = truncate(input, 200)
      existing.displayName = toolDisplayName(existing.name, input)
    }
    return existing
  }

  const operationKey = toolOperationKey(name)
  const lastSegment = streamSegments.value[streamSegments.value.length - 1]
  const groupId = lastSegment?.type === 'tool-group' && lastSegment.operationKey === operationKey && lastSegment.groupId
    ? lastSegment.groupId
    : `stream:tool-group:${operationKey}:${streamToolGroupSeq++}`

  if (lastSegment?.type !== 'tool-group' || lastSegment.groupId !== groupId) {
    streamSegments.value.push({ type: 'tool-group', groupId, operationKey })
  }

  const call: StreamToolCall = {
    toolId,
    name,
    displayName: toolDisplayName(name, input),
    groupId,
    inputRaw: input,
    inputPreview: truncate(input, 200),
    isRunning: options.running,
    status: '',
    isError: false,
    result: '',
    resultPreview: '',
    isOpen: false,
  }
  streamToolCalls.value.push(call)
  return call
}

function appendToolCall(payload: ToolUsePayload) {
  const tc = ensureStreamToolCall(payload, { running: true })
  if (!tc) return

  clearStreamActivity()
  scrollToBottom()
}

function appendToolDelta(payload: ToolDeltaPayload) {
  if (!payload || aborted.value) return
  if (isStreaming.value && streamBubble.value && !streamHasVisibleOutput.value) {
    setStreamActivity('正在接收工具参数')
  }
  const toolId = payload.tool_use_id || payload.toolUseId || payload.id || ''
  const fragment = payload.json_fragment ?? payload.jsonFragment ?? payload.fragment ?? ''
  const fragmentText = typeof fragment === 'string' ? fragment : String(fragment || '')
  if (!toolId || !fragmentText) return

  const existing = streamToolCalls.value.find(t => t.toolId === toolId)
  const tc = existing || ensureStreamToolCall(payload, { running: true })
  if (!tc) return
  clearStreamActivity()

  const nextInput = `${tc.inputRaw || ''}${fragmentText}`
  tc.inputRaw = nextInput
  if (!isEmptyToolPreview(nextInput)) {
    tc.inputPreview = truncate(nextInput, 200)
    tc.displayName = toolDisplayName(tc.name, nextInput)
  }
  scrollToBottom()
}

function appendToolResult(payload: ToolResultPayload) {
  if (!payload) return
  const name = normalizeToolName(payload)
  if (name && isInternalToolName(name)) return
  if (!isStreaming.value) startStreaming()
  const raw = payload.result || payload.content || payload.output || ''
  const content = typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2)
  const toolId = payload.tool_use_id || payload.toolUseId || payload.id || ''

  const tc = streamToolCalls.value.find(t => t.toolId === toolId) || ensureStreamToolCall(payload, { running: false })
  if (tc) {
    clearStreamActivity()
    const input = normalizeToolInputText(payload)
    if (input) {
      tc.inputRaw = input
      tc.inputPreview = truncate(input, 200)
      tc.displayName = toolDisplayName(tc.name, input)
    }
    tc.isRunning = false
    tc.status = toolResultIsError(payload) ? 'error' : 'success'
    tc.isError = toolResultIsError(payload)
    tc.result = content
    tc.resultPreview = truncate(content, 200)
  }

  scrollToBottom()
}

function streamToolCallToHistoryCall(tc: StreamToolCall): any {
  return {
    id: tc.toolId,
    toolId: tc.toolId,
    tool_use_id: tc.toolId,
    name: tc.name,
    tool_name: tc.name,
    input: tc.inputRaw || tc.inputPreview,
    groupId: tc.groupId,
    result: tc.result,
    is_error: tc.isError,
    isError: tc.isError,
    execution_status: tc.status ? { status: tc.status } : undefined,
  }
}

function streamTimelineSnapshot(fallbackText = ''): any[] {
  const segments = streamSegments.value
    .map((seg) => {
      if (seg.type === 'text') {
        const raw = String(seg.raw || '')
        return raw ? { type: 'text', raw } : null
      }
      if (seg.type === 'tool-group') {
        return {
          type: 'tool-group',
          groupId: seg.groupId,
          operationKey: seg.operationKey,
        }
      }
      return null
    })
    .filter(Boolean) as any[]
  if (segments.length === 0 && fallbackText) return [{ type: 'text', raw: fallbackText }]
  return segments
}

function toolDisplayName(name: string, input: any): string {
  if (name === 'publish_artifact') {
    const inputObj = typeof input === 'string' ? (() => { try { return JSON.parse(input) } catch { return null } })() : input
    const target = inputObj?.name || inputObj?.path
    if (target) return `${name} - ${target.split(/[\\/]+/).filter(Boolean).pop() || target}`
  }
  return name
}

function toolIconName(name: string): IconName {
  const n = String(name || '').toLowerCase()
  if (n.includes('search') || n.includes('google') || n.includes('bing')) return 'search'
  if (n.includes('fetch') || n.includes('http') || n.includes('curl') || n.includes('wget')) return 'monitor'
  if (n.includes('python') || n === 'py' || n.includes('exec') || n.includes('bash') || n.includes('shell')) return 'config'
  if (n.includes('write') || n.includes('edit') || n.includes('patch')) return 'edit'
  if (n.includes('read') || n.includes('file') || n.includes('cat') || n.includes('list') || n === 'ls' || n.includes('glob') || n.includes('find')) return 'logs'
  if (n.includes('artifact') || n.includes('download')) return 'download'
  if (n.includes('memory')) return 'clock'
  return 'gear'
}

function toolOperationKey(name: string): string {
  const n = String(name || '').toLowerCase()
  if (n.includes('web_search') || n === 'search' || n.includes('google') || n.includes('bing')) return 'web.search'
  if (n.includes('web_fetch') || n.includes('http') || n.includes('fetch') || n.includes('curl') || n.includes('wget')) return 'web.read'
  if (n.includes('python') || n === 'py') return 'code.python'
  if (n.includes('bash') || n.includes('shell') || n.includes('exec')) return 'command.run'
  if (n.includes('write')) return 'file.write'
  if (n.includes('edit') || n.includes('patch')) return 'file.edit'
  if (n.includes('read') || n.includes('cat') || n.includes('list') || n === 'ls' || n.includes('glob') || n.includes('find') || n.includes('file')) return 'file.inspect'
  if (n.includes('publish_artifact') || n.includes('artifact')) return 'artifact.create'
  if (n.includes('memory')) return 'memory.search'
  return `tool.${n.replace(/[^a-z0-9]+/g, '.') || 'unknown'}`
}

function toolActionLabel(name: string): string {
  const key = toolOperationKey(name)
  if (key === 'web.search') return '搜索网页'
  if (key === 'web.read') return '读取网页'
  if (key === 'code.python') return '运行 Python 代码'
  if (key === 'command.run') return '运行命令'
  if (key === 'file.inspect') return '查看文件'
  if (key === 'file.write') return '写入文件'
  if (key === 'file.edit') return '修改文件'
  if (key === 'artifact.create') return '生成文件'
  if (key === 'memory.search') return '检索记忆'
  return name.replace(/[_-]+/g, ' ')
}

function toolSecondaryText(tc: StreamToolCall): string {
  const source = String(tc.inputPreview || tc.resultPreview || '').replace(/\s+/g, ' ').trim()
  if (isEmptyToolPreview(source)) return ''
  return truncate(source.replace(/^"|"$/g, ''), 86)
}

function toolStatusText(tc: StreamToolCall): string {
  if (tc.isRunning) return '运行中'
  if (tc.status === 'error') return '失败'
  const count = toolResultCount(tc.result)
  if (count !== null) return `${count} 个结果`
  if (tc.status === 'success') return '完成'
  return '等待'
}

function toolGroupStatusText(group: ToolCallGroup): string {
  if (group.isRunning) return '运行中'
  if (group.isError) return '失败'
  const counts = group.calls.map(tc => toolResultCount(tc.result)).filter((n): n is number => n !== null)
  if (counts.length && group.calls.length === 1) return `${counts[0]} 个结果`
  if (counts.length) return `${counts.reduce((sum, n) => sum + n, 0)} 个结果`
  if (group.status === 'success') return '完成'
  return '等待'
}

function toolResultCount(raw: string): number | null {
  const text = String(raw || '').trim()
  if (!text) return null
  const match = /(?:^|\D)(\d{1,4})\s*(?:results?|结果)(?:\D|$)/i.exec(text)
  if (match) return Number(match[1])
  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) return parsed.length
    for (const key of ['results', 'items', 'data', 'matches']) {
      if (Array.isArray(parsed?.[key])) return parsed[key].length
    }
  } catch {}
  return null
}

function toolResultIsError(payload: any): boolean {
  const status = payload?.execution_status || payload?.executionStatus
  if (status && typeof status.status === 'string') {
    return ['error', 'timeout', 'cancelled'].includes(status.status)
  }
  return !!(payload?.is_error || payload?.isError || payload?.error)
}

function showToolResultModal(content: string, title = 'Tool Result') {
  toolResultModal.value = { open: true, title, content }
}

function appendArtifact(payload: ArtifactPayload) {
  if (!payload) return
  clearStreamActivity()
  streamArtifacts.value.push(payload)
  scrollToBottom()
}

/* ── Send ──────────────────────────────────────────────────────────── */

async function onSend() {
  let text = inputText.value.trim()
  let hasPayload = text || pendingAttachments.value.length > 0
  let isLiteralSlash = false

  if (hasPendingAttachmentWork()) {
    console.warn('Wait for file attachment processing to finish')
    return
  }

  if (text.startsWith('//')) {
    isLiteralSlash = true
    text = text.slice(1)
    hasPayload = text || pendingAttachments.value.length > 0
  }

  // While streaming, enqueue
  if (isStreaming.value || isCompactInFlightForCurrentSession()) {
    if (!isLiteralSlash && text.startsWith('/')) {
      console.warn(`Wait for ${isCompactInFlightForCurrentSession() ? 'context compaction' : 'the current response'} before running ${text.split(/\s+/, 1)[0]}.`)
      return
    }
    if (!hasPayload) return
    enqueuePendingInput(text)
    return
  }

  if (!isLiteralSlash && text.startsWith('/')) {
    const handled = await executeSlashCommand(text)
    if (handled) return
  }

  if (!hasPayload || !sessionKey.value) return

  aborted.value = false
  closeSlashMenu()

  const now = new Date().toISOString()
  const userText = text
  messages.value.push({ role: 'user', text: userText, ts: now })
  autoScroll.value = true
  scrollToBottom()

  // Build RPC params
  const params: ChatSendParams = { message: text || 'Describe these attachments', sessionKey: sessionKey.value }
  const elevated = normalizeElevatedMode(elevatedMode.value)
  if (elevated) params._source = { elevated }
  if (pendingSessionIntent.value) {
    params.intent = pendingSessionIntent.value
    pendingSessionIntent.value = null
  }
  if (pendingAttachments.value.length > 0) {
    params.displayText = userText
    params.attachments = pendingAttachments.value.map((a) => {
      if (a.kind === 'staged') return { type: a.mime, file_uuid: a.file_uuid, mime: a.mime, name: a.name }
      return { type: a.mime || 'image/png', data: a.data, mime: a.mime, name: a.name }
    })
  }

  inputText.value = ''
  autoResizeTextarea()
  pendingAttachments.value = []

  startStreaming()
  showThinkingIndicator()

  try {
    const res = await rpc.call<ChatSendResponse>('chat.send', params)
    if (res?.sessionKey && res.sessionKey !== sessionKey.value) persistSession(res.sessionKey)
  } catch (err: any) {
    endStreaming()
    messages.value.push({ role: 'error', text: 'Send failed: ' + err.message, ts: new Date().toISOString() })
  }
}

function onStop() {
  if (!isStreaming.value) return
  aborted.value = true
  rpc.call('chat.abort', { sessionKey: sessionKey.value }).catch(() => {})
  endStreaming({ reason: 'aborted' })
  const recovered = popAllPendingIntoComposer()
  console.warn(recovered ? 'Stopped -- pending recovered to input' : 'Stopped')
}

/* ── Attachments ───────────────────────────────────────────────────── */

function onFileInputChange(e: Event) {
  const target = e.target as HTMLInputElement
  if (target.files) {
    Array.from(target.files).forEach(addAttachment)
    target.value = ''
  }
}

function onThreadDrop(e: DragEvent) {
  threadDragOver.value = false
  if (e.dataTransfer?.files) {
    Array.from(e.dataTransfer.files).forEach(addAttachment)
  }
}

function addAttachment(file: File) {
  const mime = resolveAttachmentMime(file)
  if (!isAllowedAttachmentMime(mime)) {
    console.warn(`Unsupported file: ${file.name} (${mime})`)
    return
  }
  const hardCap = attachmentHardCapBytes(mime)
  if (file.size > hardCap) {
    console.warn(`File too large: ${file.name}`)
    return
  }

  const localId = nextAttachmentId.value++

  if (file.size <= INLINE_THRESHOLD_BYTES) {
    pendingAttachments.value.push({ kind: 'inline_pending', local_id: localId, name: file.name, mime, size: file.size })
    const reader = new FileReader()
    reader.onload = (e) => {
      const dataUrl = e.target?.result as string
      const b64 = dataUrl?.split(',')[1] || ''
      const idx = pendingAttachments.value.findIndex(a => a.local_id === localId)
      if (idx >= 0) {
        pendingAttachments.value[idx] = { kind: 'inline', local_id: localId, name: file.name, mime, size: file.size, data: b64, dataUrl }
      }
    }
    reader.onerror = () => {
      removeAttachmentByLocalId(localId)
      console.warn(`Could not read file: ${file.name}`)
    }
    reader.readAsDataURL(file)
    return
  }

  if (!canStageAttachmentMime(mime)) {
    console.warn(`File too large: ${file.name}`)
    return
  }

  pendingAttachments.value.push({ kind: 'uploading', local_id: localId, name: file.name, mime, size: file.size })
  uploadAttachmentStaged(file, mime, localId).catch((err) => {
    removeAttachmentByLocalId(localId)
    console.warn(`Upload failed for ${file.name}:`, err?.message || err)
  })
}

async function uploadAttachmentStaged(file: File, mime: string, localId: number) {
  const form = new FormData()
  form.append('file', file, file.name)
  form.append('mime', mime)
  const response = await fetch('/api/v1/files/upload', {
    method: 'POST',
    body: form,
    credentials: 'same-origin',
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(`HTTP ${response.status} ${detail}`)
  }
  const result = await response.json()
  const idx = pendingAttachments.value.findIndex(a => a.local_id === localId)
  if (idx >= 0) {
    pendingAttachments.value[idx] = { kind: 'staged', local_id: localId, name: file.name, mime, size: file.size, file_uuid: result.file_uuid }
  }
}

function removeAttachment(index: number) {
  pendingAttachments.value.splice(index, 1)
}

function removeAttachmentByLocalId(localId: number) {
  pendingAttachments.value = pendingAttachments.value.filter(a => a.local_id !== localId)
}

function hasPendingAttachmentWork(): boolean {
  return pendingAttachments.value.some(a => a.kind === 'inline_pending' || a.kind === 'uploading')
}

/* ── Pending queue ─────────────────────────────────────────────────── */

function enqueuePendingInput(text: string) {
  if (pendingQueue.value.length >= MAX_PENDING) {
    console.warn(`Pending queue full (${MAX_PENDING})`)
    return false
  }
  pendingQueue.value.push({ text, attachments: pendingAttachments.value.map(a => ({ ...a })), intent: pendingSessionIntent.value })
  inputText.value = ''
  pendingAttachments.value = []
  pendingSessionIntent.value = null
  autoResizeTextarea()
  console.info(`Queued (${pendingQueue.value.length}/${MAX_PENDING})`)
  return true
}

function removePendingChip(index: number) {
  pendingQueue.value.splice(index, 1)
}

function clearPendingQueue() {
  clearPendingDrainAfterTerminalTimer()
  pendingQueue.value = []
}

function popPendingTail() {
  if (pendingQueue.value.length === 0) return false
  const tail = pendingQueue.value.pop()
  inputText.value = tail?.text || ''
  pendingAttachments.value = tail?.attachments || []
  pendingSessionIntent.value = tail?.intent || null
  autoResizeTextarea()
  return true
}

function popAllPendingIntoComposer(): boolean {
  clearPendingDrainAfterTerminalTimer()
  if (!composerRef.value || pendingQueue.value.length === 0) return false
  const queuedTexts = pendingQueue.value.map(p => p.text).filter(Boolean)
  const queuedAttachments = pendingQueue.value.flatMap(p => p.attachments || [])
  const headIntent = pendingQueue.value[0]?.intent
  const current = inputText.value || ''
  const joined = [current, ...queuedTexts].filter(Boolean).join('\n')
  pendingQueue.value = []
  inputText.value = joined
  pendingAttachments.value = [...pendingAttachments.value, ...queuedAttachments]
  pendingSessionIntent.value = pendingSessionIntent.value || headIntent || null
  autoResizeTextarea()
  inputHistoryIdx.value = null
  inputHistoryDraft.value = ''
  return true
}

function drainQueueHead() {
  clearPendingDrainAfterTerminalTimer()
  if (pendingQueue.value.length === 0) return
  const head = pendingQueue.value.shift()
  inputText.value = head?.text || ''
  pendingAttachments.value = head?.attachments || []
  pendingSessionIntent.value = head?.intent || null
  nextTick(() => onSend())
}

function schedulePendingDrainAfterTerminal() {
  if (pendingQueue.value.length === 0) return
  clearPendingDrainAfterTerminalTimer()
  pendingDrainTimer = setTimeout(() => {
    pendingDrainTimer = null
    if (isStreaming.value || isCompactInFlightForCurrentSession() || pendingQueue.value.length === 0) return
    drainQueueHead()
  }, 50)
}

function clearPendingDrainAfterTerminalTimer() {
  if (pendingDrainTimer) { clearTimeout(pendingDrainTimer); pendingDrainTimer = null }
}

/* ── Compact ───────────────────────────────────────────────────────── */

function isCompactInFlightForCurrentSession(): boolean {
  if (!compactInFlight.value) return false
  return !compactInFlightKey.value || compactInFlightKey.value === sessionKey.value
}

function setCompactInFlight(active: boolean, key = sessionKey.value) {
  compactInFlight.value = active
  compactInFlightKey.value = active ? String(key || sessionKey.value || '') : ''
}

function hideCompactStatus() {
  compactStatus.value = { visible: false, message: '', detail: '', tone: 'info', isBusy: false }
}

function showCompactStatus(status: string, message: string, options: { tone?: string; detail?: string; dismissMs?: number } = {}) {
  compactStatus.value = {
    visible: true,
    message,
    detail: options.detail || '',
    tone: options.tone || 'info',
    isBusy: status === 'started',
  }
  if (options.dismissMs && options.dismissMs > 0) {
    setTimeout(hideCompactStatus, options.dismissMs)
  }
}

/* ── Slash commands ────────────────────────────────────────────────── */

function slashCommandKey(value: string): string {
  const raw = String(value || '').trim().split(/\s+/, 1)[0].toLowerCase()
  if (!raw) return ''
  return raw.startsWith('/') ? raw : '/' + raw
}

function normalizeSlashCommand(cmd: any) {
  const name = cmd?.name || cmd?.cmd || ''
  return { ...cmd, name, cmd: name, label: cmd?.label || name, desc: cmd?.description || cmd?.desc || cmd?.usage || '', aliases: Array.isArray(cmd?.aliases) ? cmd.aliases : [] }
}

async function loadSlashCommands() {
  try {
    await rpc.waitForConnection()
    const res = await rpc.call('commands.list_for_surface', { surface: 'web_chat' }) as any
    slashCmds.value = (Array.isArray(res?.commands) ? res.commands : []).map(normalizeSlashCommand)
    slashCatalogLoaded.value = true
  } catch {
    slashCmds.value = []
    slashCatalogLoaded.value = false
  }
}

function handleSlashInput() {
  const val = inputText.value
  if (val.startsWith('//')) { closeSlashMenu(); return }
  if (val.startsWith('/') && !val.includes(' ')) {
    const query = val.slice(1).toLowerCase()
    filteredSlashCmds.value = slashCmds.value.filter(c => c.cmd.slice(1).startsWith(query))
    if (filteredSlashCmds.value.length > 0) {
      slashOpen.value = true
      slashIdx.value = 0
      return
    }
  }
  closeSlashMenu()
}

function closeSlashMenu() {
  slashOpen.value = false
  filteredSlashCmds.value = []
}

function selectSlashCmd(cmd: any, _args = '') {
  closeSlashMenu()
  inputText.value = ''
  autoResizeTextarea()

  const action = cmd?.execution?.action || cmd.cmd || cmd.name
  switch (action) {
    case 'new_chat':
    case '/new':
      newSession()
      break
    case 'reset_session':
    case 'sessions.reset':
    case '/reset':
      rpc.call('sessions.reset', { key: sessionKey.value })
        .then(() => {
          resetSessionRuntimeState()
          messages.value = []
          clearPendingDrainAfterTerminalTimer()
          setCompactInFlight(false)
          hideCompactStatus()
          pendingQueue.value = []
          contextStatus.value = null
          console.info('Session reset')
        })
        .catch((err: any) => console.warn('Reset failed:', err.message))
      break
    case 'compact_context':
    case 'sessions.contextCompact':
    case '/compact': {
      const compactKey = sessionKey.value
      setCompactInFlight(true, compactKey)
      showCompactStatus('started', 'Compacting context...', { tone: 'info' })
      rpc.call('sessions.contextCompact', { key: compactKey })
        .then((_result: any) => {
          if (compactKey !== sessionKey.value) return
          showCompactStatus('completed', 'Context compacted', { tone: 'ok', dismissMs: 5000 })
        })
        .catch((err: any) => {
          if (compactKey !== sessionKey.value) return
          showCompactStatus('failed', 'Compact failed: ' + err.message, { tone: 'err', dismissMs: 10000 })
        })
      break
    }
    case 'usage_status':
    case 'usage.status':
    case '/usage':
      rpc.call('usage.status')
        .then((result: any) => {
          const totals = result?.totals || {}
          const tokens = Number(result?.totalTokens ?? result?.total_tokens ?? totals.tokens ?? 0)
          console.info(`Usage: ${tokens.toLocaleString()} tokens`)
        })
        .catch((err: any) => console.warn('Usage failed:', err.message))
      break
  }
}

async function executeSlashCommand(text: string): Promise<boolean> {
  if (!slashCatalogLoaded.value) await loadSlashCommands()
  const [cmdText, ...rest] = text.trim().split(/\s+/)
  const cmd = slashCmds.value.find(c => slashCommandKey(c.name) === slashCommandKey(cmdText))
  if (!cmd) {
    closeSlashMenu()
    console.warn('Unsupported command:', cmdText)
    return true
  }
  selectSlashCmd(cmd, rest.join(' '))
  return true
}

/* ── History ───────────────────────────────────────────────────────── */

function scheduleHistorySync() {
  if (historySyncTimer) clearTimeout(historySyncTimer)
  historySyncTimer = setTimeout(() => {
    historySyncTimer = null
    loadHistory()
  }, 50)
}

async function loadHistory() {
  if (!sessionKey.value) return
  const key = sessionKey.value
  try {
    await rpc.waitForConnection()
    if (key !== sessionKey.value) return
    const data = await rpc.call<ChatHistoryResponse>('chat.history', { sessionKey: key })
    if (key !== sessionKey.value) return
    const msgs = data.messages || []

    if (msgs.length === 0) {
      messages.value = []
      lastHeaderRole.value = ''
      lastHeaderDay.value = ''
      return
    }

    messages.value = msgs.map(msg => ({
      role: msg.role || 'assistant',
      text: msg.role === 'user' ? stripTimePrefix(msg.text || '') : msg.text || '',
      ts: msg.timestamp || msg.ts || null,
      routerDecision: msg.router_decision || msg.routerDecision || null,
      artifacts: msg.artifacts || [],
      tool_calls: msg.tool_calls || [],
      timeline: msg.timeline || [],
      attachments: msg.attachments || [],
      provenanceKind: msg.provenance_kind || '',
      provenanceSourceSessionKey: msg.provenance_source_session_key || '',
      provenanceSourceTool: msg.provenance_source_tool || '',
      usage: msg.usage || msg.turn_usage || null,
      model: msg.model || undefined,
      input: msg.input || msg.input_tokens || undefined,
      output: msg.output || msg.output_tokens || undefined,
      messageId: msg.message_id || msg.id || '',
      restoredFromHistory: true,
    }))

    lastHeaderRole.value = ''
    lastHeaderDay.value = ''

    nextTick(() => scrollToBottom())
  } catch {
    // History endpoint may not exist yet
  }
}

/* ── Message actions ───────────────────────────────────────────────── */

function copyMessage(msg: RenderedMessage) {
  const text = msg.text || ''
  navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    document.body.appendChild(ta)
    ta.select()
    try { document.execCommand('copy') } catch {}
    ta.remove()
  })
}

function regenerateMessage(index: number) {
  if (isStreaming.value) {
    console.warn('Wait for the current response to finish')
    return
  }
  // Find the user message before this assistant message
  let userMsgIndex = -1
  for (let i = index - 1; i >= 0; i--) {
    if (renderedMessages.value[i]?.role === 'user') {
      userMsgIndex = i
      break
    }
  }
  if (userMsgIndex < 0) {
    console.warn('No previous message to regenerate')
    return
  }
  // Remove all messages from the user message onward
  const userText = messages.value[userMsgIndex]?.text || ''
  messages.value = messages.value.slice(0, userMsgIndex)
  inputText.value = userText
  autoResizeTextarea()
  nextTick(() => onSend())
}

function editMessage(index: number) {
  if (isStreaming.value) {
    console.warn('Wait for the current response to finish')
    return
  }
  // Find the actual message index in messages array
  let msgIndex = -1
  let userCount = 0
  for (let i = 0; i < messages.value.length; i++) {
    if (messages.value[i].role === 'user') {
      if (userCount === index) {
        msgIndex = i
        break
      }
      userCount++
    }
  }
  if (msgIndex < 0) return
  const text = messages.value[msgIndex].text || ''
  messages.value = messages.value.slice(0, msgIndex)
  inputText.value = text
  autoResizeTextarea()
  composerRef.value?.focusTextarea()
}

/* ── Textarea ──────────────────────────────────────────────────────── */

function onTextareaInput() {
  autoResizeTextarea()
  handleSlashInput()
}

function autoResizeTextarea() {
  composerRef.value?.resizeTextarea()
}

function onTextareaKeydown(e: KeyboardEvent) {
  if (composing.value || e.isComposing || (e as any).keyCode === 229) return

  // Slash menu navigation
  if (slashOpen.value) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      slashIdx.value = Math.min(slashIdx.value + 1, filteredSlashCmds.value.length - 1)
      return
    }
    if (e.key === 'ArrowUp') {
      e.preventDefault()
      slashIdx.value = Math.max(slashIdx.value - 1, 0)
      return
    }
    if (e.key === 'Enter' || e.key === 'Tab') {
      if (filteredSlashCmds.value.length > 0) {
        e.preventDefault()
        selectSlashCmd(filteredSlashCmds.value[slashIdx.value])
        return
      }
    }
    if (e.key === 'Escape') {
      e.preventDefault()
      closeSlashMenu()
      return
    }
  }

  // ESC: clear input when not streaming
  if (e.key === 'Escape' && !isStreaming.value && pendingQueue.value.length === 0 && inputText.value) {
    e.preventDefault()
    inputText.value = ''
    autoResizeTextarea()
    return
  }

  // Alt+Up: pop pending tail
  if (e.key === 'ArrowUp' && e.altKey && pendingQueue.value.length > 0) {
    e.preventDefault()
    popPendingTail()
    return
  }

  // Alt+Down: enqueue current
  if (e.key === 'ArrowDown' && e.altKey && inputText.value && pendingQueue.value.length < MAX_PENDING) {
    e.preventDefault()
    enqueuePendingInput(inputText.value)
    return
  }

  // Up/Down history
  if (e.key === 'ArrowUp' && !e.altKey && !e.shiftKey && (!inputText.value || inputHistoryIdx.value !== null)) {
    if (cycleHistory(-1)) { e.preventDefault(); return }
  }
  if (e.key === 'ArrowDown' && !e.altKey && !e.shiftKey && inputHistoryIdx.value !== null) {
    if (cycleHistory(1)) { e.preventDefault(); return }
  }

  // Enter to send
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    onSend()
  }
}

function cycleHistory(dir: number): boolean {
  const history = messages.value.filter(m => m.role === 'user' && typeof m.text === 'string').map(m => m.text)
  if (history.length === 0) return false

  if (dir < 0) {
    if (inputHistoryIdx.value === null) {
      inputHistoryDraft.value = inputText.value || ''
      inputHistoryIdx.value = history.length - 1
    } else {
      inputHistoryIdx.value = Math.max(0, inputHistoryIdx.value - 1)
    }
    inputText.value = history[inputHistoryIdx.value]
    autoResizeTextarea()
    return true
  }

  if (inputHistoryIdx.value === null) return false
  const next = inputHistoryIdx.value + 1
  if (next >= history.length) {
    inputHistoryIdx.value = null
    inputText.value = inputHistoryDraft.value
    inputHistoryDraft.value = ''
  } else {
    inputHistoryIdx.value = next
    inputText.value = history[next]
  }
  autoResizeTextarea()
  return true
}

/* ── Savings / Token widget ────────────────────────────────────────── */

function resetSavingsPopupCooldown() {
  savingsPopupLastTs.value = 0
  lastSavingsPopupIdentity.value = ''
}

function saveWidgetState() {
  if (!appStore.features.tokenViz) return
  if (!sessionKey.value) return
  try {
    localStorage.setItem('opensquilla-widget:' + sessionKey.value, JSON.stringify({
      input: usageAccum.value.input, output: usageAccum.value.output,
      cost: usageAccum.value.cost, model: usageModel.value,
    }))
  } catch { /* ignore */ }
}

function restoreWidgetState() {
  if (!appStore.features.tokenViz) return
  if (!sessionKey.value) return
  try {
    const raw = localStorage.getItem('opensquilla-widget:' + sessionKey.value)
    if (raw) {
      const d = JSON.parse(raw)
      usageAccum.value.input = d.input || 0
      usageAccum.value.output = d.output || 0
      usageAccum.value.cost = d.cost || null
      usageModel.value = d.model || ''
    }
  } catch { /* ignore */ }
}

async function loadCurrentSessionUsage() {
  if (!sessionKey.value) return
  try {
    await rpc.waitForConnection()
    const usage = await rpc.call('usage.status', { sessionKey: sessionKey.value }) as any
    const sessions = usage?.sessions || []
    const current = sessions.find((s: any) => (s.session || s.sessionKey || s.key) === sessionKey.value)
    if (current) {
      usageAccum.value.input = Number(current.input_tokens || current.inputTokens || 0)
      usageAccum.value.output = Number(current.output_tokens || current.outputTokens || 0)
      usageAccum.value.cacheRead = Number(current.cache_read_tokens || current.cacheReadTokens || 0)
      usageAccum.value.cacheWrite = Number(current.cache_write_tokens || current.cacheWriteTokens || 0)
      const costVal = Number(current.cost_usd || current.costUsd || 0)
      usageAccum.value.cost = costVal > 0 ? costVal : null
      usageModel.value = current.model || ''
      saveWidgetState()
    }
  } catch { /* ignore */ }
}

/* ── Feature toggles ───────────────────────────────────────────────── */

async function loadFeatureToggles() {
  try {
    await rpc.waitForConnection()
    const cfg = await rpc.call('config.get') as any
    const routerOn = (cfg?.squilla_router?.enabled ?? false) && cfg?.squilla_router?.rollout_phase === 'full'
    routerEnabled.value = routerOn
    toolbarState.value.router = routerOn
    const tiers = cfg?.squilla_router?.tiers
    const tierKeys: string[] = []
    const tierModels: Record<string, string> = {}
    if (tiers && typeof tiers === 'object') {
      Object.keys(tiers).forEach((tier) => {
        if (!tier) return
        const lower = String(tier).toLowerCase()
        tierKeys.push(lower)
        const model = tiers[tier]?.model
        if (typeof model === 'string' && model.trim()) {
          tierModels[lower] = model.trim()
        }
      })
    }
    routerFxSlotList.value = routerFxSortTiers(tierKeys)
    routerFxModels.value = tierModels
    globalElevatedMode.value = normalizeElevatedMode(cfg?.permissions?.default_mode)
    toolbarState.value.bypass = isApprovalBypassMode(effectiveElevatedMode.value)
    await loadCurrentSessionUsage()
  } catch { /* ignore */ }
}

/* ── Event handlers ────────────────────────────────────────────────── */

function isStaleEpoch(payload: SessionEventPayload): boolean {
  const ep = payload?.epoch
  if (typeof ep !== 'number' || !Number.isFinite(ep)) return false
  return ep < currentEpoch.value
}

function acceptStreamSeq(payload: SessionEventPayload): boolean {
  if (!isCurrentSessionPayload(payload)) return false
  const seq = payload?.stream_seq
  if (typeof seq !== 'number' || !Number.isFinite(seq)) return true
  if (seq <= lastStreamSeq.value) return false
  lastStreamSeq.value = seq
  return true
}

function taskTerminalStatus(event: string): string {
  if (!event.startsWith('task.')) return ''
  const status = event.slice('task.'.length)
  return ['succeeded', 'failed', 'timeout', 'abandoned', 'cancelled'].includes(status) ? status : ''
}

function taskTerminalAsSessionEvent(event: string, payload: any) {
  if (event === 'task.cancelled') {
    return { event: 'session.event.done', payload: { ...(payload || {}), reason: 'aborted' } }
  }
  if (!['task.failed', 'task.timeout', 'task.abandoned'].includes(event)) return null
  const status = event.replace('task.', '')
  return {
    event: 'session.event.error',
    payload: { ...(payload || {}), message: taskTerminalMessage(status, payload), code: status },
  }
}

function taskTerminalMessage(status: string, payload: any): string {
  if (typeof payload?.terminal_message === 'string' && payload.terminal_message.trim()) return payload.terminal_message.trim()
  if (status === 'timeout') return 'The task timed out before it could finish.'
  if (status === 'abandoned') return 'The task stopped before it could finish.'
  if (status === 'cancelled') return 'The task was cancelled before it finished.'
  if (status === 'failed') return 'The task failed before it could finish.'
  return 'The task ended before it could finish.'
}

function sessionErrorMessage(payload: any): string {
  if (typeof payload?.terminal_message === 'string' && payload.terminal_message.trim()) return payload.terminal_message.trim()
  const message = typeof payload?.message === 'string' ? payload.message : ''
  const code = typeof payload?.code === 'string' ? payload.code.toLowerCase() : ''
  if (code.includes('timeout') || message.toLowerCase().includes('stream idle')) return 'The task timed out before it could finish.'
  if (message) return message
  return 'Agent error'
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

  // Close popovers first
  if (toolbarPopoverOpen.value) { toolbarPopoverOpen.value = false; e.preventDefault(); return }

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

/* ── Click outside popovers ────────────────────────────────────────── */

function onDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (toolbarPopoverOpen.value && !target.closest('.chat-toolbar-popover') && !target.closest('.chat-toolbar-trigger')) {
    toolbarPopoverOpen.value = false
  }
}

/* ── Lifecycle ─────────────────────────────────────────────────────── */

onMounted(async () => {
  // Initialize session key
  const startNewChatOnMount = hasNewChatRouteSignal()
  const urlSession = readSessionFromUrl()
  const urlAgent = readAgentFromUrl()
  const storedSession = canonicalSessionKey(localStorage.getItem('opensquilla_active_session') || '')
  const fallbackSession = urlAgent ? webchatSessionKey(urlAgent) : (storedSession || WEBCHAT_SESSION_KEY)
  sessionKey.value = canonicalSessionKey(urlSession || fallbackSession)
  persistSession(sessionKey.value, { updateRoute: !urlSession })

  // Load elevated mode
  loadElevatedMode()

  // Load feature toggles
  await loadFeatureToggles()

  // Subscribe to RPC events
  unsubs.push(rpc.on('session.event.text_delta', (payload: TextDeltaPayload) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendDelta(payload.text || '')
  }))

  unsubs.push(rpc.on('session.event.tool_use_start', (payload: ToolUsePayload) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendToolCall(payload)
  }))

  unsubs.push(rpc.on('session.event.tool_use_delta', (payload: ToolDeltaPayload) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendToolDelta(payload)
  }))

  unsubs.push(rpc.on('session.event.tool_result', (payload: ToolResultPayload) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendToolResult(payload)
  }))

  unsubs.push(rpc.on('session.event.artifact', (payload: ArtifactPayload) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendArtifact(payload)
  }))

  unsubs.push(rpc.on('session.event.state_change', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (!payload || aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    const to = payload.to_state || payload.toState || ''
    const activeState = ['thinking', 'streaming', 'tool_calling', 'tool_use', 'running'].includes(String(to))
    if (!isStreaming.value && activeState) startStreaming()
    if (!isStreaming.value) return
    if (to === 'thinking') {
      if (streamBubble.value && !streamHasVisibleOutput.value) {
        setStreamActivity('正在组织下一步')
      } else if (!streamBubble.value) {
        showThinkingIndicator()
      }
    } else if (to === 'streaming' && streamBubble.value && !streamHasVisibleOutput.value) {
      setStreamActivity('模型正在生成')
    } else if ((to === 'tool_calling' || to === 'tool_use') && streamBubble.value && !streamHasVisibleOutput.value) {
      setStreamActivity('正在准备工具调用')
    } else if (to && streamBubble.value && !streamHasVisibleOutput.value) {
      setStreamActivity('仍在运行')
    }
  }))

  unsubs.push(rpc.on('session.event.run_heartbeat', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    if (!isStreaming.value) startStreaming()
    resetStreamIdleTimer()
    if (streamBubble.value && !streamHasVisibleOutput.value) {
      setStreamActivity('正在组织下一步')
    } else if (!streamBubble.value) {
      showThinkingIndicator()
    }
  }))

  unsubs.push(rpc.on('session.event.compaction', (payload: CompactionPayload, meta: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    showCompactionToast(payload || {}, meta || {})
  }))

  unsubs.push(rpc.on('session.event.warning', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    console.warn((payload && payload.message) || 'Assistant warning')
  }))

  unsubs.push(rpc.on('session.epoch_changed', (payload: SessionEventPayload) => {
    const ep = payload?.epoch
    if (typeof ep === 'number' && Number.isFinite(ep) && ep > currentEpoch.value) {
      activeTaskGroups.value.clear()
      currentEpoch.value = ep
    }
  }))

  unsubs.push(rpc.on('sessions.changed', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (!isCurrentSessionPayload(payload)) return
    if (sessionChangeIsTerminal(payload)) {
      syncTerminalSessionChange(payload)
      return
    }
    applySessionRunState(payload)
  }))

  unsubs.push(rpc.on('task.queued', (payload: SessionEventPayload) => {
    if (!isCurrentSessionPayload(payload)) return
    applySessionRunState({ run_status: 'queued', active_task: { ...(payload || {}), status: 'queued' } })
  }))

  unsubs.push(rpc.on('task.running', (payload: SessionEventPayload) => {
    if (!isCurrentSessionPayload(payload)) return
    applySessionRunState({ run_status: 'running', active_task: { ...(payload || {}), status: 'running' } })
  }))

  unsubs.push(rpc.on('session.event.task_group.waiting', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupActive(payload)
  }))

  unsubs.push(rpc.on('session.event.task_group.synthesizing', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupActive(payload)
  }))

  unsubs.push(rpc.on('session.event.task_group.done', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupTerminal(payload, 'succeeded')
  }))

  unsubs.push(rpc.on('session.event.task_group.failed', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupTerminal(payload, 'failed')
  }))

  unsubs.push(rpc.on('session.event.router_decision', (payload: RouterDecisionPayload) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    queueRouterDecision(payload)
  }))

  unsubs.push(rpc.on('session.event.router_control_replay', (payload: SessionEventPayload) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    handleRouterControlReplay()
  }))

  unsubs.push(rpc.on('*', (rawEvent: string, rawPayload: any) => {
    const terminalStatus = taskTerminalStatus(rawEvent)
    if (terminalStatus) {
      if (!isCurrentSessionPayload(rawPayload)) return
      const terminalRunStatus = terminalStatus === 'succeeded' ? 'idle' : terminalStatus === 'abandoned' ? 'interrupted' : terminalStatus
      if (activeTaskGroups.value.size > 0) {
        applySessionRunState(activeTaskGroupRunState(rawPayload))
      } else {
        applySessionRunState({ run_status: terminalRunStatus, last_task: { ...(rawPayload || {}), status: terminalStatus } })
      }
    }

    const normalized = taskTerminalAsSessionEvent(rawEvent, rawPayload)
    if (normalized && isStaleEpoch(rawPayload)) return
    if (normalized && !isStreaming.value) return

    const event = normalized ? normalized.event : rawEvent
    const payload = normalized ? normalized.payload : rawPayload

    if (typeof event !== 'string') return
    if (event.startsWith('session.event.') && isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    if (event.startsWith('session.event.task_group.')) return
    if (event === 'sessions.changed') return

    if (event.endsWith('.done') || event === 'chat.done') {
      const u = payload?.usage || payload || {}
      if (u.input_tokens || u.output_tokens) {
        usageAccum.value.input += u.input_tokens || 0
        usageAccum.value.output += u.output_tokens || 0
        usageAccum.value.cacheRead += u.cached_tokens || 0
        usageAccum.value.cacheWrite += u.cache_write || 0
        if (u.cost_usd != null) usageAccum.value.cost = (usageAccum.value.cost || 0) + u.cost_usd
      }
      if (u.model) usageModel.value = u.model
      saveWidgetState()

      const finalText = typeof u.text === 'string' ? u.text : ''
      if (finalText && finalText !== streamRaw.value) {
        // Reconcile final text
        streamRaw.value = finalText
      }

      if (payload?.reason === 'aborted') {
        clearPendingRouterDecision()
      } else {
        flushPendingRouterDecision()
      }
      endStreaming()
      scheduleHistorySync()

      if (payload?.reason === 'aborted') {
        popAllPendingIntoComposer()
        applySessionRunState({ run_status: 'cancelled', last_task: { ...(payload || {}), status: 'cancelled' } })
      } else if (activeTaskGroups.value.size > 0) {
        applySessionRunState(activeTaskGroupRunState({ reason: 'task_group_active' }))
      } else {
        applySessionRunState({ run_status: 'idle', last_task: { status: 'succeeded' } })
      }

      if (pendingQueue.value.length > 0 && payload?.reason !== 'aborted') {
        schedulePendingDrainAfterTerminal()
      }
    } else if (event.endsWith('.error')) {
      clearPendingRouterDecision()
      endStreaming()
      messages.value.push({ role: 'error', text: sessionErrorMessage(payload), ts: new Date().toISOString() })
      scheduleHistorySync()
      if (activeTaskGroups.value.size > 0) {
        applySessionRunState(activeTaskGroupRunState(payload))
      } else {
        applySessionRunState({ run_status: 'failed', last_task: { ...(payload || {}), status: 'failed' } })
      }
    }
  }))

  unsubs.push(rpc.on('_state', (state: string) => {
    if (state === 'connected' && sessionKey.value) {
      hideThinkingIndicator()
      subscribeSession()
      loadCurrentSessionUsage()
      loadHistory()
    }
    if (state === 'disconnected' && isStreaming.value) {
      clearStreamIdleTimer()
      showThinkingIndicator()
    }
  }))

  // Document events
  document.addEventListener('paste', onDocumentPaste)
  document.addEventListener('keydown', onDocumentKeydown)
  document.addEventListener('click', onDocumentClick)

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
  if (renderRafId) { clearTimeout(renderRafId); renderRafId = null }
  clearStreamIdleTimer()
  clearPendingDrainAfterTerminalTimer()
  if (historySyncTimer) { clearTimeout(historySyncTimer); historySyncTimer = null }
  if (thinkingDelayTimer) { clearTimeout(thinkingDelayTimer); thinkingDelayTimer = null }
  if (thinkingTimer) { clearInterval(thinkingTimer); thinkingTimer = null }
  clearStreamActivity()
  if (composerResizeObserver) { composerResizeObserver.disconnect(); composerResizeObserver = null }
  document.documentElement.style.removeProperty('--composer-h')
  document.removeEventListener('paste', onDocumentPaste)
  document.removeEventListener('keydown', onDocumentKeydown)
  document.removeEventListener('click', onDocumentClick)
  unsubscribeSession()
})

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

function showCompactionToast(payload: any, meta: any = {}) {
  if (meta.replayed) return
  let status = String(payload.status || '').toLowerCase()
  if (!status && Object.prototype.hasOwnProperty.call(payload, 'compacted')) {
    status = payload.compacted ? 'completed' : 'skipped'
  }
  const source = String(payload.source || '').toLowerCase()

  if (status === 'started') {
    if (source === 'manual') setCompactInFlight(true, payload.key || sessionKey.value)
    showCompactStatus('started', 'Compacting context...', { tone: 'info' })
    return
  }
  if (status === 'skipped') {
    settleCompactInFlight(payload || {})
    showCompactStatus('skipped', 'Already within context budget; no compact was applied.', { tone: 'info', dismissMs: 5000 })
    return
  }
  if (status === 'failed' || status === 'error') {
    const preservePending = compactFailureBlocksPending(payload || {})
    settleCompactInFlight(payload || {}, { preservePending })
    showCompactStatus('failed', 'Compact failed', { tone: 'err', dismissMs: 10000 })
    return
  }
  if (status === 'cancelled') {
    settleCompactInFlight(payload || {}, { recoverPending: true })
    showCompactStatus('cancelled', 'Compact cancelled', { tone: 'warn', dismissMs: 8000 })
    return
  }
  if (status === 'completed') {
    settleCompactInFlight(payload || {})
    showCompactStatus('completed', 'Context compacted', { tone: 'ok', dismissMs: 5000 })
  }
}

function compactFailureBlocksPending(payload: any): boolean {
  if (!payload) return false
  if (payload.refused === true || payload.safe_to_send === false || payload.safeToSend === false) return true
  const reason = String(payload.reason || payload.error_reason || payload.errorClass || payload.error_class || payload.error?.reason || payload.error?.code || '').toLowerCase()
  return ['compaction_insufficient', 'compaction_flush_failed', 'context_overflow', 'unsafe_flush_receipt'].includes(reason)
}

function settleCompactInFlight(payload: any = {}, options: any = {}) {
  const key = String(payload.key || compactInFlightKey.value || sessionKey.value || '')
  if (!compactInFlight.value || (compactInFlightKey.value && key && key !== compactInFlightKey.value)) return false
  setCompactInFlight(false)
  const status = String(payload.status || '').toLowerCase()
  const compactedFlag = Object.prototype.hasOwnProperty.call(payload, 'compacted') ? !!payload.compacted : null
  if (status === 'completed' || status === 'skipped' || (status === '' && compactedFlag !== null)) {
    schedulePendingDrainAfterTerminal()
  } else if (options.preservePending) {
    // pending preserved
  } else if (options.recoverPending) {
    popAllPendingIntoComposer()
  }
  return true
}
</script>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  background: #fff;
  color: #18181b;
  border: 1px solid rgba(31, 35, 40, 0.05);
  border-radius: 10px;
  box-shadow:
    0 1px 1px rgba(31, 35, 40, 0.025),
    0 8px 18px rgba(31, 35, 40, 0.032);
}

.chat--new-landing {
  justify-content: flex-start;
  gap: 1.125rem;
  padding: clamp(5.25rem, 17vh, 9.5rem) 0 2rem;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 48px;
  padding: 0 20px;
  border-bottom: 0;
  background: #fff;
  flex-shrink: 0;
}

.chat-header-left {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
}

.chat-header-right {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
  margin-right: 56px;
}

.chat-label {
  font-size: 0.9375rem;
  font-weight: 500;
  letter-spacing: 0;
  color: #242428;
  flex-shrink: 0;
  max-width: min(42vw, 360px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-session-chip {
  display: inline-flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.25rem 0.5rem;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  font-family: monospace;
  cursor: pointer;
  max-width: 280px;
  min-width: 0;
}

.chat-session-chip-key {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-session-chip-caret {
  display: inline-flex;
  flex-shrink: 0;
  color: var(--text-muted, #666);
}

.chat-session-copy-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.25rem;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted, #666);
  flex-shrink: 0;
}

.chat-session-copy-btn:hover {
  color: var(--text-primary, #1a1a1a);
}

.chip {
  display: inline-flex;
  align-items: center;
  padding: 0.125rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.8125rem;
  font-weight: 500;
  background: var(--bg-tertiary, #e5e5e5);
  color: var(--text-muted, #666);
}

.chat-header-right .chip {
  display: none;
}

.chip-warn {
  background: #fef3c7;
  color: #92400e;
}

.chip-ok {
  background: #d1fae5;
  color: #065f46;
}

.chip-danger {
  background: #fee2e2;
  color: #991b1b;
}

.chat-ctx-warn {
  font-size: 0.8125rem;
  font-weight: 500;
  color: #dc2626;
}

.chat-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  background: #fff;
}

.chat--new-landing .chat-body {
  flex: 0 0 auto;
  overflow: visible;
}

.chat-thread {
  flex: 1;
  overflow-y: auto;
  padding: 0.25rem 0 1.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  background: #fff;
}

.chat--new-landing .chat-thread {
  flex: 0 0 auto;
  overflow: visible;
  padding: 0;
  gap: 0;
}

.chat-landing-brand {
  width: min(calc(100% - 48px), 720px);
  margin: 0 auto;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.chat-landing-lockup {
  display: block;
  width: 100%;
  height: auto;
  max-height: 252px;
  object-fit: contain;
  filter: drop-shadow(0 18px 34px rgba(31, 35, 40, 0.13));
}

.chat-empty {
  text-align: center;
  color: #9ca3af;
  padding: 3rem 1rem;
  font-size: 0.875rem;
}

/* Messages */
/* ── Kimi-style Messages ─────────────────────────────────────────────── */

/* User message */
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

/* AI message */
.msg-ai {
  display: flex;
  gap: 0.625rem;
  width: min(calc(100% - 48px), 980px);
  margin: 0 auto;
  padding: 0.5rem 0;
  align-items: flex-start;
  max-width: calc(100% - 48px);
}

.msg-ai-avatar {
  width: 1.75rem;
  height: 1.75rem;
  border-radius: 50%;
  background: #fff;
  border: 1px solid rgba(32, 39, 34, 0.08);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 0.0625rem;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(31, 35, 40, 0.05);
}

.msg-ai-avatar__img {
  width: 1.125rem;
  height: 1.125rem;
  object-fit: contain;
  display: block;
}

.msg-ai-main {
  flex: 1;
  min-width: 0;
  max-width: none;
  padding-top: 0.0625rem;
}

.msg-ai-text {
  font-size: 0.875rem;
  line-height: 1.6;
  color: #27272a;
  word-break: break-word;
  margin-bottom: 0.5rem;
}

.msg-ai-text :deep(p) { margin: 0.375rem 0; }
.msg-ai-text :deep(p:first-child) { margin-top: 0; }
.msg-ai-text :deep(ul), .msg-ai-text :deep(ol) { margin: 0.375rem 0; padding-left: 1.25rem; }
.msg-ai-text :deep(li) { margin: 0.125rem 0; }
.msg-ai-text :deep(code) {
  background: #f4f4f5;
  padding: 0.0625rem 0.25rem;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  color: #52525b;
}
.msg-ai-text :deep(pre) {
  background: #fafafa;
  border: 1px solid #e4e4e7;
  border-radius: 6px;
  padding: 0.625rem;
  overflow-x: auto;
  margin: 0.375rem 0;
}
.msg-ai-text :deep(pre code) {
  background: transparent;
  padding: 0;
}

.msg-ai-footer {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  margin-top: 0.25rem;
}

.msg-ai-actions {
  display: flex;
  gap: 0.125rem;
  opacity: 0;
  transition: opacity 0.15s;
}

.msg-ai:hover .msg-ai-actions {
  opacity: 1;
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

.msg-ai-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  font-size: 0.8125rem;
  line-height: 1.35;
  color: var(--text-muted, #8a8a8a);
}

/* System / Subagent / Error messages */
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

/* Step card */
.step-card {
  background: #fff;
  border: 1px solid rgba(31, 35, 40, 0.08);
  border-radius: 8px;
  padding: 0.25rem;
  overflow: hidden;
  margin: 0.625rem 0;
  box-shadow:
    0 1px 1px rgba(31, 35, 40, 0.025),
    0 8px 18px rgba(31, 35, 40, 0.032);
}

.stream-activity {
  display: inline-flex;
  align-items: center;
  gap: 0.5rem;
  min-height: 1.625rem;
  padding: 0.375rem 0;
}

.stream-activity-dot {
  width: 0.375rem;
  height: 0.375rem;
  border-radius: 999px;
  background: #76a98c;
  box-shadow: 0 0 0 0 rgba(118, 169, 140, 0.28);
  animation: activityPulse 1.8s ease-out infinite;
  flex-shrink: 0;
}

.stream-activity-text {
  font-size: 0.8125rem;
  line-height: 1.5;
}

.activity-shimmer {
  color: #8c938b;
  background:
    linear-gradient(
      105deg,
      #8c938b 0%,
      #8c938b 36%,
      #232824 48%,
      #8c938b 60%,
      #8c938b 100%
    );
  background-size: 240% 100%;
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  animation: activityTextShimmer 2.2s ease-in-out infinite;
}

.step-group {
  border-radius: 7px;
}

.step-group + .step-group {
  margin-top: 0.125rem;
}

.step-group-header,
.step-subitem {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
  padding: 0.625rem 0.875rem;
  cursor: pointer;
  border-radius: 6px;
  transition: background 0.12s ease, color 0.12s ease;
  min-height: 2.5rem;
  color: inherit;
}

.step-group-header {
  border: 0;
  background: transparent;
  font: inherit;
  text-align: left;
}

.step-subitem {
  position: relative;
  padding: 0.5625rem 0.75rem 0.5625rem 2.25rem;
}

.step-group-header:hover,
.step-subitem:hover {
  background: #f7f8f6;
}

.step-group.is-open > .step-group-header,
.step-subitem.is-open {
  background: #fafbf9;
}

.step-group--running > .step-group-header,
.step-item--running {
  background: rgba(184, 68, 4, 0.045);
}

.step-group--running .step-icon,
.step-item--running .step-icon {
  color: #b84404;
}

.step-group--error .step-title,
.step-group--error .step-status,
.step-item--error .step-title,
.step-item--error .step-subtitle,
.step-item--error .step-status {
  color: #c2410c;
}

.step-group-members {
  margin: 0.125rem 0 0.25rem;
  padding-left: 1.25rem;
}

.step-group-members::before {
  content: '';
  display: block;
  width: calc(100% - 1.25rem);
  height: 1px;
  margin: 0 0 0.125rem 1.25rem;
  background: rgba(31, 35, 40, 0.045);
}

.step-icon {
  width: 1.125rem;
  height: 1.125rem;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  color: #6b716b;
}

.step-body {
  flex: 1;
  min-width: 0;
}

.step-title-row {
  display: flex;
  align-items: baseline;
  gap: 0.625rem;
  min-width: 0;
}

.step-title {
  font-size: 0.8125rem;
  font-weight: 500;
  color: #272a27;
  line-height: 1.4;
  flex-shrink: 0;
}

.step-count {
  flex-shrink: 0;
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0.0625rem 0.375rem;
  border-radius: 999px;
  color: #71766f;
  background: rgba(31, 35, 40, 0.055);
}

.step-subtitle {
  font-size: 0.765625rem;
  font-weight: 500;
  color: #4b514a;
  line-height: 1.4;
  flex-shrink: 0;
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-secondary {
  min-width: 0;
  color: #90958f;
  font-size: 0.8125rem;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.step-detail {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: #f8f9f7;
  border: 1px solid rgba(31, 35, 40, 0.06);
  border-radius: 6px;
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: #676d66;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow-y: auto;
}

.step-result {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: #f8f9f7;
  border: 1px solid rgba(31, 35, 40, 0.06);
  border-radius: 6px;
}

.step-result--error {
  background: #fff7ed;
  border-color: #fed7aa;
}

.step-result-pre {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: #27272a;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow-y: auto;
  margin: 0;
}

.step-view-btn {
  margin-top: 0.25rem;
  padding: 0.125rem 0.375rem;
  font-size: 0.6875rem;
  color: #b84404;
  background: transparent;
  border: none;
  cursor: pointer;
}

.step-view-btn:hover {
  text-decoration: underline;
}

.step-trailing {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-shrink: 0;
  color: #a4aaa3;
}

.step-status {
  font-size: 0.8125rem;
  color: #9ca29b;
  white-space: nowrap;
}

.step-chevron {
  transition: transform 0.12s ease;
}

.step-group.is-open > .step-group-header .step-chevron,
.step-subitem.is-open .step-chevron {
  transform: rotate(90deg);
}

/* Thinking indicator */
.thinking-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.375rem 0;
}

.thinking-elapsed {
  font-size: 0.8125rem;
  line-height: 1.5;
}

@keyframes activityPulse {
  0% {
    transform: scale(0.9);
    opacity: 0.6;
    box-shadow: 0 0 0 0 rgba(118, 169, 140, 0.24);
  }
  55% {
    transform: scale(1);
    opacity: 1;
    box-shadow: 0 0 0 5px rgba(118, 169, 140, 0);
  }
  100% {
    transform: scale(0.9);
    opacity: 0.65;
    box-shadow: 0 0 0 0 rgba(118, 169, 140, 0);
  }
}

@keyframes activityTextShimmer {
  0% { background-position: 140% 0; }
  45% { background-position: -20% 0; }
  100% { background-position: -20% 0; }
}

/* Pending queue */
.chat-pending {
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--border-color, #e5e5e5);
  background: var(--bg-secondary, #f5f5f5);
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
  color: var(--text-muted, #666);
}

.chat-pending-clear {
  font-size: 0.8125rem;
  color: var(--accent-color, #3b82f6);
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
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
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
  color: var(--text-muted, #666);
  font-size: 0.875rem;
  line-height: 1;
}

.chat-pending-chip-remove:hover {
  color: #dc2626;
}

.chat-pending-attch {
  font-size: 0.8125rem;
}

/* Compact status */
.chat-compact-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  font-size: 0.8125rem;
  flex-shrink: 0;
}

.chat-compact-status--info {
  background: #eff6ff;
  color: #1e40af;
}

.chat-compact-status--ok {
  background: #ecfdf5;
  color: #065f46;
}

.chat-compact-status--warn {
  background: #fffbeb;
  color: #92400e;
}

.chat-compact-status--err {
  background: #fef2f2;
  color: #991b1b;
}

.chat-compact-status__spinner {
  width: 12px;
  height: 12px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

.chat-compact-status__dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Slash menu */
.chat-slash {
  position: absolute;
  bottom: calc(var(--composer-h, 60px) + 0.5rem);
  left: 1rem;
  right: 1rem;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  z-index: 10;
  max-height: 200px;
  overflow-y: auto;
}

.chat-slash-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 0.75rem;
  cursor: pointer;
  font-size: 0.875rem;
}

.chat-slash-item:hover,
.chat-slash-item--active {
  background: var(--bg-secondary, #f5f5f5);
}

.chat-slash-cmd {
  font-family: monospace;
  font-weight: 600;
  color: var(--accent-color, #3b82f6);
}

.chat-slash-desc {
  color: var(--text-muted, #666);
  font-size: 0.8125rem;
}

/* Composer */
.chat-composer {
  padding: 0.75rem 1.5rem 1.875rem;
  border-top: 0;
  background: #fff;
  flex-shrink: 0;
}

.chat--new-landing .chat-composer {
  width: min(calc(100% - 48px), 820px);
  margin: 0 auto;
  padding: 0;
  background: transparent;
}

.chat-composer-inner {
  width: min(100%, 820px);
  margin: 0 auto;
}

.chat--new-landing .chat-composer-inner {
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

.chat--new-landing .chat-input-panel {
  min-height: 148px;
  border-color: rgba(32, 39, 34, 0.10);
  border-radius: 24px;
  box-shadow:
    0 1px 2px rgba(31, 35, 40, 0.025),
    0 18px 42px rgba(31, 35, 40, 0.065);
}

.chat--new-landing .chat-input-panel:focus-within {
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

.chat--new-landing .chat-textarea {
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

/* Buttons */
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
  padding: 0.5rem;
  width: 36px;
  height: 36px;
}

.chat-composer .btn--icon {
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

.chat-aux-action-wrap,
.chat-aux-action {
  width: 0 !important;
  min-width: 0 !important;
  height: 34px;
  padding: 0;
  overflow: hidden;
  opacity: 0;
  pointer-events: none;
  transform: translateX(-4px);
  transition: opacity 120ms ease, width 120ms ease, min-width 120ms ease, transform 120ms ease;
}

.chat-input-panel:hover .chat-aux-action-wrap,
.chat-input-panel:focus-within .chat-aux-action-wrap,
.chat-input-panel:hover .chat-aux-action,
.chat-input-panel:focus-within .chat-aux-action,
.chat-aux-action-wrap.is-visible,
.chat-aux-action.is-glowing {
  width: 34px !important;
  min-width: 34px !important;
  opacity: 1;
  pointer-events: auto;
  transform: translateX(0);
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

.chat-model-pill {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  max-width: 160px;
  min-height: 32px;
  padding: 0 0.375rem 0 0.625rem;
  color: #2f2f33;
  font-size: 0.8125rem;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.btn--danger {
  background: #dc2626;
  color: #fff;
  border-color: #dc2626;
}

.btn--danger:hover {
  opacity: 0.9;
}

.btn--sm {
  padding: 0.25rem 0.5rem;
  font-size: 0.8125rem;
}

/* Toolbar */
.chat-toolbar-wrap {
  position: relative;
}

.chat-toolbar-trigger {
  position: relative;
}

.chat-toolbar-trigger-dots {
  position: absolute;
  top: 2px;
  right: 2px;
  display: flex;
  gap: 1px;
}

.chat-toolbar-trigger-dots i {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: transparent;
}

.chat-toolbar-trigger.has-dot-bypass [data-dot="bypass"] {
  background: #dc2626;
}

.chat-toolbar-trigger.has-dot-router [data-dot="router"] {
  background: #f59e0b;
}

.chat-toolbar-trigger.is-glowing {
  color: var(--accent-color, #3b82f6);
}

.chat-toolbar-popover {
  position: absolute;
  bottom: calc(100% + 0.5rem);
  right: 0;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.5rem;
  box-shadow: 0 4px 12px rgba(0,0,0,0.1);
  padding: 0.75rem;
  min-width: 220px;
  z-index: 20;
}

.chat-toolbar-popover-arrow {
  position: absolute;
  bottom: -5px;
  right: 12px;
  width: 10px;
  height: 10px;
  background: var(--bg-primary, #fff);
  border-right: 1px solid var(--border-color, #e5e5e5);
  border-bottom: 1px solid var(--border-color, #e5e5e5);
  transform: rotate(45deg);
}

.chat-toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.75rem;
  padding: 0.375rem 0;
}

.chat-toolbar-row-label {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text-primary, #1a1a1a);
}

/* Toggle switch */
.toggle-switch-wrap {
  display: inline-flex;
}

.toggle-switch {
  display: inline-flex;
  align-items: center;
  cursor: pointer;
  position: relative;
}

.toggle-switch input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.toggle-track {
  width: 36px;
  height: 20px;
  background: var(--bg-tertiary, #e5e5e5);
  border-radius: 10px;
  position: relative;
  transition: background 0.2s;
}

.toggle-switch input:checked + .toggle-track {
  background: var(--accent-color, #3b82f6);
}

.toggle-thumb {
  position: absolute;
  top: 2px;
  left: 2px;
  width: 16px;
  height: 16px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s;
  box-shadow: 0 1px 3px rgba(0,0,0,0.2);
}

.toggle-switch input:checked + .toggle-track .toggle-thumb {
  transform: translateX(16px);
}

/* Pills */
.chat-pill {
  display: inline-flex;
  align-items: center;
  padding: 0.25rem 0.625rem;
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  border: 1px solid transparent;
  background: var(--bg-tertiary, #e5e5e5);
  color: var(--text-muted, #666);
}

.chat-pill--danger {
  background: #fee2e2;
  color: #991b1b;
  border-color: #fecaca;
}

.chat-pill.is-active {
  background: #dcfce7;
  color: #166534;
  border-color: #bbf7d0;
}

.chat-pill--disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

/* Session popover */
.chat-session-popover {
  position: fixed;
  z-index: 30;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.5rem;
  box-shadow: 0 4px 16px rgba(0,0,0,0.15);
  max-height: 400px;
  overflow-y: auto;
  min-width: 320px;
}

.chat-session-popover-search {
  width: 100%;
  padding: 0.5rem 0.75rem;
  border: none;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
  font-size: 0.875rem;
  outline: none;
  background: transparent;
  color: var(--text-primary, #1a1a1a);
}

.chat-session-popover-list {
  padding: 0.25rem 0;
}

.chat-session-popover-group {
  padding: 0.25rem 0;
}

.chat-session-popover-group-label {
  padding: 0.25rem 0.75rem;
  font-size: 0.6875rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #999);
}

.chat-session-popover-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  width: 100%;
  padding: 0.375rem 0.75rem;
  background: none;
  border: none;
  cursor: pointer;
  font-size: 0.8125rem;
  text-align: left;
}

.chat-session-popover-item:hover {
  background: var(--bg-secondary, #f5f5f5);
}

.chat-session-popover-item.is-current {
  background: var(--bg-secondary, #f5f5f5);
}

.chat-session-popover-item-key {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-family: monospace;
}

.chat-session-popover-item-run {
  font-size: 0.6875rem;
  padding: 0.0625rem 0.375rem;
  border-radius: 0.25rem;
  font-weight: 500;
  flex-shrink: 0;
}

.chat-session-popover-item-run--running {
  background: #d1fae5;
  color: #065f46;
}

.chat-session-popover-item-run--queued {
  background: #fef3c7;
  color: #92400e;
}

.chat-session-popover-item-run--failed {
  background: #fee2e2;
  color: #991b1b;
}

.chat-session-popover-item-tag {
  font-size: 0.6875rem;
  padding: 0.0625rem 0.375rem;
  border-radius: 0.25rem;
  background: var(--accent-color, #3b82f6);
  color: #fff;
  flex-shrink: 0;
}

.chat-session-popover-empty {
  padding: 1rem;
  text-align: center;
  font-size: 0.8125rem;
  color: var(--text-muted, #666);
}

/* Tool Result Modal */
.tool-modal-overlay {
  position: fixed;
  inset: 0;
  z-index: 300;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-4);
}

.tool-modal {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  width: 100%;
  max-width: 720px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
}

.tool-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
}

.tool-modal__title {
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
  color: var(--text);
}

.tool-modal__body {
  flex: 1;
  padding: var(--sp-4);
  margin: 0;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  background: var(--bg-primary);
  color: var(--text);
}

/* Artifacts */
.msg-artifacts {
  margin: 0.75rem 0 0.875rem;
}

.msg-artifact-gallery,
.msg-artifact-files {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  width: 100%;
  margin: 0 auto;
}

.msg-artifact-card {
  display: flex;
  flex-direction: column;
  padding: 0;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.5rem;
  overflow: hidden;
  cursor: pointer;
  text-align: left;
}

.msg-artifact-card--image {
  max-width: 200px;
}

.msg-artifact-preview {
  width: 100%;
  height: 120px;
  object-fit: cover;
}

.msg-artifact-card__body {
  padding: 0.375rem 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

.msg-artifact-card__name {
  font-size: 0.8125rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-artifact-card__meta {
  font-size: 0.6875rem;
  color: var(--text-muted, #999);
}

.msg-artifact-chip {
  display: grid;
  grid-template-columns: 3.25rem minmax(0, 1fr) auto;
  align-items: center;
  gap: 0.875rem;
  width: 100%;
  min-height: 4.625rem;
  padding: 0.75rem 1rem 0.75rem 0.75rem;
  background: linear-gradient(180deg, #fff 0%, #fbfcfa 100%);
  border: 1px solid rgba(31, 35, 40, 0.1);
  border-radius: 10px;
  box-shadow:
    0 1px 1px rgba(31, 35, 40, 0.02),
    0 8px 18px rgba(31, 35, 40, 0.026);
  cursor: pointer;
  text-align: left;
  transition:
    background 0.14s ease,
    border-color 0.14s ease,
    box-shadow 0.14s ease;
}

.msg-artifact-chip:hover {
  background: #fff;
  border-color: rgba(32, 39, 34, 0.16);
  box-shadow:
    0 1px 1px rgba(31, 35, 40, 0.03),
    0 10px 22px rgba(31, 35, 40, 0.045);
}

.msg-artifact-chip:focus-visible {
  outline: 2px solid rgba(184, 68, 4, 0.28);
  outline-offset: 2px;
}

.msg-artifact-icon {
  position: relative;
  width: 3.25rem;
  height: 3.25rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #5d645d;
  background: #f6f7f4;
  border: 1px solid rgba(31, 35, 40, 0.08);
  border-radius: 8px;
  overflow: hidden;
  flex-shrink: 0;
}

.msg-artifact-icon::after {
  content: "";
  position: absolute;
  top: -1px;
  right: -1px;
  width: 0.875rem;
  height: 0.875rem;
  background: linear-gradient(135deg, rgba(31, 35, 40, 0.08) 50%, #fff 50%);
  border-bottom-left-radius: 4px;
}

.msg-artifact-icon[data-kind="visual"] {
  color: #315f68;
  background: #f2f8f7;
}

.msg-artifact-icon[data-kind="data"] {
  color: #5d552f;
  background: #faf7ec;
}

.msg-artifact-icon[data-kind="code"] {
  color: #70452b;
  background: #fbf4ef;
}

.msg-artifact-info {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  min-width: 0;
}

.msg-artifact-name {
  color: #202722;
  font-size: 0.9375rem;
  font-weight: 500;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-artifact-meta {
  color: #8a9189;
  font-size: 0.8125rem;
  line-height: 1.35;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-artifact-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 4rem;
  min-height: 2.125rem;
  padding: 0 0.875rem;
  border-radius: 999px;
  background: #f6f7f4;
  color: #262b27;
  font-size: 0.8125rem;
  font-weight: 500;
  white-space: nowrap;
  transition: background 0.14s ease, color 0.14s ease;
}

.msg-artifact-chip:hover .msg-artifact-action {
  background: #202722;
  color: #fff;
}

@media (max-width: 640px) {
  .msg-artifact-chip {
    grid-template-columns: 2.75rem minmax(0, 1fr);
    gap: 0.75rem;
    padding: 0.625rem;
  }

  .msg-artifact-icon {
    width: 2.75rem;
    height: 2.75rem;
  }

  .msg-artifact-action {
    grid-column: 2;
    justify-self: start;
    min-height: 1.875rem;
    min-width: 3.5rem;
    margin-top: 0.125rem;
  }
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

/* Attachment thumbnails in messages */
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

/* Subagent disclosure */
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

/* Router FX */
.router-fx {
  display: flex;
  flex-direction: column;
  gap: 6px;
  width: min(calc(100% - 48px), 620px);
  margin: 0.375rem auto 0.25rem;
  padding: 0;
  user-select: none;
  --router-accent: var(--accent, #f56600);
  --router-bg: #fff;
  --router-surface: #fafafa;
  --router-hairline: rgba(24, 24, 27, 0.09);
  --router-text: #27272a;
  --router-muted: #8b8b93;
  --router-danger: #dc2626;
}

.router-fx-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 2px 0 0;
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 10.5px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.44em;
}

.router-fx-header .title {
  padding-left: 0.44em;
}

.router-fx-header .glyph {
  color: var(--router-accent);
  font-size: 12px;
  letter-spacing: 0;
  animation: router-fx-chev 900ms cubic-bezier(.4,0,.6,1) 2;
}

.router-fx-header .glyph:last-child {
  animation-delay: 450ms;
}

@keyframes router-fx-chev {
  0%, 100% { transform: translateX(0); }
  50% { transform: translateX(3px); }
}

.router-fx-grid {
  position: relative;
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  grid-template-rows: repeat(3, 30px);
  gap: 4px;
  padding: 8px;
  background:
    radial-gradient(rgba(24, 24, 27, 0.08) 0.7px, transparent 1.2px) 0 0 / 8px 8px,
    var(--router-surface);
  border: 1px solid var(--router-hairline);
  border-radius: 8px;
  overflow: hidden;
}

.router-fx-cell {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  padding: 0 6px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid var(--router-hairline);
  border-radius: 4px;
  color: var(--router-text);
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: 0.01em;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: transform 220ms cubic-bezier(.34,1.65,.5,1), background 240ms ease, color 240ms ease, border-color 240ms ease, box-shadow 240ms ease;
}

.router-fx-cell[data-kind="real"]::after {
  content: '';
  position: absolute;
  top: 3px;
  right: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--router-accent);
  opacity: 0.72;
}

.router-fx-cell[data-kind="decoy"] {
  color: var(--router-muted);
  font-style: italic;
  opacity: 0.78;
}

@keyframes router-fx-mole-pop {
  0% { transform: translateY(0) scale(1); background: rgba(255, 255, 255, 0.72); }
  35% { transform: translateY(-2px) scale(1.14); background: color-mix(in srgb, var(--router-accent) 14%, #fff); }
  100% { transform: translateY(0) scale(1); background: rgba(255, 255, 255, 0.72); }
}

.router-fx-cell:nth-child(2),
.router-fx-cell:nth-child(6),
.router-fx-cell:nth-child(9),
.router-fx-cell:nth-child(4) {
  animation: router-fx-mole-pop 190ms cubic-bezier(.34,1.7,.5,1) both;
}

.router-fx-cell:nth-child(2) { animation-delay: 80ms; }
.router-fx-cell:nth-child(6) { animation-delay: 280ms; }
.router-fx-cell:nth-child(9) { animation-delay: 520ms; }
.router-fx-cell:nth-child(4) { animation-delay: 760ms; }

.router-fx-cell .nm {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}

.router-fx-cell.win {
  font-style: normal;
  animation: router-fx-winner-reveal 1.42s linear both;
}

.router-fx-cell.win::after {
  animation: router-fx-winner-dot-reveal 1.42s linear both;
}

.router-fx[data-source="fallback"] .router-fx-cell.win {
  animation-name: router-fx-winner-reveal-fallback;
}

.router-fx[data-source="fallback"] .router-fx-cell.win::after {
  background: var(--router-danger);
}

/* Settled state: a router decision has already animated in this turn.
   Subsequent decisions in the same turn (e.g. tool-call model switch)
   update data only — no keyframes replay; the selector slides via
   transition to the new tier. */
.router-fx[data-settled="true"] .router-fx-cell,
.router-fx[data-settled="true"] .router-fx-cell.win,
.router-fx[data-settled="true"] .router-fx-cell.win::after,
.router-fx[data-settled="true"] .router-fx-header .glyph {
  animation: none !important;
}
.router-fx[data-settled="true"] .router-fx-cell.win {
  color: var(--router-accent);
  background: color-mix(in srgb, var(--router-accent) 9%, #fff);
  border-color: var(--router-accent);
  font-weight: 600;
}
.router-fx[data-settled="true"][data-source="fallback"] .router-fx-cell.win {
  color: var(--router-danger);
  background: color-mix(in srgb, var(--router-danger) 9%, #fff);
  border-color: var(--router-danger);
}
.router-fx[data-settled="true"] .router-fx-selector {
  transition: left 360ms cubic-bezier(.4,.0,.2,1), top 360ms cubic-bezier(.4,.0,.2,1);
}

@keyframes router-fx-winner-reveal {
  0%, 89% {
    color: var(--router-text);
    background: rgba(255, 255, 255, 0.72);
    border-color: var(--router-hairline);
    font-weight: 400;
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    color: var(--router-accent);
    background: color-mix(in srgb, var(--router-accent) 9%, #fff);
    border-color: var(--router-accent);
    font-weight: 600;
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
  }
}

@keyframes router-fx-winner-reveal-fallback {
  0%, 89% {
    color: var(--router-text);
    background: rgba(255, 255, 255, 0.72);
    border-color: var(--router-hairline);
    font-weight: 400;
    transform: translateY(0);
    box-shadow: none;
  }
  100% {
    color: var(--router-danger);
    background: color-mix(in srgb, var(--router-danger) 9%, #fff);
    border-color: var(--router-danger);
    font-weight: 600;
    transform: translateY(-1px);
    box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
  }
}

@keyframes router-fx-winner-dot-reveal {
  0%, 89% { opacity: 0.72; }
  100% { opacity: 1; }
}

.router-fx-selector {
  position: absolute;
  z-index: 2;
  top: 8px;
  left: 8px;
  width: calc((100% - 28px) / 4);
  height: 30px;
  border: 2px solid color-mix(in srgb, var(--router-accent) 80%, transparent);
  border-radius: 4px;
  background: color-mix(in srgb, var(--router-accent) 6%, transparent);
  pointer-events: none;
  opacity: 0;
  transform: rotate(0deg);
}

.router-fx-selector.visible {
  opacity: 1;
}

.router-fx-selector.lock {
  border-color: var(--router-accent);
  background: color-mix(in srgb, var(--router-accent) 12%, transparent);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--router-accent) 22%, transparent),
    inset 0 0 0 1px color-mix(in srgb, var(--router-accent) 8%, transparent);
}

.router-fx[data-source="fallback"] .router-fx-selector.lock {
  border-color: var(--router-danger);
  background: color-mix(in srgb, var(--router-danger) 12%, transparent);
  box-shadow:
    0 0 0 1px color-mix(in srgb, var(--router-danger) 22%, transparent),
    inset 0 0 0 1px color-mix(in srgb, var(--router-danger) 8%, transparent);
}

@keyframes router-fx-selector-chase {
  0% { opacity: 1; left: 8px; top: 8px; transform: rotate(1.4deg); }
  12% { left: calc(((100% - 28px) / 2) + 16px); top: 8px; transform: rotate(-1.4deg); }
  25% { left: calc(((100% - 28px) / 4) + 12px); top: 42px; transform: rotate(1.4deg); }
  42% { left: calc(((100% - 28px) * 3 / 4) + 20px); top: 42px; transform: rotate(-1.4deg); }
  62% { left: 8px; top: 76px; transform: rotate(1.4deg); }
  78% { left: calc(((100% - 28px) / 2) + 16px); top: 76px; transform: rotate(-1.4deg); }
  100% { opacity: 1; left: var(--router-left); top: var(--router-top); transform: rotate(0deg); }
}

.router-fx-selector.lock-impact {
  animation: router-fx-selector-chase 1.28s cubic-bezier(.18,1.25,.45,1) both, router-fx-impact 280ms cubic-bezier(.34,1.6,.5,1) 1.28s both;
}

@keyframes router-fx-impact {
  0% { outline: 0 solid transparent; outline-offset: 0; }
  35% { outline: 2px solid color-mix(in srgb, var(--router-accent) 70%, transparent); outline-offset: 4px; }
  100% { outline: 0 solid transparent; outline-offset: 0; }
}

.router-fx-burst {
  position: absolute;
  z-index: 4;
  left: var(--router-burst-left);
  top: var(--router-burst-top);
  width: 0;
  height: 0;
  pointer-events: none;
}

.router-fx-burst i {
  position: absolute;
  left: -2px;
  top: -2px;
  width: 4px;
  height: 4px;
  border-radius: 1px;
  background: var(--router-accent);
  opacity: 0;
  animation: router-fx-burst 540ms cubic-bezier(.2,.7,.2,1) 1.38s forwards;
}

.router-fx-burst i:nth-child(1) { --bx: -22px; --by: -10px; }
.router-fx-burst i:nth-child(2) { --bx: 22px; --by: -10px; }
.router-fx-burst i:nth-child(3) { --bx: -22px; --by: 10px; }
.router-fx-burst i:nth-child(4) { --bx: 22px; --by: 10px; }
.router-fx-burst i:nth-child(5) { --bx: 0; --by: -18px; width: 3px; height: 3px; }
.router-fx-burst i:nth-child(6) { --bx: 0; --by: 18px; width: 3px; height: 3px; }

@keyframes router-fx-burst {
  0% { opacity: 1; transform: translate(0, 0) scale(1); }
  60% { opacity: 0.7; }
  100% { opacity: 0; transform: translate(var(--bx, 16px), var(--by, 0)) scale(0.4); }
}

.router-fx[data-source="fallback"] .router-fx-burst i {
  background: var(--router-danger);
}

.router-fx[data-observe="true"] {
  opacity: 0.55;
}

.router-fx[data-observe="true"] .router-fx-header::after {
  content: 'observe';
  margin-left: 12px;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(139, 139, 147, 0.16);
  color: var(--router-muted);
  font-family: var(--font-mono);
  font-size: 9px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.router-fx[data-observe="true"] .router-fx-selector.lock-impact,
.router-fx[data-observe="true"] .router-fx-burst i,
.router-fx[data-observe="true"] .router-fx-header .glyph {
  animation: none;
}

.router-fx[data-observe="true"] .router-fx-selector {
  left: var(--router-left);
  top: var(--router-top);
  transform: rotate(0deg);
  opacity: 1;
}

.router-fx[data-observe="true"] .router-fx-cell.win {
  animation: none;
  background: rgba(139, 139, 147, 0.08);
  border-color: rgba(139, 139, 147, 0.35);
  color: var(--router-muted);
  font-weight: 500;
}

.router-fx[data-static="true"] .router-fx-cell,
.router-fx[data-static="true"] .router-fx-header .glyph,
.router-fx[data-static="true"] .router-fx-selector {
  animation: none;
}

.router-fx[data-static="true"] .router-fx-selector {
  left: var(--router-left);
  top: var(--router-top);
  transform: rotate(0deg);
  opacity: 1;
}

.router-fx[data-static="true"] .router-fx-cell.win {
  animation: none;
  color: var(--router-accent);
  background: color-mix(in srgb, var(--router-accent) 9%, #fff);
  border-color: var(--router-accent);
  font-weight: 600;
  transform: translateY(-1px);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-accent) 35%, transparent);
}

.router-fx[data-static="true"][data-source="fallback"] .router-fx-cell.win {
  color: var(--router-danger);
  background: color-mix(in srgb, var(--router-danger) 9%, #fff);
  border-color: var(--router-danger);
  box-shadow: 0 1px 0 color-mix(in srgb, var(--router-danger) 35%, transparent);
}

.router-fx[data-static="true"] .router-fx-cell.win::after {
  animation: none;
  opacity: 1;
}

@media (prefers-reduced-motion: reduce) {
  .router-fx-cell,
  .router-fx-selector,
  .router-fx-burst i,
  .router-fx-header .glyph {
    animation: none !important;
    transition: none !important;
  }

  .router-fx-selector {
    left: var(--router-left);
    top: var(--router-top);
    transform: rotate(0deg);
    opacity: 1;
  }
}

/* Code blocks */
:deep(.code-block) {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 0.75rem;
  border-radius: 0.375rem;
  overflow-x: auto;
  font-size: 0.8125rem;
  line-height: 1.5;
  margin: 0.5rem 0;
}

:deep(.code-block code) {
  font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
}

:deep(code) {
  background: var(--bg-tertiary, #e5e5e5);
  padding: 0.125rem 0.25rem;
  border-radius: 0.25rem;
  font-size: 0.8125rem;
  font-family: 'SF Mono', Monaco, 'Cascadia Code', monospace;
}

/* Cron tag */
.cron-tag {
  display: inline-flex;
  align-items: center;
  padding: 0.0625rem 0.375rem;
  background: #fef3c7;
  color: #92400e;
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  font-weight: 500;
}

/* Drag over */
.drag-over {
  background: rgba(59, 130, 246, 0.05);
}

/* Hidden */
.hidden {
  display: none !important;
}

/* Savings indicator */
.savings-indicator {
  font-size: 0.8125rem;
  font-weight: 600;
}

/* Dark mode adjustments */
/* Mobile */
@media (max-width: 768px) {
  .chat--new-landing {
    padding: clamp(3.25rem, 13vh, 5.5rem) 0.75rem 1.25rem;
    gap: 0.875rem;
  }

  .chat-landing-brand,
  .chat--new-landing .chat-composer {
    width: 100%;
  }

  .chat-landing-lockup {
    max-height: 152px;
  }

  .chat-header {
    padding: 0.5rem 0.75rem;
  }

  .chat-session-chip {
    max-width: 180px;
  }

  .msg-user-bubble {
    max-width: 85%;
  }

  .chat-thread {
    padding: 0.75rem;
  }

  .chat-composer {
    padding: 0.5rem 0.75rem;
  }

}
</style>

<template>
  <div class="chat">
    <!-- Header -->
    <div class="chat-header">
      <div class="chat-header-left">
        <label class="chat-label">Chat session</label>
        <button
          type="button"
          class="chat-session-chip"
          :aria-label="`Switch chat session: ${sessionKey}`"
          aria-haspopup="dialog"
          :aria-expanded="sessionPopoverOpen"
          @click="toggleSessionPopover"
        >
          <span class="chat-session-chip-key" :title="sessionKey">{{ sessionKey }}</span>
          <span class="chat-session-chip-caret" aria-hidden="true">
            <Icon name="chevronDown" :size="12" />
          </span>
        </button>
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

    <!-- Session Popover -->
    <div v-if="sessionPopoverOpen" class="chat-session-popover" role="dialog" aria-label="Switch session">
      <input
        ref="sessionSearchRef"
        v-model="sessionSearch"
        type="search"
        class="chat-session-popover-search"
        placeholder="Search sessions…"
        autocomplete="off"
        spellcheck="false"
        @keydown.enter.prevent="switchToTypedSession"
      />
      <div class="chat-session-popover-list">
        <template v-if="sessionListError">
          <div class="chat-session-popover-empty">Session list unavailable. Enter a key above.</div>
          <button type="button" class="chat-session-popover-item" @click="switchToTypedSession">
            <span class="chat-session-popover-item-key">Switch to typed session</span>
          </button>
        </template>
        <template v-else-if="groupedSessions.length === 0">
          <div class="chat-session-popover-empty">{{ sessionSearch ? 'No matches.' : 'No sessions found.' }}</div>
        </template>
        <template v-else>
          <div v-for="group in groupedSessions" :key="group.label" class="chat-session-popover-group">
            <div class="chat-session-popover-group-label">{{ group.label }}</div>
            <button
              v-for="item in group.items"
              :key="item.key"
              type="button"
              class="chat-session-popover-item"
              :class="{ 'is-current': item.key === sessionKey }"
              @click="switchToSession(item.key)"
            >
              <span class="chat-session-popover-item-key" :title="item.key">{{ item.key }}</span>
              <span v-if="item.runStatus && item.runStatus !== 'idle'" class="chat-session-popover-item-run" :class="`chat-session-popover-item-run--${item.runStatus}`">{{ item.runLabel }}</span>
              <span v-if="item.key === sessionKey" class="chat-session-popover-item-tag">current</span>
            </button>
          </div>
        </template>
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
        <div v-if="messages.length === 0 && !isStreaming" class="chat-empty">No messages yet.</div>

        <!-- Rendered messages -->
        <template v-for="(msg, idx) in renderedMessages" :key="msg.id || `${msg.role}-${idx}`">
          <!-- Day separator -->
          <div v-if="msg.daySeparator" class="chat-day-sep"><span>{{ msg.dayLabel }}</span></div>

          <!-- Router FX strip -->
          <div v-else-if="msg.isRouterStrip" class="router-fx" :data-state="msg.routerState">
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
                :class="{ win: ci === msg.winnerIdx }"
              >
                <span class="nm">{{ cell.displayName }}</span>
              </div>
            </div>
          </div>

          <!-- Message bubble -->
          <div
            v-else
            class="msg"
            :class="[msg.displayRole, { streaming: msg.isStreaming }]"
            :data-history-role="msg.displayRole"
            :data-message-id="msg.messageId"
          >
            <div v-if="msg.showHeader" class="msg-header">
              <span class="role-label">{{ msg.roleLabel }}</span>
              <span v-if="msg.provenanceKind === 'cron'" class="cron-tag">Cron</span>
              <span class="msg-time">{{ msg.timeStr }}</span>
            </div>
            <div class="msg-body" :class="{ 'msg-body--has-attachments': msg.hasAttachments }">
              <template v-if="msg.displayRole === 'assistant' && msg.text">
                <div class="msg-text-seg" v-html="renderMarkdown(msg.text)" />
              </template>
              <template v-else-if="msg.displayRole === 'subagent'">
                <details class="chat-subagent-disclosure">
                  <summary class="chat-subagent-disclosure-summary">{{ subagentSummary(msg.text) }}</summary>
                  <pre class="chat-subagent-disclosure-body">{{ subagentBody(msg.text) }}</pre>
                </details>
              </template>
              <template v-else-if="msg.displayRole === 'system' && msg.text">
                {{ msg.text }}
              </template>
              <template v-else-if="msg.text">
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

              <!-- Tool calls -->
              <template v-if="msg.toolCalls?.length">
                <details
                  v-for="tc in msg.toolCalls"
                  :key="tc.toolId"
                  class="chat-tools-collapse"
                  :class="{ 'chat-tools-collapse--running': tc.isRunning, 'chat-tools-collapse--success': tc.status === 'success', 'chat-tools-collapse--error': tc.status === 'error' }"
                  :open="tc.isOpen"
                >
                  <summary class="chat-tools-summary" @click.prevent="tc.isRunning && $event.preventDefault()">
                    <span class="chat-tools-icon">{{ toolEmoji(tc.name) }}</span>
                    {{ tc.displayName }}
                  </summary>
                  <div class="chat-tools-body">
                    <div v-if="tc.inputPreview" class="chat-tool-input">{{ tc.inputPreview }}</div>
                    <div v-if="tc.result" class="chat-tool-result" :class="{ 'chat-tool-result--error': tc.isError }">
                      <div class="chat-tool-result-preview">{{ tc.resultPreview }}</div>
                      <button v-if="tc.result.length > 200" class="btn btn--sm btn--ghost chat-tool-view-btn" @click="showToolResultModal(tc.result)">View full</button>
                    </div>
                  </div>
                </details>
              </template>

              <!-- Artifacts -->
              <div v-if="msg.artifacts?.length" class="msg-artifacts">
                <div class="msg-artifact-files">
                  <button
                    v-for="art in msg.artifacts"
                    :key="art.id || art.name"
                    type="button"
                    class="msg-artifact-chip"
                    @click="downloadArtifact(art)"
                  >
                    <span class="msg-file-chip__icon" aria-hidden="true">{{ artifactCategoryLabel(art) }}</span>
                    <span class="msg-file-chip__name">{{ art.name || 'artifact' }}</span>
                    <span class="msg-file-chip__meta">{{ artifactMeta(art) }}</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- Hover actions -->
            <div v-if="msg.displayRole === 'user' || msg.displayRole === 'assistant'" class="msg-actions" role="toolbar" :aria-label="`${msg.roleLabel} message actions`">
              <button type="button" class="msg-action" title="Copy message" aria-label="Copy message" @click="copyMessage(msg)">
                <Icon name="copy" :size="14" />
              </button>
              <button v-if="msg.displayRole === 'assistant'" type="button" class="msg-action" title="Regenerate" aria-label="Regenerate response" @click="regenerateMessage(idx)">
                <Icon name="refresh" :size="14" />
              </button>
              <button v-if="msg.displayRole === 'user'" type="button" class="msg-action" title="Edit message" aria-label="Edit message" @click="editMessage(idx)">
                <Icon name="edit" :size="14" />
              </button>
            </div>

            <!-- Meta footer -->
            <div v-if="msg.meta" class="msg-meta">
              <span v-if="msg.meta.model" class="msg-meta__model">{{ msg.meta.modelShort }}</span>
              <span v-if="msg.meta.hasTokens" class="msg-meta__tokens" :title="`Turn -- input: ${msg.meta.input?.toLocaleString()}, output: ${msg.meta.output?.toLocaleString()} tokens`">
                &#8593;{{ fmtTok(msg.meta.input) }} &#8595;{{ fmtTok(msg.meta.output) }}
              </span>
              <span v-if="msg.meta.cachedTokens" class="msg-meta__cached" :title="`Cached tokens: ${msg.meta.cachedTokens.toLocaleString()}`">cache:{{ fmtTok(msg.meta.cachedTokens) }}</span>
              <span v-if="msg.meta.reasoningTokens" class="msg-meta__reasoning" :title="`Reasoning tokens: ${msg.meta.reasoningTokens.toLocaleString()}`">think:{{ fmtTok(msg.meta.reasoningTokens) }}</span>
              <span v-if="msg.meta.costUsd" class="msg-meta__cost" :title="`Turn cost: $${msg.meta.costUsd.toFixed(6)}`">${{ msg.meta.costUsd.toFixed(6).replace(/\.?0+$/, '') }}</span>
              <span v-if="msg.meta.hasSaved" class="msg-meta__saved" :title="`Squilla router routed this turn (~${Math.round(msg.meta.turnSavedPct)}% vs flagship)`">
                <svg class="msg-meta__saved-flame" viewBox="0 0 16 16" aria-hidden="true" width="1em" height="1em"><path d="M8 16c3.4 0 6-2.55 6-5.78 0-3.05-2.7-4.6-2.7-7.55 0 0-1.55 1.45-2.5 4.4C8.55 4.5 8.4 1 6.5 0 6.6 3 4 4.45 4 7.6 4 11.05 5.65 16 8 16z" fill="currentColor"/></svg>
                <span class="msg-meta__saved-label">{{ msg.meta.savedLabel }}</span>
              </span>
            </div>

            <!-- Interrupted marker -->
            <span v-if="msg.interrupted" class="msg-interrupt-mark">interrupted</span>
          </div>
        </template>

        <!-- Streaming bubble -->
        <div v-if="isStreaming && streamBubble" class="msg assistant streaming" data-history-role="assistant" aria-live="polite">
          <div v-if="streamShowHeader" class="msg-header">
            <span class="role-label">Assistant</span>
            <span class="savings-indicator"></span>
            <span class="msg-time"></span>
          </div>
          <div class="msg-body">
            <div v-for="(seg, si) in streamSegments" :key="si" class="msg-text-seg" v-html="seg.html" />
            <!-- Tool calls in stream -->
            <template v-for="tc in streamToolCalls" :key="tc.toolId">
              <details
                class="chat-tools-collapse"
                :class="{ 'chat-tools-collapse--running': tc.isRunning, 'chat-tools-collapse--success': tc.status === 'success', 'chat-tools-collapse--error': tc.status === 'error' }"
              >
                <summary class="chat-tools-summary" @click.prevent="tc.isRunning && $event.preventDefault()">
                  <span class="chat-tools-icon">{{ toolEmoji(tc.name) }}</span>
                  {{ tc.displayName }}
                </summary>
                <div class="chat-tools-body">
                  <div v-if="tc.inputPreview" class="chat-tool-input">{{ tc.inputPreview }}</div>
                  <div v-if="tc.result" class="chat-tool-result" :class="{ 'chat-tool-result--error': tc.isError }">
                    <div class="chat-tool-result-preview">{{ tc.resultPreview }}</div>
                    <button v-if="tc.result.length > 200" class="btn btn--sm btn--ghost chat-tool-view-btn" @click="showToolResultModal(tc.result)">View full</button>
                  </div>
                </div>
              </details>
            </template>
            <!-- Stream artifacts -->
            <div v-if="streamArtifacts.length" class="msg-artifacts">
              <div class="msg-artifact-files">
                <button
                  v-for="art in streamArtifacts"
                  :key="art.id || art.name"
                  type="button"
                  class="msg-artifact-chip"
                  @click="downloadArtifact(art)"
                >
                  <span class="msg-file-chip__icon" aria-hidden="true">{{ artifactCategoryLabel(art) }}</span>
                  <span class="msg-file-chip__name">{{ art.name || 'artifact' }}</span>
                  <span class="msg-file-chip__meta">{{ artifactMeta(art) }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Thinking indicator -->
        <div v-if="thinkingVisible" class="msg assistant thinking" role="status" aria-live="polite">
          <div v-if="lastHeaderRole !== 'assistant'" class="msg-header">
            <span class="role-label">Assistant</span>
          </div>
          <div class="msg-body thinking-body">
            <div class="thinking-status">
              <div class="typing-indicator">
                <span v-for="i in 3" :key="i" class="dot" />
              </div>
              <span class="thinking-elapsed" aria-live="off">{{ thinkingText }}</span>
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

    <!-- Composer -->
    <div ref="composerRef" class="chat-composer">
      <div v-if="pendingAttachments.length > 0" class="chat-attachments">
        <div
          v-for="(att, i) in pendingAttachments"
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
          <button class="attachment-remove" title="Remove" @click="removeAttachment(i)">&times;</button>
        </div>
      </div>
      <div class="chat-input-bar">
        <button class="btn btn--icon btn--ghost" title="Attach files: PNG, JPEG, GIF, WEBP, PDF, TXT, MD, HTML, CSV, JSON" aria-label="Attach files" @click="fileInputRef?.click()">
          <Icon name="paperclip" :size="16" />
        </button>
        <div class="chat-toolbar-wrap">
          <button
            type="button"
            class="btn btn--icon btn--ghost chat-toolbar-trigger"
            :class="{ 'is-glowing': toolbarTriggerActive, 'has-dot-bypass': isApprovalBypassMode(effectiveElevatedMode), 'has-dot-router': toolbarState.router === false }"
            :title="toolbarTriggerTitle"
            :aria-label="toolbarTriggerTitle"
            aria-haspopup="dialog"
            :aria-expanded="toolbarPopoverOpen"
            @click="toggleToolbarPopover"
          >
            <Icon name="settings" :size="14" />
            <span class="chat-toolbar-trigger-dots" aria-hidden="true">
              <i data-dot="bypass" />
              <i data-dot="router" />
            </span>
          </button>
          <div v-if="toolbarPopoverOpen" class="chat-toolbar-popover" role="dialog" aria-label="Composer settings">
            <div class="chat-toolbar-popover-arrow" aria-hidden="true" />
            <div class="chat-toolbar-popover-inner">
              <div class="chat-toolbar-row">
                <span class="chat-toolbar-row-label">Approvals</span>
                <button
                  class="chat-pill"
                  :class="{ 'chat-pill--danger': !effectiveElevatedMode, 'is-active': !!effectiveElevatedMode, 'chat-pill--disabled': elevatedUnavailable }"
                  :aria-disabled="elevatedUnavailable ? 'true' : undefined"
                  @click="toggleElevatedMode"
                >
                  {{ elevatedPillText }}
                </button>
              </div>
              <div class="chat-toolbar-row">
                <span class="chat-toolbar-row-label">Squilla Router</span>
                <div class="toggle-switch-wrap" title="Squilla router">
                  <label class="toggle-switch" aria-label="Squilla Router">
                    <input v-model="routerEnabled" type="checkbox" @change="onRouterToggle" />
                    <span class="toggle-track"><span class="toggle-thumb" /></span>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </div>
        <div class="chat-input-wrap">
          <textarea
            ref="textareaRef"
            v-model="inputText"
            class="chat-textarea"
            rows="1"
            :placeholder="composerPlaceholder"
            maxlength="100000"
            aria-label="Message to send"
            @input="onTextareaInput"
            @keydown="onTextareaKeydown"
            @compositionstart="composing = true"
            @compositionend="composing = false"
          />
        </div>
        <button class="btn btn--icon btn--ghost" title="New chat session in the current agent" aria-label="New chat session in the current agent" @click="newSession">
          <Icon name="plus" :size="16" />
        </button>
        <button class="btn btn--icon btn--ghost" title="Export as Markdown" aria-label="Export as Markdown" @click="exportMarkdown">
          <Icon name="download" :size="16" />
        </button>
        <button class="btn btn--icon btn--primary" :title="sendButtonTitle" aria-label="Send" @click="onSend">
          <Icon name="send" :size="16" />
        </button>
        <button v-if="isStreaming" class="btn btn--icon btn--danger" title="Stop current response (Esc)" aria-label="Stop current response" @click="onStop">
          <Icon name="stop" :size="16" />
        </button>
      </div>
    </div>

    <input
      ref="fileInputRef"
      type="file"
      accept="image/png,image/jpeg,image/gif,image/webp,application/pdf,text/plain,text/markdown,text/html,text/csv,application/json,.md,.markdown"
      multiple
      class="hidden"
      @change="onFileInputChange"
    />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import { useAppStore } from '@/stores/app'
import Icon from '@/components/Icon.vue'

/* ── Types ─────────────────────────────────────────────────────────── */

interface Attachment {
  kind: 'inline' | 'staged' | 'inline_pending' | 'uploading'
  local_id: number
  name: string
  mime: string
  size?: number
  data?: string
  dataUrl?: string
  file_uuid?: string
}

interface PendingItem {
  text: string
  attachments: Attachment[]
  intent: string | null
}

interface Message {
  role: string
  text: string
  ts: string | number | null
  artifacts?: any[]
  tool_calls?: any[]
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
}

interface StreamToolCall {
  toolId: string
  name: string
  displayName: string
  inputPreview: string
  isRunning: boolean
  status: '' | 'success' | 'error'
  isError: boolean
  result: string
  resultPreview: string
  isOpen: boolean
}

interface StreamSegment {
  type: 'text'
  raw: string
  html: string
}

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
  artifacts?: any[]
  meta?: any
  interrupted?: boolean
  provenanceKind?: string
  daySeparator?: boolean
  dayLabel?: string
  isRouterStrip?: boolean
  routerState?: string
  gridCells?: any[]
  winnerIdx?: number
}

interface SessionItem {
  key: string
  runStatus: string
  runLabel: string
}

interface SessionGroup {
  label: string
  items: SessionItem[]
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
const SQUILLA_VERBS = ['Watching', 'Tracking', 'Sensing', 'Pulsing', 'Thinking', 'Drafting', 'Polishing']
const SQUILLA_DWELL_MS = 2500

const ATTACHMENT_IMAGE_MIMES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp']
const ATTACHMENT_TEXT_MIMES = ['text/plain', 'text/markdown', 'text/html', 'text/csv', 'application/json']
const ATTACHMENT_ALLOWED_MIMES = [...ATTACHMENT_IMAGE_MIMES, 'application/pdf', ...ATTACHMENT_TEXT_MIMES]
const ATTACHMENT_EXTENSION_MIMES: Record<string, string> = {
  png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg', gif: 'image/gif',
  webp: 'image/webp', pdf: 'application/pdf', txt: 'text/plain', md: 'text/markdown',
  markdown: 'text/markdown', html: 'text/html', htm: 'text/html', csv: 'text/csv', json: 'application/json',
}

const TOOL_EMOJI: Record<string, string> = {
  bash: '&#128187;', read_file: '&#128196;', write_file: '&#9997;', edit_file: '&#9997;',
  web_search: '&#128269;', search: '&#128269;', http_request: '&#127760;', web_fetch: '&#127760;',
  list_files: '&#128194;', memory_search: '&#129504;', memory_store: '&#129504;',
}

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

/* ── DOM refs ──────────────────────────────────────────────────────── */

const threadRef = ref<HTMLElement | null>(null)
const textareaRef = ref<HTMLTextAreaElement | null>(null)
const composerRef = ref<HTMLElement | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
const sessionSearchRef = ref<HTMLInputElement | null>(null)

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

// Streaming
const streamRaw = ref('')
const streamSegments = ref<StreamSegment[]>([])
const streamArtifacts = ref<any[]>([])
const streamToolCalls = ref<StreamToolCall[]>([])
const streamBubble = ref(false)
const streamShowHeader = ref(false)

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
const sessionPopoverOpen = ref(false)
const toolbarPopoverOpen = ref(false)
const sessionSearch = ref('')
const sessionsList = ref<any[]>([])
const sessionListError = ref(false)

// Elevated mode
const elevatedMode = ref('')
const globalElevatedMode = ref('')
const elevatedUnavailable = ref(false)

// Router
const routerEnabled = ref(false)
const toolbarState = ref({ bypass: false, router: true })

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

const elevatedPillText = computed(() => {
  if (elevatedUnavailable.value) return 'Bypass N/A'
  const eff = effectiveElevatedMode.value
  if (elevatedMode.value) return `Session ${eff.toUpperCase()}`
  if (globalElevatedMode.value) return `Global ${globalElevatedMode.value.toUpperCase()}`
  return 'Bypass Off'
})

const toolbarTriggerActive = computed(() => {
  return toolbarState.value.bypass || toolbarState.value.router === false
})

const toolbarTriggerTitle = computed(() => {
  const eff = effectiveElevatedMode.value
  const bypass = eff === 'bypass' || eff === 'full'
  const parts: string[] = []
  if (eff === 'full') parts.push('FULL: Full permission mode active')
  else if (bypass) parts.push('BYPASS: Approvals bypassed')
  if (toolbarState.value.router === false) parts.push('router off')
  return parts.length ? `Run modes: ${parts.join(', ')}` : 'Run modes'
})

const composerPlaceholder = computed(() => {
  return window.innerWidth <= 480 ? 'Message...' : 'Send a message...'
})

const sendButtonTitle = computed(() => {
  if (isCompactInFlightForCurrentSession()) return 'Send (queues until compaction finishes)'
  if (isStreaming.value) return 'Send (queues for after current response)'
  return 'Send'
})

const groupedSessions = computed((): SessionGroup[] => {
  const groups: Record<string, SessionItem[]> = {
    'Web chat': [], CLI: [], 'Sub-agents': [], Agents: [], Sessions: [], Other: [],
  }
  for (const item of sessionsList.value) {
    const key = itemKey(item)
    if (!key || key === 'unknown') continue
    const g = classifyKey(item)
    if (g) groups[g].push({ key, runStatus: normalizeRunStatus(item.status || item.run_status), runLabel: runStatusLabelText(normalizeRunStatus(item.status || item.run_status)) })
  }
  const f = sessionSearch.value.toLowerCase()
  const result: SessionGroup[] = []
  for (const [label, items] of Object.entries(groups)) {
    const visible = f ? items.filter(it => it.key.toLowerCase().includes(f)) : items
    if (visible.length) result.push({ label, items: visible })
  }
  return result
})

const renderedMessages = computed((): RenderedMessage[] => {
  const result: RenderedMessage[] = []
  let prevDay = ''
  let prevRole = ''

  for (let i = 0; i < messages.value.length; i++) {
    const msg = messages.value[i]
    const day = dayKey(msg.ts)

    // Day separator
    if (day && day !== prevDay) {
      result.push({ daySeparator: true, dayLabel: dayLabel(day), role: '', displayRole: '', roleLabel: '', text: '', timeStr: '', showHeader: false })
      prevDay = day
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
      toolCalls: msg.tool_calls,
      artifacts: msg.artifacts,
      meta,
      interrupted: msg.interrupted,
      provenanceKind: msg.provenanceKind,
    })
  }

  return result
})

/* ── Helpers ───────────────────────────────────────────────────────── */

function esc(s: string): string {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

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

function dayLabel(isoDay: string): string {
  if (!isoDay) return ''
  const today = new Date().toISOString().slice(0, 10)
  const yester = new Date(Date.now() - 86400000).toISOString().slice(0, 10)
  if (isoDay === today) return 'Today'
  if (isoDay === yester) return 'Yesterday'
  const d = new Date(isoDay + 'T12:00:00')
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

function truncate(s: string, max = 200): string {
  if (!s || s.length <= max) return s || ''
  return s.slice(0, max) + '…'
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

function itemKey(item: any): string {
  return typeof item === 'string' ? item : (item.key || item.session || item.sessionKey || '')
}

function classifyKey(item: any): string | null {
  const key = itemKey(item)
  if (!key || key === 'unknown') return null
  const channelKind = item?.channel_kind || item?.channelKind || item?.channel || ''
  const sourceKind = item?.source_kind || item?.sourceKind || ''
  if (channelKind === 'webchat' || sourceKind === 'webui') return 'Web chat'
  if (channelKind === 'cli' || sourceKind === 'cli') return 'CLI'
  if (key.startsWith('agent:')) {
    if (key.includes(':webchat')) return 'Web chat'
    if (key.includes(':cli:') || key.includes(':standalone:')) return 'CLI'
    if (key.includes(':subagent')) return 'Sub-agents'
    return 'Agents'
  }
  if (key.startsWith('sess-')) return 'Sessions'
  return 'Other'
}

function toolEmoji(name: string): string {
  return TOOL_EMOJI[name] || '⚡'
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

function attachmentMeta(att: Attachment): string {
  const kb = att.size ? Math.max(1, Math.round(att.size / 1024)) + ' KB' : ''
  const stagedTag = att.kind === 'staged' ? ' • staged' : ''
  if (att.kind === 'inline_pending') return 'Reading...'
  if (att.kind === 'uploading') return 'Uploading...'
  return `${att.mime || ''} ${kb}${stagedTag}`.trim()
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

function renderMarkdown(text: string): string {
  // Simple markdown renderer - preserves the pattern from the original
  // which used Markdown.render(). For now, do basic formatting.
  text = stripProtocolTextLeak(stripDirectiveTags(stripGeneratedArtifactMarkers(text)))
  if (!text) return ''

  // Escape HTML
  let html = esc(text)

  // Code blocks
  html = html.replace(/```(\w+)?\n([\s\S]*?)```/g, (_m, lang, code) => {
    return `<pre class="code-block"><code class="language-${lang || 'text'}">${code}</code></pre>`
  })

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>')

  // Bold
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')

  // Italic
  html = html.replace(/\*([^*]+)\*/g, '<em>$1</em>')

  // Links
  html = html.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')

  // Line breaks
  html = html.replace(/\n/g, '<br>')

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

function artifactMime(artifact: any): string {
  return artifact?.mime ? String(artifact.mime).toLowerCase() : ''
}

function artifactName(artifact: any): string {
  return artifact?.name ? String(artifact.name) : 'artifact'
}

function artifactExtension(name: string): string {
  const trimmed = String(name || '').trim().toLowerCase()
  const idx = trimmed.lastIndexOf('.')
  if (idx < 0 || idx === trimmed.length - 1) return ''
  return trimmed.slice(idx + 1)
}

function artifactCategory(artifact: any): string {
  const mime = artifactMime(artifact)
  if (mime.startsWith('image/')) return 'visual'
  if (ARTIFACT_MIME_CATEGORIES[mime]) return ARTIFACT_MIME_CATEGORIES[mime]
  if (!mime || mime === 'application/octet-stream') {
    const ext = artifactExtension(artifactName(artifact))
    if (ARTIFACT_EXTENSION_CATEGORIES[ext]) return ARTIFACT_EXTENSION_CATEGORIES[ext]
  }
  return 'file'
}

function artifactCategoryLabel(artifact: any): string {
  const cat = artifactCategory(artifact)
  switch (cat) {
    case 'data': return 'data'
    case 'document': return 'doc'
    case 'code': return 'code'
    default: return 'file'
  }
}

function artifactMeta(artifact: any): string {
  const mime = artifact?.mime ? String(artifact.mime) : ''
  const size = artifact?.size ? `${Math.max(1, Math.round(Number(artifact.size) / 1024))} KB` : ''
  return [mime, size].filter(Boolean).join(' · ')
}

function artifactDownloadUrl(artifact: any): string {
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

async function downloadArtifact(artifact: any) {
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

function persistSession(key: string) {
  sessionKey.value = canonicalSessionKey(key)
  try { localStorage.setItem('opensquilla_active_session', sessionKey.value) } catch {}
  try {
    const url = new URL(window.location.href)
    url.searchParams.set('session', sessionKey.value)
    url.searchParams.delete('agent')
    history.replaceState(null, '', url)
  } catch {}
}

function readSessionFromUrl(): string {
  try { return new URLSearchParams(window.location.search).get('session') || '' } catch { return '' }
}

function readAgentFromUrl(): string {
  try { return new URLSearchParams(window.location.search).get('agent') || '' } catch { return '' }
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

function toggleElevatedMode() {
  if (elevatedUnavailable.value) {
    console.warn('Bypass requires a local owner session (loopback only).')
    return
  }
  if (effectiveElevatedMode.value) {
    setElevatedMode('', { toast: true, sync: true })
    return
  }
  const ok = window.confirm('Enable approval bypass for this browser session?')
  if (ok) setElevatedMode('bypass', { toast: true, sync: true })
}

async function onRouterToggle() {
  const enabled = routerEnabled.value
  try {
    await rpc.waitForConnection()
    await rpc.call('config.patch.safe', {
      patches: {
        'squilla_router.enabled': enabled,
        'squilla_router.rollout_phase': enabled ? 'full' : 'observe',
      },
    })
    toolbarState.value.router = enabled
    console.info('Squilla Router:', enabled ? 'ON' : 'OFF')
  } catch (e: any) {
    routerEnabled.value = !enabled
    console.warn('Failed:', e.message)
  }
}

/* ── Session switching ─────────────────────────────────────────────── */

function switchToSession(key: string) {
  if (!key || key === sessionKey.value) {
    sessionPopoverOpen.value = false
    return
  }
  unsubscribeSession()
  sessionKey.value = canonicalSessionKey(key)
  persistSession(key)
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
  sessionPopoverOpen.value = false
}

function switchToTypedSession() {
  const key = sessionSearch.value.trim()
  if (!key) return
  switchToSession(key)
}

function newSession() {
  unsubscribeSession()
  const key = genKey()
  sessionKey.value = key
  persistSession(key)
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

async function toggleSessionPopover() {
  if (sessionPopoverOpen.value) {
    sessionPopoverOpen.value = false
    return
  }
  sessionPopoverOpen.value = true
  sessionSearch.value = ''
  sessionListError.value = false

  nextTick(() => {
    sessionSearchRef.value?.focus()
  })

  try {
    const resp = await fetch('/api/sessions')
    if (resp.ok) {
      const data = await resp.json()
      sessionsList.value = (data.sessions || data.keys || []).filter((s: any) => !!(typeof s === 'string' ? s : (s.key || s.session || s.sessionKey)))
    } else {
      sessionListError.value = true
    }
  } catch {
    sessionListError.value = true
  }
}

function toggleToolbarPopover() {
  toolbarPopoverOpen.value = !toolbarPopoverOpen.value
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
  try {
    await rpc.waitForConnection()
    const params: any = { key: sessionKey.value, since_stream_seq: lastStreamSeq.value }
    const res = await rpc.call('sessions.messages.subscribe', params) as any
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

function isCurrentSessionPayload(payload: any): boolean {
  const key = payload?.key || payload?.session_key || payload?.sessionKey || ''
  return !key || !sessionKey.value || key === sessionKey.value
}

function taskGroupId(payload: any): string {
  const id = payload?.group_id
  return typeof id === 'string' && id ? id : ''
}

function noteTaskGroupActive(payload: any) {
  const gid = taskGroupId(payload)
  if (gid) activeTaskGroups.value.add(gid)
  applySessionRunState(activeTaskGroupRunState(payload))
}

function noteTaskGroupTerminal(payload: any, terminalStatus: string) {
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

function activeTaskGroupRunState(payload: any = {}) {
  return {
    run_status: 'running',
    active_task: { ...(payload || {}), status: 'running', task_group_count: activeTaskGroups.value.size },
  }
}

function sessionChangeIsTerminal(payload: any): boolean {
  const reason = String(payload?.reason || '').toLowerCase()
  if (reason === 'turn_complete' || reason === 'task_terminal') return true
  const lifecycle = String(payload?.status || '').toLowerCase()
  if (['done', 'failed', 'killed', 'timeout'].includes(lifecycle)) return true
  const runStatus = normalizeRunStatus(payload?.run_status || payload?.runStatus)
  return ['failed', 'timeout', 'cancelled', 'interrupted'].includes(runStatus)
}

function syncTerminalSessionChange(payload: any = {}) {
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

function startStreaming() {
  isStreaming.value = true
  applySessionRunState({ run_status: 'running', active_task: { status: 'running' } })
  streamRaw.value = ''
  streamSegments.value = []
  streamArtifacts.value = []
  streamToolCalls.value = []
  streamBubble.value = true
  streamShowHeader.value = lastHeaderRole.value !== 'assistant'
  autoScroll.value = true
  resetStreamIdleTimer()
}

function endStreaming(opts?: { reason?: string }) {
  const wasAborted = opts?.reason === 'aborted'
  hideThinkingIndicator()
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

    // Record the message
    messages.value.push({
      role: 'assistant',
      text: cleanedText,
      ts: new Date().toISOString(),
      artifacts: streamArtifacts.value.slice(),
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

function appendDelta(text: string) {
  if (aborted.value) return
  if (!isStreaming.value) startStreaming()
  streamRaw.value += text

  // Update or create text segment
  if (streamSegments.value.length === 0 || streamSegments.value[streamSegments.value.length - 1].type !== 'text') {
    streamSegments.value.push({ type: 'text', raw: text, html: '' })
  } else {
    const seg = streamSegments.value[streamSegments.value.length - 1]
    seg.raw += text
  }

  // Debounced render
  renderDirty = true
  if (!renderRafId) {
    renderRafId = requestAnimationFrame(flushRender)
  }
}

function flushRender() {
  renderRafId = null
  if (!renderDirty) return

  for (const seg of streamSegments.value) {
    if (seg.type === 'text') {
      seg.html = renderMarkdown(seg.raw)
    }
  }

  renderDirty = false
  if (autoScroll.value) scrollToBottom()
}

function showThinkingIndicator() {
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
  thinkingText.value = `${verb} (${seconds}s)`
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

function onThreadScroll() {
  if (!threadRef.value) return
  const gap = threadRef.value.scrollHeight - threadRef.value.scrollTop - threadRef.value.clientHeight
  autoScroll.value = gap < 60
}

/* ── Tool calls ────────────────────────────────────────────────────── */

function appendToolCall(payload: any) {
  if (!payload) return
  const name = payload.name || payload.tool_name || 'tool'
  const input = typeof payload.input === 'string' ? payload.input : JSON.stringify(payload.input || payload.arguments || '', null, 2)
  const toolId = payload.tool_use_id || ''

  // Check for duplicate
  if (streamToolCalls.value.find(tc => tc.toolId === toolId)) return

  streamToolCalls.value.push({
    toolId,
    name,
    displayName: toolDisplayName(name, input),
    inputPreview: truncate(input, 200),
    isRunning: true,
    status: '',
    isError: false,
    result: '',
    resultPreview: '',
    isOpen: false,
  })

  // Add new text segment after tool
  if (streamSegments.value.length > 0) {
    streamSegments.value.push({ type: 'text', raw: '', html: '' })
  }

  scrollToBottom()
}

function appendToolResult(payload: any) {
  if (!payload) return
  const raw = payload.result || payload.content || payload.output || ''
  const content = typeof raw === 'string' ? raw : JSON.stringify(raw, null, 2)
  const toolId = payload.tool_use_id || ''

  const tc = streamToolCalls.value.find(t => t.toolId === toolId)
  if (tc) {
    tc.isRunning = false
    tc.status = toolResultIsError(payload) ? 'error' : 'success'
    tc.isError = toolResultIsError(payload)
    tc.result = content
    tc.resultPreview = truncate(content, 200)
  }

  scrollToBottom()
}

function toolDisplayName(name: string, input: any): string {
  if (name === 'publish_artifact') {
    const inputObj = typeof input === 'string' ? (() => { try { return JSON.parse(input) } catch { return null } })() : input
    const target = inputObj?.name || inputObj?.path
    if (target) return `${name} - ${target.split(/[\\/]+/).filter(Boolean).pop() || target}`
  }
  return name || 'tool'
}

function toolResultIsError(payload: any): boolean {
  const status = payload?.execution_status || payload?.executionStatus
  if (status && typeof status.status === 'string') {
    return ['error', 'timeout', 'cancelled'].includes(status.status)
  }
  return !!(payload?.is_error || payload?.isError || payload?.error)
}

function showToolResultModal(content: string) {
  // Simple modal via alert for now - can be replaced with a proper modal component
  console.info('Tool result:', content)
}

function appendArtifact(payload: any) {
  if (!payload) return
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

  // Build RPC params
  const params: any = { message: text || 'Describe these attachments', sessionKey: sessionKey.value }
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
    const res = await rpc.call('chat.send', params) as any
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
  if (!textareaRef.value || pendingQueue.value.length === 0) return false
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
          messages.value = []
          clearPendingDrainAfterTerminalTimer()
          setCompactInFlight(false)
          hideCompactStatus()
          pendingQueue.value = []
          contextStatus.value = null
          activeTaskGroups.value.clear()
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
  try {
    await rpc.waitForConnection()
    const data = await rpc.call('chat.history', { sessionKey: sessionKey.value }) as any
    const msgs = data.messages || []

    if (msgs.length === 0) {
      messages.value = []
      lastHeaderRole.value = ''
      lastHeaderDay.value = ''
      return
    }

    messages.value = msgs.map((msg: any) => ({
      role: msg.role,
      text: msg.role === 'user' ? stripTimePrefix(msg.text || '') : msg.text || '',
      ts: msg.timestamp || msg.ts || null,
      artifacts: msg.artifacts || [],
      tool_calls: msg.tool_calls || [],
      attachments: msg.attachments || [],
      provenanceKind: msg.provenance_kind || '',
      provenanceSourceSessionKey: msg.provenance_source_session_key || '',
      provenanceSourceTool: msg.provenance_source_tool || '',
      usage: msg.usage || msg.turn_usage || null,
      model: msg.model || null,
      input: msg.input || msg.input_tokens || null,
      output: msg.output || msg.output_tokens || null,
      messageId: msg.message_id || msg.id || '',
    }))

    lastHeaderRole.value = ''
    lastHeaderDay.value = ''

    nextTick(() => scrollToBottom())
  } catch {
    // History endpoint may not exist yet
  }
}

/* ── Export ────────────────────────────────────────────────────────── */

function exportMarkdown() {
  if (messages.value.length === 0) {
    console.warn('No messages to export')
    return
  }
  let md = `# Chat Export -- ${sessionKey.value}\n\n`
  md += `Exported: ${new Date().toISOString()}\n\n---\n\n`
  messages.value.forEach((msg) => {
    const role = msg.role === 'user' ? 'You' : msg.role === 'assistant' ? 'Assistant' : msg.role
    const time = msg.ts ? ` _(${new Date(msg.ts).toLocaleString()})_` : ''
    md += `### ${role}${time}\n\n${msg.text}\n\n---\n\n`
  })

  const blob = new Blob([md], { type: 'text/markdown' })
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = `chat-${sessionKey.value}.md`
  a.click()
  URL.revokeObjectURL(a.href)
  console.info('Exported as Markdown')
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
  nextTick(() => textareaRef.value?.focus())
}

/* ── Textarea ──────────────────────────────────────────────────────── */

function onTextareaInput() {
  autoResizeTextarea()
  handleSlashInput()
}

function autoResizeTextarea() {
  nextTick(() => {
    const ta = textareaRef.value
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 160) + 'px'
  })
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
    globalElevatedMode.value = normalizeElevatedMode(cfg?.permissions?.default_mode)
    toolbarState.value.bypass = isApprovalBypassMode(effectiveElevatedMode.value)
    await loadCurrentSessionUsage()
  } catch { /* ignore */ }
}

/* ── Event handlers ────────────────────────────────────────────────── */

function isStaleEpoch(payload: any): boolean {
  const ep = payload?.epoch
  if (typeof ep !== 'number' || !Number.isFinite(ep)) return false
  return ep < currentEpoch.value
}

function acceptStreamSeq(payload: any): boolean {
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
  if (sessionPopoverOpen.value) { sessionPopoverOpen.value = false; e.preventDefault(); return }

  if (isStreaming.value) {
    e.preventDefault()
    onStop()
    return
  }

  if (pendingQueue.value.length > 0 && document.activeElement !== textareaRef.value) {
    e.preventDefault()
    popAllPendingIntoComposer()
  }
}

/* ── Click outside popovers ────────────────────────────────────────── */

function onDocumentClick(e: MouseEvent) {
  const target = e.target as HTMLElement
  if (sessionPopoverOpen.value && !target.closest('.chat-session-popover') && !target.closest('.chat-session-chip')) {
    sessionPopoverOpen.value = false
  }
  if (toolbarPopoverOpen.value && !target.closest('.chat-toolbar-popover') && !target.closest('.chat-toolbar-trigger')) {
    toolbarPopoverOpen.value = false
  }
}

/* ── Lifecycle ─────────────────────────────────────────────────────── */

onMounted(async () => {
  // Initialize session key
  const urlSession = readSessionFromUrl()
  const urlAgent = readAgentFromUrl()
  const storedSession = localStorage.getItem('opensquilla_active_session') || ''
  sessionKey.value = canonicalSessionKey(urlSession || (urlAgent ? webchatSessionKey(urlAgent) : storedSession))
  persistSession(sessionKey.value)

  // Load elevated mode
  loadElevatedMode()

  // Load feature toggles
  await loadFeatureToggles()

  // Subscribe to RPC events
  unsubs.push(rpc.on('session.event.text_delta', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendDelta(payload.text || '')
  }))

  unsubs.push(rpc.on('session.event.tool_use_start', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendToolCall(payload)
  }))

  unsubs.push(rpc.on('session.event.tool_result', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendToolResult(payload)
  }))

  unsubs.push(rpc.on('session.event.artifact', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    appendArtifact(payload)
  }))

  unsubs.push(rpc.on('session.event.state_change', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!payload || aborted.value) return
    if (!acceptStreamSeq(payload)) return
    resetStreamIdleTimer()
    const to = payload.to_state || payload.toState || ''
    if (to === 'thinking' && !streamBubble.value) {
      if (!isStreaming.value) startStreaming()
      showThinkingIndicator()
    }
  }))

  unsubs.push(rpc.on('session.event.run_heartbeat', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (aborted.value) return
    if (!acceptStreamSeq(payload)) return
    if (!isStreaming.value) startStreaming()
    resetStreamIdleTimer()
    if (!streamBubble.value) showThinkingIndicator()
  }))

  unsubs.push(rpc.on('session.event.compaction', (payload: any, meta: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    showCompactionToast(payload || {}, meta || {})
  }))

  unsubs.push(rpc.on('session.event.warning', (payload: any) => {
    if (isStaleEpoch(payload)) return
    console.warn((payload && payload.message) || 'Assistant warning')
  }))

  unsubs.push(rpc.on('session.epoch_changed', (payload: any) => {
    const ep = payload?.epoch
    if (typeof ep === 'number' && Number.isFinite(ep) && ep > currentEpoch.value) {
      activeTaskGroups.value.clear()
      currentEpoch.value = ep
    }
  }))

  unsubs.push(rpc.on('sessions.changed', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!isCurrentSessionPayload(payload)) return
    if (sessionChangeIsTerminal(payload)) {
      syncTerminalSessionChange(payload)
      return
    }
    applySessionRunState(payload)
  }))

  unsubs.push(rpc.on('task.queued', (payload: any) => {
    if (!isCurrentSessionPayload(payload)) return
    applySessionRunState({ run_status: 'queued', active_task: { ...(payload || {}), status: 'queued' } })
  }))

  unsubs.push(rpc.on('task.running', (payload: any) => {
    if (!isCurrentSessionPayload(payload)) return
    applySessionRunState({ run_status: 'running', active_task: { ...(payload || {}), status: 'running' } })
  }))

  unsubs.push(rpc.on('session.event.task_group.waiting', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupActive(payload)
  }))

  unsubs.push(rpc.on('session.event.task_group.synthesizing', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupActive(payload)
  }))

  unsubs.push(rpc.on('session.event.task_group.done', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupTerminal(payload, 'succeeded')
  }))

  unsubs.push(rpc.on('session.event.task_group.failed', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    noteTaskGroupTerminal(payload, 'failed')
  }))

  unsubs.push(rpc.on('session.event.router_decision', (payload: any) => {
    if (isStaleEpoch(payload)) return
    if (!acceptStreamSeq(payload)) return
    // Router decision - simplified for now
    console.info('Router decision:', payload)
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
  if (composerRef.value) {
    composerResizeObserver = new ResizeObserver(() => {
      const h = composerRef.value?.getBoundingClientRect().height || 0
      document.documentElement.style.setProperty('--composer-h', h + 'px')
    })
    composerResizeObserver.observe(composerRef.value)
  }

  // Load history
  subscribeSession()
  loadHistory()
  loadSlashCommands()

  // Focus textarea on desktop
  if (window.innerWidth > 768) {
    nextTick(() => textareaRef.value?.focus())
  }
})

onUnmounted(() => {
  unsubs.forEach(fn => fn())
  unsubs = []
  if (renderRafId) { cancelAnimationFrame(renderRafId); renderRafId = null }
  clearStreamIdleTimer()
  clearPendingDrainAfterTerminalTimer()
  if (historySyncTimer) { clearTimeout(historySyncTimer); historySyncTimer = null }
  if (thinkingDelayTimer) { clearTimeout(thinkingDelayTimer); thinkingDelayTimer = null }
  if (thinkingTimer) { clearInterval(thinkingTimer); thinkingTimer = null }
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
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0.75rem 1rem;
  border-bottom: 1px solid var(--border-color, #e5e5e5);
  background: var(--bg-secondary, #f5f5f5);
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
}

.chat-label {
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #666);
  flex-shrink: 0;
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
  font-size: 0.75rem;
  font-weight: 500;
  background: var(--bg-tertiary, #e5e5e5);
  color: var(--text-muted, #666);
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
  font-size: 0.75rem;
  font-weight: 500;
  color: #dc2626;
}

.chat-body {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.chat-thread {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.chat-empty {
  text-align: center;
  color: var(--text-muted, #666);
  padding: 3rem 1rem;
  font-size: 0.875rem;
}

.chat-day-sep {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin: 0.5rem 0;
  font-size: 0.75rem;
  color: var(--text-muted, #666);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.chat-day-sep::before,
.chat-day-sep::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--border-color, #e5e5e5);
}

/* Messages */
.msg {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  max-width: 100%;
  position: relative;
}

.msg.user {
  align-self: flex-end;
  max-width: 80%;
}

.msg.assistant,
.msg.system,
.msg.subagent,
.msg.error {
  align-self: flex-start;
  max-width: 90%;
}

.msg-header {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-muted, #666);
  padding: 0 0.25rem;
}

.role-label {
  text-transform: capitalize;
}

.msg-time {
  font-weight: 400;
  font-size: 0.6875rem;
  color: var(--text-muted, #999);
}

.msg-body {
  padding: 0.625rem 0.875rem;
  border-radius: 0.75rem;
  font-size: 0.875rem;
  line-height: 1.5;
  word-break: break-word;
}

.msg.user .msg-body {
  background: var(--accent-color, #3b82f6);
  color: #fff;
  border-bottom-right-radius: 0.25rem;
}

.msg.assistant .msg-body,
.msg.streaming .msg-body {
  background: var(--bg-secondary, #f5f5f5);
  color: var(--text-primary, #1a1a1a);
  border-bottom-left-radius: 0.25rem;
}

.msg.system .msg-body,
.msg.subagent .msg-body {
  background: var(--bg-tertiary, #e5e5e5);
  color: var(--text-muted, #666);
  font-size: 0.8125rem;
  border-bottom-left-radius: 0.25rem;
}

.msg.error .msg-body {
  background: #fee2e2;
  color: #991b1b;
  border-bottom-left-radius: 0.25rem;
}

.msg.streaming .msg-body {
  opacity: 0.9;
}

/* Message actions */
.msg-actions {
  display: flex;
  gap: 0.25rem;
  opacity: 0;
  transition: opacity 0.15s;
  padding: 0 0.25rem;
}

.msg:hover .msg-actions,
.msg:focus-within .msg-actions {
  opacity: 1;
}

.msg-action {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.25rem;
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-muted, #666);
  border-radius: 0.25rem;
}

.msg-action:hover {
  color: var(--text-primary, #1a1a1a);
  background: var(--bg-tertiary, #e5e5e5);
}

/* Meta footer */
.msg-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  padding: 0 0.25rem;
  font-size: 0.6875rem;
  color: var(--text-muted, #999);
}

.msg-meta__model {
  font-weight: 500;
}

.msg-meta__tokens {
  font-family: monospace;
}

.msg-meta__saved {
  display: inline-flex;
  align-items: center;
  gap: 0.125rem;
  color: #ea580c;
  font-weight: 500;
}

.msg-meta__saved-flame {
  width: 1em;
  height: 1em;
}

.msg-interrupt-mark {
  font-size: 0.75rem;
  font-style: italic;
  color: var(--text-muted, #999);
  padding: 0 0.25rem;
}

/* Thinking indicator */
.thinking-body {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.thinking-status {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.typing-indicator {
  display: flex;
  gap: 0.25rem;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted, #999);
  animation: typingBounce 1.4s infinite ease-in-out both;
}

.dot:nth-child(1) { animation-delay: -0.32s; }
.dot:nth-child(2) { animation-delay: -0.16s; }

@keyframes typingBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}

.thinking-elapsed {
  font-size: 0.75rem;
  color: var(--text-muted, #666);
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
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--text-muted, #666);
}

.chat-pending-clear {
  font-size: 0.75rem;
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
  font-size: 0.75rem;
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
  font-size: 0.75rem;
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
  padding: 0.5rem 1rem;
  border-top: 1px solid var(--border-color, #e5e5e5);
  background: var(--bg-primary, #fff);
  flex-shrink: 0;
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
  background: var(--bg-secondary, #f5f5f5);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.375rem;
  font-size: 0.75rem;
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

.chat-input-bar {
  display: flex;
  align-items: flex-end;
  gap: 0.375rem;
}

.chat-input-wrap {
  flex: 1;
  min-width: 0;
}

.chat-textarea {
  width: 100%;
  min-height: 36px;
  max-height: 160px;
  padding: 0.5rem 0.75rem;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.5rem;
  background: var(--bg-primary, #fff);
  color: var(--text-primary, #1a1a1a);
  font-size: 0.875rem;
  line-height: 1.5;
  resize: none;
  outline: none;
  font-family: inherit;
}

.chat-textarea:focus {
  border-color: var(--accent-color, #3b82f6);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
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

.btn--ghost {
  background: none;
  border-color: transparent;
  color: var(--text-muted, #666);
}

.btn--ghost:hover {
  background: var(--bg-secondary, #f5f5f5);
  color: var(--text-primary, #1a1a1a);
}

.btn--primary {
  background: var(--accent-color, #3b82f6);
  color: #fff;
  border-color: var(--accent-color, #3b82f6);
}

.btn--primary:hover {
  opacity: 0.9;
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
  font-size: 0.75rem;
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
  font-size: 0.75rem;
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

/* Tool calls */
.chat-tools-collapse {
  margin-top: 0.5rem;
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.5rem;
  overflow: hidden;
}

.chat-tools-summary {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
  font-weight: 500;
  cursor: pointer;
  background: var(--bg-secondary, #f5f5f5);
  user-select: none;
}

.chat-tools-collapse--running .chat-tools-summary {
  cursor: default;
  opacity: 0.7;
}

.chat-tools-icon {
  font-size: 1rem;
}

.chat-tools-body {
  padding: 0.5rem 0.75rem;
  font-size: 0.8125rem;
}

.chat-tool-input {
  padding: 0.5rem;
  background: var(--bg-tertiary, #e5e5e5);
  border-radius: 0.25rem;
  font-family: monospace;
  font-size: 0.75rem;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
}

.chat-tool-result {
  margin-top: 0.5rem;
  padding: 0.5rem;
  background: #f0fdf4;
  border-radius: 0.25rem;
  font-size: 0.8125rem;
}

.chat-tool-result--error {
  background: #fef2f2;
}

.chat-tool-result-preview {
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 120px;
  overflow-y: auto;
}

.chat-tool-view-btn {
  margin-top: 0.375rem;
}

/* Artifacts */
.msg-artifacts {
  margin-top: 0.5rem;
}

.msg-artifact-gallery,
.msg-artifact-files {
  display: flex;
  flex-wrap: wrap;
  gap: 0.375rem;
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
  font-size: 0.75rem;
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
  display: inline-flex;
  align-items: center;
  gap: 0.375rem;
  padding: 0.375rem 0.625rem;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.375rem;
  font-size: 0.8125rem;
  cursor: pointer;
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
  font-size: 0.75rem;
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
  font-size: 0.75rem;
  overflow-x: auto;
  max-height: 200px;
  overflow-y: auto;
}

/* Router FX */
.router-fx {
  margin: 0.5rem 0;
  padding: 0.75rem;
  background: var(--bg-secondary, #f5f5f5);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.5rem;
}

.router-fx-header {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0.5rem;
  font-size: 0.75rem;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-muted, #666);
  margin-bottom: 0.5rem;
}

.router-fx-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0.375rem;
}

.router-fx-cell {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0.375rem;
  background: var(--bg-primary, #fff);
  border: 1px solid var(--border-color, #e5e5e5);
  border-radius: 0.25rem;
  font-size: 0.6875rem;
  text-align: center;
  min-height: 32px;
}

.router-fx-cell.win {
  background: #d1fae5;
  border-color: #34d399;
  font-weight: 600;
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
  font-size: 0.75rem;
  font-weight: 600;
}

/* Dark mode adjustments */
:root[data-theme="dark"] .msg.user .msg-body {
  background: #2563eb;
}

:root[data-theme="dark"] .msg.assistant .msg-body,
:root[data-theme="dark"] .msg.streaming .msg-body {
  background: #374151;
  color: #f3f4f6;
}

:root[data-theme="dark"] .chat-textarea {
  background: #1f2937;
  border-color: #374151;
  color: #f3f4f6;
}

:root[data-theme="dark"] .chat-session-chip,
:root[data-theme="dark"] .attachment-chip,
:root[data-theme="dark"] .chat-pending-chip,
:root[data-theme="dark"] .msg-artifact-chip,
:root[data-theme="dark"] .chat-session-popover,
:root[data-theme="dark"] .chat-toolbar-popover,
:root[data-theme="dark"] .chat-slash {
  background: #1f2937;
  border-color: #374151;
}

:root[data-theme="dark"] .chat-header,
:root[data-theme="dark"] .chat-composer,
:root[data-theme="dark"] .chat-pending {
  background: #111827;
  border-color: #374151;
}

:root[data-theme="dark"] .chat-session-popover-item:hover,
:root[data-theme="dark"] .chat-session-popover-item.is-current,
:root[data-theme="dark"] .chat-slash-item:hover,
:root[data-theme="dark"] .chat-slash-item--active {
  background: #374151;
}

/* Mobile */
@media (max-width: 768px) {
  .chat-header {
    padding: 0.5rem 0.75rem;
  }

  .chat-session-chip {
    max-width: 180px;
  }

  .msg.user {
    max-width: 90%;
  }

  .msg.assistant,
  .msg.system,
  .msg.subagent,
  .msg.error {
    max-width: 95%;
  }

  .chat-thread {
    padding: 0.75rem;
  }

  .chat-composer {
    padding: 0.5rem 0.75rem;
  }

  .router-fx-grid {
    grid-template-columns: repeat(3, 1fr);
  }
}
</style>

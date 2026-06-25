<template>
  <div class="tool-timeline" :class="{ 'tool-timeline--checklist': variant === 'checklist' }">
  <section
    v-if="summary"
    class="run-trace__summary control-stat-grid control-stat-grid--fixed"
    style="--control-stat-columns: 5"
  >
    <div class="control-stat control-stat--static">
      <div class="control-stat__label">Status</div>
      <div class="control-stat__value">
        <span v-if="summary.loading" class="run-trace__skeleton" aria-hidden="true" />
        <template v-else-if="summary.status">
          <span
            class="run-trace__dot"
            :class="`run-trace__dot--${statusTone}`"
            :aria-label="statusLabel"
          />
          {{ statusLabel }}
        </template>
        <template v-else>—</template>
      </div>
    </div>
    <div class="control-stat control-stat--static">
      <div class="control-stat__label">Executor</div>
      <div class="control-stat__value run-trace__summary-text">
        <span v-if="summary.loading" class="run-trace__skeleton" aria-hidden="true" />
        <template v-else>{{ summary.executor || '—' }}</template>
      </div>
    </div>
    <div class="control-stat control-stat--static">
      <div class="control-stat__label">Time</div>
      <div class="control-stat__value control-stat__value--mono">
        <span v-if="summary.loading" class="run-trace__skeleton" aria-hidden="true" />
        <template v-else>{{ fmtMs(summary.elapsedMs) }}</template>
      </div>
    </div>
    <div class="control-stat control-stat--static">
      <div class="control-stat__label">Tokens</div>
      <div class="control-stat__value control-stat__value--mono">
        <span v-if="summary.loading" class="run-trace__skeleton" aria-hidden="true" />
        <template v-else>{{ fmtTok(summary.tokens) }}</template>
      </div>
    </div>
    <div class="control-stat control-stat--static">
      <div class="control-stat__label">Steps</div>
      <div class="control-stat__value control-stat__value--mono">
        <span v-if="summary.loading" class="run-trace__skeleton" aria-hidden="true" />
        <template v-else>{{ summary.steps != null ? summary.steps : '—' }}</template>
      </div>
    </div>
  </section>
  <TransitionGroup name="tool-row" tag="div" class="tool-row-group">
  <template v-for="item in visibleItems" :key="item.key">
    <div v-if="item.type === 'text'" class="msg-ai-text" v-html="item.html" />
    <button
      v-else-if="item.type === 'overflow'"
      type="button"
      class="tool-overflow-note"
      title="Show all calls"
      @click="showAllRows = true"
    >
      …{{ item.hiddenCount }} earlier calls
    </button>
    <div v-else class="step-card">
      <div
        class="step-group"
        :class="{
          'step-group--running': item.group.isRunning,
          'step-group--error': item.group.isError,
          'is-open': groupOpen(item.group),
        }"
      >
        <!-- Multi-call batches keep a group header; single calls render as one row. -->
        <template v-if="item.group.calls.length > 1">
          <button
            type="button"
            class="tool-row tool-row--group"
            :data-op="item.group.operationKey"
            :aria-expanded="groupOpen(item.group)"
            @click="$emit('toggleGroup', item.group.groupId)"
          >
            <span class="tool-row__bullet" :class="groupBulletClass(item.group)" aria-hidden="true" />
            <span class="tool-row__label">{{ item.group.label }}</span>
            <span class="step-count">{{ item.group.calls.length }} calls</span>
            <span v-if="item.group.secondary" class="tool-row__arg">{{ item.group.secondary }}</span>
            <span class="tool-row__trailing">
              <span class="tool-row__status">{{ resolvedGroupStatusText(item.group) }}</span>
              <Icon class="step-chevron" name="chevronRight" :size="14" />
            </span>
          </button>
          <div v-if="groupOpen(item.group)" class="step-group-members">
            <div v-for="call in item.group.calls" :key="call.renderKey" class="tool-row-wrap">
              <button
                type="button"
                class="tool-row tool-row--member"
                :class="rowClass(call)"
                :data-op="operationKey(call)"
                :aria-expanded="callOpen(call)"
                @click="$emit('toggleItem', call.renderKey)"
              >
                <span class="tool-row__bullet" :class="bulletClass(call)" aria-hidden="true" />
                <span class="tool-row__label tool-row__label--member">{{ call.displayName }}</span>
                <span v-if="resolvedSecondaryText(call)" class="tool-row__arg">{{ resolvedSecondaryText(call) }}</span>
                <span class="tool-row__trailing">
                  <span v-if="resultCountText(call)" class="tool-row__status">{{ resultCountText(call) }}</span>
                  <span v-if="elapsedFor(call)" class="tool-row__elapsed">{{ elapsedFor(call) }}</span>
                  <Icon v-if="iconFor(call).glyph === 'check'" class="tool-row__state-icon tool-row__state-icon--ok" name="check" :size="13" />
                  <Icon v-else-if="iconFor(call).glyph === 'x'" class="tool-row__state-icon tool-row__state-icon--err" name="x" :size="13" />
                  <Icon class="step-chevron" name="chevronRight" :size="14" />
                </span>
              </button>
              <div v-if="callOpen(call)" class="tool-row-body">
                <ToolRowSections :call="call" :label="call.displayName" @show-result="forwardShowResult" />
              </div>
            </div>
          </div>
        </template>
        <template v-else>
          <div v-for="call in item.group.calls" :key="call.renderKey" class="tool-row-wrap">
            <button
              type="button"
              class="tool-row"
              :class="rowClass(call)"
              :data-op="operationKey(call)"
              :aria-expanded="callOpen(call)"
              @click="$emit('toggleItem', call.renderKey)"
            >
              <span class="tool-row__bullet" :class="bulletClass(call)" aria-hidden="true" />
              <span class="tool-row__label">{{ item.group.label }}</span>
              <span v-if="resolvedSecondaryText(call)" class="tool-row__arg">{{ resolvedSecondaryText(call) }}</span>
              <span class="tool-row__trailing">
                <span v-if="resultCountText(call)" class="tool-row__status">{{ resultCountText(call) }}</span>
                <span v-if="elapsedFor(call)" class="tool-row__elapsed">{{ elapsedFor(call) }}</span>
                <Icon v-if="iconFor(call).glyph === 'check'" class="tool-row__state-icon tool-row__state-icon--ok" name="check" :size="13" />
                <Icon v-else-if="iconFor(call).glyph === 'x'" class="tool-row__state-icon tool-row__state-icon--err" name="x" :size="13" />
                <Icon class="step-chevron" name="chevronRight" :size="14" />
              </span>
            </button>
            <div v-if="callOpen(call)" class="tool-row-body">
              <ToolRowSections :call="call" :label="item.group.label" @show-result="forwardShowResult" />
            </div>
          </div>
        </template>
      </div>
    </div>
  </template>
  </TransitionGroup>
  </div>
</template>

<script lang="ts">
import { defineComponent, h, type PropType } from 'vue'
import type { ChatToolCallRenderItem } from '@/types/chat'

const SECTION_PREVIEW_LIMIT = 200

function parseToolResultRecord(raw: string): Record<string, unknown> | null {
  const text = String(raw || '').trim()
  if (!text.startsWith('{')) return null
  try {
    const parsed = JSON.parse(text)
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : null
  } catch {
    return null
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function asNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function webDiagnosticsSummary(raw: string): string {
  const payload = parseToolResultRecord(raw)
  if (!payload) return ''
  const diagnostics = asRecord(payload.diagnostics)
  if (!diagnostics) return ''

  const attempts = Array.isArray(payload.provider_attempts)
    ? payload.provider_attempts
    : Array.isArray(diagnostics.provider_attempts)
      ? diagnostics.provider_attempts
      : []
  const successfulAttempt = attempts
    .map(item => asRecord(item))
    .find(item => item?.status === 'success' && item?.provider)
  const selected = String(
    diagnostics.selected_provider ||
    payload.provider ||
    successfulAttempt?.provider ||
    '',
  )
  const fallbackFrom = String(diagnostics.fallback_from || '')
  const fetchedCount = asNumber(diagnostics.fetched_count)
  const fetchFailedCount = asNumber(diagnostics.fetch_failed_count)
  const returnedChars = asNumber(diagnostics.returned_chars)
  const truncated = diagnostics.budget_clamped === true

  const parts: string[] = []
  if (selected) parts.push(`provider ${selected}`)
  if (attempts.length) parts.push(`${attempts.length} attempt${attempts.length === 1 ? '' : 's'}`)
  if (fallbackFrom) parts.push(`fallback from ${fallbackFrom}`)
  if (fetchedCount !== null) parts.push(`${fetchedCount} fetched`)
  if (fetchFailedCount) parts.push(`${fetchFailedCount} fetch failed`)
  if (returnedChars !== null) parts.push(`${returnedChars} chars`)
  if (truncated) parts.push('truncated')
  return parts.join(' · ')
}

// Labeled input / result / error sections shown in an expanded row body.
const ToolRowSections = defineComponent({
  name: 'ToolRowSections',
  props: {
    call: { type: Object as PropType<ChatToolCallRenderItem>, required: true },
    label: { type: String, required: true },
  },
  emits: ['showResult'],
  setup(props, { emit }) {
    return () => {
      const call = props.call
      const sections = []
      if (call.inputPreview) {
        const fullInput = call.inputRaw || ''
        sections.push(h('section', { class: 'tool-row-section' }, [
          h('div', { class: 'tool-row-section__label' }, 'input'),
          h('pre', { class: 'tool-row-section__pre' }, call.inputPreview),
          fullInput.length > SECTION_PREVIEW_LIMIT
            ? h('button', {
                type: 'button',
                class: 'step-view-btn',
                onClick: (event: Event) => {
                  event.stopPropagation()
                  emit('showResult', fullInput, `${props.label} · input`)
                },
              }, 'view full')
            : null,
        ]))
      }
      const diagnostics = webDiagnosticsSummary(call.result)
      if (diagnostics) {
        sections.push(h('section', { class: 'tool-row-section' }, [
          h('div', { class: 'tool-row-section__label' }, 'diagnostics'),
          h('pre', { class: 'tool-row-section__pre' }, diagnostics),
        ]))
      }
      if (call.result) {
        const kind = call.isError ? 'error' : 'result'
        sections.push(h('section', {
          class: ['tool-row-section', { 'tool-row-section--error': call.isError }],
        }, [
          h('div', { class: 'tool-row-section__label' }, kind),
          h('pre', { class: 'tool-row-section__pre' }, call.resultPreview),
          call.result.length > SECTION_PREVIEW_LIMIT
            ? h('button', {
                type: 'button',
                class: 'step-view-btn',
                onClick: (event: Event) => {
                  event.stopPropagation()
                  emit('showResult', call.result, `${props.label} · ${kind}`)
                },
              }, 'view full')
            : null,
        ]))
      }
      return sections
    }
  },
})

export default { components: { ToolRowSections } }
</script>

<script setup lang="ts">
import { computed, ref } from 'vue'
import Icon from '@/components/Icon.vue'
import type {
  ChatStreamTimelineItem,
  ChatToolCallGroup,
} from '@/types/chat'
import type { NodeStep, RunTraceStatus, RunTraceSummary } from '@/types/runTrace'
import {
  toolGroupStatusText as defaultToolGroupStatusText,
  toolSecondaryText as defaultToolSecondaryText,
  toolOperationKey,
  toolResultCount,
} from '@/utils/chat/toolDisplay'
import { toolState } from '@/utils/chat/toParts'
import { composeTree, statusVisual, type StatusVisual } from '@/components/run/runTrace'

const MAX_TOOL_ROWS = 30

// Reads and searches collapse to a pill by default; writes, exec, and unknown
// tools stay expanded; error rows auto-expand. Manual toggles invert the
// default, so a user collapse is always respected.
const COLLAPSED_BY_DEFAULT = new Set(['web.discover', 'web.search', 'web.read', 'file.inspect', 'memory.search'])

type TimelineRenderItem =
  | ChatStreamTimelineItem
  | { type: 'overflow'; key: string; hiddenCount: number }

const props = defineProps<{
  // Chat path: the proven timeline shape (full group data). The lifted markup
  // renders this unchanged.
  items?: ChatStreamTimelineItem[]
  // Flat path: SessionInspect / Logs pass NodeStep[]; RunTrace composes the tree.
  steps?: NodeStep[]
  // summary strip; omit to hide it entirely.
  summary?: RunTraceSummary
  // Open-state is caller-owned (chat keeps its toggle store; non-chat surfaces
  // use useRunTrace()).
  isToolGroupOpen?: (groupId: string) => boolean
  isToolItemOpen?: (renderKey: string) => boolean
  // Label helpers are injected; default to the toolDisplay exports when omitted.
  toolGroupStatusText?: (group: ChatToolCallGroup) => string
  toolStatusText?: (call: ChatToolCallRenderItem) => string
  toolSecondaryText?: (call: ChatToolCallRenderItem) => string
  // Live streams provide real per-call timings; replayed history omits this
  // prop, so no fabricated elapsed badges appear.
  toolElapsedText?: (call: ChatToolCallRenderItem) => string
  // 'checklist' drives the live work-card presentation: a running row shows a
  // pulsing ring, a completed row dims, an error row stays open. History
  // omits this, keeping the default pill timeline untouched.
  variant?: 'checklist'
}>()

const emit = defineEmits<{
  toggleGroup: [groupId: string]
  toggleItem: [renderKey: string]
  showResult: [content: string, title: string]
}>()

const showAllRows = ref(false)

// Chat passes `items` (proven group data); non-chat surfaces pass flat steps,
// which compose into the same tool-group timeline shape so the markup never
// branches on input source.
const resolvedItems = computed<ChatStreamTimelineItem[]>(() => {
  if (props.items) return props.items
  return composeTree(props.steps ?? []).map((node): ChatStreamTimelineItem => {
    const members = node.children.length ? node.children.map(child => child.step) : [node.step]
    const calls = members.map(stepToRenderItem)
    const isError = calls.some(call => call.isError || call.status === 'error')
    const isRunning = calls.some(call => call.isRunning)
    const status: '' | 'success' | 'error' = isError
      ? 'error'
      : (calls.every(call => call.status === 'success') ? 'success' : '')
    const group: ChatToolCallGroup = {
      groupId: node.step.id,
      operationKey: node.step.operationKey,
      label: node.step.title,
      iconName: 'gear',
      calls,
      secondary: '',
      isRunning,
      isError,
      status,
    }
    return { type: 'tool-group', key: node.step.id, group }
  })
})

function stepToRenderItem(step: NodeStep): ChatToolCallRenderItem {
  const status: '' | 'success' | 'error' = step.state === 'output-error'
    ? 'error'
    : (step.state === 'output-available' ? 'success' : '')
  return {
    toolId: step.id,
    renderKey: step.id,
    name: step.operationKey,
    displayName: step.title,
    inputRaw: step.input,
    inputPreview: step.inputPreview ?? '',
    isRunning: step.state === 'input-available',
    status,
    isError: step.isError ?? step.state === 'output-error',
    result: step.output ?? '',
    resultPreview: step.outputPreview ?? '',
    isOpen: false,
  }
}

const totalCalls = computed(() => resolvedItems.value.reduce(
  (count, item) => item.type === 'tool-group' ? count + item.group.calls.length : count,
  0,
))

// Cap rendered tool rows per turn; earliest calls collapse into one note.
const visibleItems = computed<TimelineRenderItem[]>(() => {
  if (showAllRows.value || totalCalls.value <= MAX_TOOL_ROWS) return resolvedItems.value
  let toHide = totalCalls.value - MAX_TOOL_ROWS
  const out: TimelineRenderItem[] = [{ type: 'overflow', key: 'overflow', hiddenCount: toHide }]
  for (const item of resolvedItems.value) {
    if (item.type !== 'tool-group' || toHide <= 0) {
      out.push(item)
      continue
    }
    if (item.group.calls.length <= toHide) {
      toHide -= item.group.calls.length
      continue
    }
    out.push({ ...item, group: { ...item.group, calls: item.group.calls.slice(toHide) } })
    toHide = 0
  }
  return out
})

function operationKey(call: ChatToolCallRenderItem): string {
  return toolOperationKey(call.name)
}

function callDefaultOpen(call: ChatToolCallRenderItem): boolean {
  if (call.isError || call.status === 'error') return true
  return !COLLAPSED_BY_DEFAULT.has(operationKey(call))
}

function callOpen(call: ChatToolCallRenderItem): boolean {
  // A recorded toggle inverts the default, so error auto-expand still honors
  // an explicit user collapse.
  return callDefaultOpen(call) !== isItemOpen(call.renderKey)
}

function groupOpen(group: ChatToolCallGroup): boolean {
  const defaultOpen = group.calls.some(callDefaultOpen)
  return defaultOpen !== isGroupOpen(group.groupId)
}

function isGroupOpen(groupId: string): boolean {
  return props.isToolGroupOpen?.(groupId) ?? false
}

function isItemOpen(renderKey: string): boolean {
  return props.isToolItemOpen?.(renderKey) ?? false
}

function iconFor(call: ChatToolCallRenderItem): StatusVisual {
  return statusVisual(toolState(call))
}

function rowClass(call: ChatToolCallRenderItem) {
  return {
    'tool-row--running': call.isRunning,
    'tool-row--error': call.status === 'error' || call.isError,
    'is-open': callOpen(call),
  }
}

function bulletClass(call: ChatToolCallRenderItem) {
  return {
    'tool-row__bullet--running': call.isRunning,
    'tool-row__bullet--ok': call.status === 'success',
    'tool-row__bullet--err': call.status === 'error' || call.isError,
  }
}

function groupBulletClass(group: ChatToolCallGroup) {
  return {
    'tool-row__bullet--running': group.isRunning,
    'tool-row__bullet--ok': group.status === 'success',
    'tool-row__bullet--err': group.isError,
  }
}

function resultCountText(call: ChatToolCallRenderItem): string {
  if (call.isRunning || call.isError) return ''
  const count = toolResultCount(call.result)
  return count === null ? '' : `${count} results`
}

function elapsedFor(call: ChatToolCallRenderItem): string {
  return props.toolElapsedText?.(call) || ''
}

function resolvedGroupStatusText(group: ChatToolCallGroup): string {
  return (props.toolGroupStatusText ?? defaultToolGroupStatusText)(group)
}

function resolvedSecondaryText(call: ChatToolCallRenderItem): string {
  return (props.toolSecondaryText ?? defaultToolSecondaryText)(call)
}

function forwardShowResult(content: string, title: string) {
  emit('showResult', content, title)
}

// summary strip. The whole-run status rolls up to a dot tone + label; unknown
// scalars render an em-dash, never 0/blank.
const STATUS_TONE: Record<RunTraceStatus, string> = {
  idle: 'idle',
  queued: 'warn',
  running: 'running',
  success: 'ok',
  error: 'err',
  cancelled: 'idle',
}

const STATUS_LABEL: Record<RunTraceStatus, string> = {
  idle: 'Idle',
  queued: 'Queued',
  running: 'Running',
  success: 'Done',
  error: 'Failed',
  cancelled: 'Cancelled',
}

const statusTone = computed(() => {
  const status = props.summary?.status
  return status ? STATUS_TONE[status] : 'idle'
})

const statusLabel = computed(() => {
  const status = props.summary?.status
  return status ? STATUS_LABEL[status] : '—'
})

function fmtMs(ms?: number | null): string {
  if (ms == null || !Number.isFinite(ms)) return '—'
  if (ms < 1000) return `${Math.round(ms)}ms`
  const seconds = ms / 1000
  if (seconds < 60) return `${+seconds.toFixed(1)}s`
  const minutes = Math.floor(seconds / 60)
  const rest = Math.round(seconds % 60)
  return `${minutes}m ${rest}s`
}

function fmtTok(n?: number | null): string {
  if (n == null || !Number.isFinite(n)) return '—'
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${+(n / 1_000).toFixed(1)}k`
  return String(n)
}
</script>

<style scoped>
.msg-ai-text {
  font-size: 0.875rem;
  line-height: 1.6;
  color: var(--text);
  word-break: break-word;
  margin-bottom: 0.5rem;
}

.msg-ai-text :deep(p) { margin: 0.375rem 0; }
.msg-ai-text :deep(p:first-child) { margin-top: 0; }
.msg-ai-text :deep(ul), .msg-ai-text :deep(ol) { margin: 0.375rem 0; padding-left: 1.25rem; }
.msg-ai-text :deep(li) { margin: 0.125rem 0; }
.msg-ai-text :deep(code) {
  background: var(--bg-hover);
  padding: 0.0625rem 0.25rem;
  border-radius: 3px;
  font-family: var(--font-mono);
  font-size: 0.8125rem;
  color: var(--text-muted);
}
.msg-ai-text :deep(pre) {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 0.625rem;
  overflow-x: auto;
  margin: 0.375rem 0;
}
.msg-ai-text :deep(pre code) {
  background: transparent;
  padding: 0;
}

.step-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0.25rem;
  overflow: hidden;
  margin: 0.625rem 0;
  box-shadow: var(--shadow-xs);
}

.step-group {
  border-radius: 7px;
}

.tool-overflow-note {
  display: block;
  margin: 0.375rem 0;
  padding: 0.25rem 0.5rem;
  border: 0;
  background: transparent;
  font: inherit;
  font-size: 0.8125rem;
  color: var(--text-dim);
  cursor: pointer;
  text-align: left;
}

.tool-overflow-note:hover {
  color: var(--text-muted);
  text-decoration: underline;
}

.tool-overflow-note:focus-visible {
  outline: none;
  border-radius: 4px;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 45%, transparent);
}

.tool-row {
  display: flex;
  align-items: center;
  gap: 0.625rem;
  width: 100%;
  padding: 0.625rem 0.875rem;
  cursor: pointer;
  border: 0;
  border-radius: 6px;
  background: transparent;
  font: inherit;
  text-align: left;
  transition: background 0.12s ease, color 0.12s ease;
  min-height: 2.5rem;
  color: inherit;
}

.tool-row:hover {
  background: var(--bg-hover);
}

.tool-row:focus-visible {
  outline: none;
  box-shadow: inset 0 0 0 2px color-mix(in srgb, var(--accent) 45%, transparent);
}

.tool-row.is-open,
.step-group.is-open > .tool-row--group {
  background: var(--bg-elevated);
}

.tool-row--running {
  background: color-mix(in srgb, var(--accent) 5%, transparent);
}

.tool-row--member {
  padding: 0.5625rem 0.75rem;
}

.tool-row__bullet {
  width: 0.4375rem;
  height: 0.4375rem;
  border-radius: 999px;
  background: var(--text-dim);
  flex-shrink: 0;
}

.tool-row__bullet--running {
  background: var(--accent);
  animation: live-pulse var(--dur-pulse) var(--ease-standard) infinite;
}

.tool-row__bullet--ok {
  background: var(--ok);
}

.tool-row__bullet--err {
  background: var(--danger);
}

.tool-row__label {
  font-size: 0.8125rem;
  font-weight: 500;
  color: var(--text);
  line-height: 1.4;
  flex-shrink: 0;
}

.tool-row__label--member {
  font-size: 0.765625rem;
  color: var(--text-muted);
  max-width: 14rem;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-row--error .tool-row__label,
.tool-row--error .tool-row__status {
  color: var(--danger);
}

.tool-row__arg {
  min-width: 0;
  flex: 1;
  color: var(--text-dim);
  font-size: 0.8125rem;
  line-height: 1.4;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-row__trailing {
  display: flex;
  align-items: center;
  gap: 0.375rem;
  flex-shrink: 0;
  margin-left: auto;
  color: var(--text-dim);
}

.tool-row__status {
  font-size: 0.8125rem;
  color: var(--text-dim);
  white-space: nowrap;
}

.tool-row__elapsed {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0.0625rem 0.375rem;
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-hover);
  white-space: nowrap;
}

.tool-row--running .tool-row__elapsed {
  color: var(--accent);
  background: color-mix(in srgb, var(--accent) 10%, transparent);
}

.tool-row__state-icon--ok {
  color: var(--ok);
}

.tool-row__state-icon--err {
  color: var(--danger);
}

.step-count {
  flex-shrink: 0;
  font-size: 0.6875rem;
  line-height: 1.3;
  padding: 0.0625rem 0.375rem;
  border-radius: 999px;
  color: var(--text-muted);
  background: var(--bg-hover);
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
  background: var(--hairline);
}

.tool-row-body {
  padding: 0 0.875rem 0.5rem;
}

.step-chevron {
  transition: transform 0.12s ease;
}

.tool-row.is-open .step-chevron,
.step-group.is-open > .tool-row--group .step-chevron {
  transform: rotate(90deg);
}

/* ── Run summary strip (Status / Executor / Time / Tokens / Steps) ──────
   Reuses the global control-stat / control-stat-grid primitives; only the
   status dot, skeleton, and the value text overrides live here. */
.run-trace__summary {
  margin: 0 0 0.625rem;
}

.run-trace__summary .control-stat__value {
  align-items: center;
  display: flex;
  font-size: 0.9375rem;
  gap: 0.375rem;
}

.run-trace__summary-text {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-trace__dot {
  border-radius: 999px;
  flex-shrink: 0;
  height: 0.5rem;
  width: 0.5rem;
}

.run-trace__dot--ok { background: var(--ok); }
.run-trace__dot--err { background: var(--danger); }
.run-trace__dot--warn { background: var(--warn); }
.run-trace__dot--running {
  background: var(--accent);
  animation: live-pulse var(--dur-pulse) var(--ease-standard) infinite;
}
.run-trace__dot--idle { background: var(--text-dim); }

.run-trace__skeleton {
  background: linear-gradient(
    90deg,
    var(--bg-hover) 25%,
    var(--bg-elevated) 50%,
    var(--bg-hover) 75%
  );
  background-size: 200% 100%;
  border-radius: var(--radius-sm);
  display: inline-block;
  height: 1em;
  width: 70%;
  animation: run-trace-shimmer 1.4s ease-in-out infinite;
}

@keyframes run-trace-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* ── Checklist variant (live work card) ───────────────────────────────
   The wrapper is layout-neutral for history; in the work card it stacks
   the tool rows into a single vertical sequence the eye can track. */
.tool-timeline {
  display: contents;
}

.tool-timeline--checklist {
  display: flex;
  flex-direction: column;
  gap: 0.125rem;
}

/* Flatten the per-group card chrome so the rows read as one running list. */
.tool-timeline--checklist .step-card {
  margin: 0;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

/* A running row earns a steady outlined ring; completed rows dim so attention
   stays on what is in flight. The single live signal is the pulsing bullet —
   the ring is static so a running row carries one rhythm, not two. */
.tool-timeline--checklist .tool-row--running {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 44%, transparent);
  border-radius: 6px;
}

.tool-timeline--checklist .tool-row__bullet--ok {
  animation: checklistCheckIn 0.2s var(--ease-press, ease-out) both;
}

.tool-timeline--checklist .tool-row__state-icon--ok {
  animation: checklistCheckIn 0.2s var(--ease-press, ease-out) both;
}

/* Completed, non-open rows soften and tuck in — kept for traceability, not
   deleted — so the running row reads as the live focus. */
.tool-timeline--checklist .tool-row-wrap:has(.tool-row--running) {
  opacity: 1;
}

.tool-timeline--checklist
  .tool-row:not(.tool-row--running):not(.tool-row--error):not(.is-open) {
  opacity: 0.62;
  transition: opacity 0.2s ease;
}

.tool-timeline--checklist
  .tool-row:not(.tool-row--running):not(.tool-row--error):not(.is-open):hover {
  opacity: 1;
}

.tool-timeline--checklist .tool-row--error {
  box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--danger) 36%, transparent);
  border-radius: 6px;
}

@keyframes checklistCheckIn {
  0% { transform: scale(0.4); opacity: 0; }
  60% { transform: scale(1.12); opacity: 1; }
  100% { transform: scale(1); opacity: 1; }
}

/* ── Tool-row enter transition ─────────────────────────────────────────
   New rows slide up from a few pixels below and fade in. Leave is
   instant so completed rows don't visually linger. The TransitionGroup
   container is display:contents so the rows stay direct layout children of
   .tool-timeline exactly as before — the group element adds no box. */
.tool-row-group {
  display: contents;
}

.tool-row-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.tool-row-enter-active {
  transition:
    opacity var(--dur-base) var(--ease-out),
    transform var(--dur-base) var(--ease-out);
}

@media (prefers-reduced-motion: reduce) {
  .tool-row__bullet--running {
    animation: none;
  }

  .tool-timeline--checklist .tool-row--running,
  .tool-timeline--checklist .tool-row__bullet--ok,
  .tool-timeline--checklist .tool-row__state-icon--ok {
    animation: none;
  }

  .tool-timeline--checklist
    .tool-row:not(.tool-row--running):not(.tool-row--error):not(.is-open) {
    transition: none;
  }

  .run-trace__dot--running {
    animation: none;
  }

  .run-trace__skeleton {
    animation: none;
    background: var(--bg-hover);
  }

  .tool-row-enter-active {
    transition: none;
  }
}
</style>

<!-- The expanded-row section content (labels, pre, "view full" button) is built
     by the ToolRowSections child via render functions h(), so those elements
     never receive a scoped data-v attribute and scoped rules cannot reach them
     (the button would fall back to native chrome — a white box on the dark
     surface). Their styling lives here, non-scoped. Tokens only — the
     chat-color guard covers this path. -->
<style>
.tool-row-section {
  margin-top: 0.5rem;
  padding: 0.5rem 0.625rem;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.tool-row-section--error {
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-surface));
  border-color: color-mix(in srgb, var(--danger) 30%, var(--border));
}

.tool-row-section__label {
  font-size: 0.6875rem;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-dim);
  margin-bottom: 0.25rem;
}

.tool-row-section--error .tool-row-section__label {
  color: var(--danger);
}

.tool-row-section__pre {
  font-family: var(--font-mono);
  font-size: 0.6875rem;
  color: var(--text);
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 100px;
  overflow-y: auto;
  margin: 0;
}

.step-view-btn {
  margin-top: 0.25rem;
  padding: 0.125rem 0.375rem;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--accent);
  font: inherit;
  font-size: 0.6875rem;
  cursor: pointer;
}

.step-view-btn:hover {
  text-decoration: underline;
}

.step-view-btn:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px color-mix(in srgb, var(--accent) 45%, transparent);
}
</style>

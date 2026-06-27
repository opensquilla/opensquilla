<template>
  <div v-if="open && item" class="inspect-overlay" @click.self="emit('close')">
    <aside
      ref="drawerRef"
      class="inspect-drawer"
      role="dialog"
      aria-modal="true"
      :aria-label="'Session details: ' + item.title"
    >
      <header class="inspect-head">
        <span class="inspect-head__icon" aria-hidden="true">
          <Icon :name="sessionSurfaceIcon(item)" :size="16" />
        </span>
        <div class="inspect-head__titles">
          <h3 class="inspect-head__title">{{ item.title }}</h3>
          <p v-if="parentItem" class="inspect-head__lineage">Subagent of {{ parentItem.title }}</p>
        </div>
        <button
          type="button"
          class="btn btn--icon btn--ghost"
          :aria-label="keyCopied ? 'Session key copied' : 'Copy session key'"
          :title="keyCopied ? 'Copied' : 'Copy session key'"
          @click="copyKey"
        >
          <Icon :name="keyCopied ? 'check' : 'copy'" :size="16" />
        </button>
        <button
          ref="closeBtn"
          type="button"
          class="btn btn--icon btn--ghost"
          aria-label="Close"
          title="Close"
          @click="emit('close')"
        >
          <Icon name="x" :size="16" />
        </button>
      </header>

      <div class="inspect-meta">
        <span class="inspect-meta__agent">{{ agentName }}</span>
        <span v-if="badge" class="inspect-meta__status" :class="badge.cls">{{ badge.label }}</span>
        <span class="inspect-meta__stats">
          {{ item.messageCount != null ? item.messageCount.toLocaleString() : '—' }} msg
          · updated {{ sessionRelTime(item.updatedAt) }}<template v-if="costText"> · {{ costText }}</template>
        </span>
      </div>

      <p v-if="snippetText" class="inspect-snippet">{{ snippetText }}</p>

      <div ref="bodyRef" class="inspect-body" aria-label="Transcript preview">
        <RunTrace v-if="!transcriptError" class="inspect-summary" :summary="summary" />
        <ErrorState
          v-if="transcriptError"
          message="Could not load the transcript."
          :on-retry="reload"
        />
        <div v-else-if="loading" class="inspect-state">
          <LoadingSpinner />
          <p class="inspect-state__text">Loading transcript…</p>
        </div>
        <template v-else>
          <div v-if="hasEarlier" class="inspect-earlier">
            <button type="button" class="btn btn--ghost" :disabled="loadingEarlier" @click="onLoadEarlier">
              {{ loadingEarlier ? 'Loading…' : 'Load earlier' }}
            </button>
          </div>
          <p v-if="transcriptRows.length === 0" class="inspect-empty">No messages yet.</p>
          <article
            v-for="row in transcriptRows"
            :key="row.id"
            class="inspect-msg"
            :class="'inspect-msg--' + row.tone"
          >
            <div class="inspect-msg__role">{{ row.roleLabel }}</div>
            <!-- eslint-disable-next-line vue/no-v-html — renderMarkdown output is DOMPurify-sanitized -->
            <div v-if="row.html" class="inspect-msg__text" v-html="row.html" />
            <RunTrace
              v-if="row.steps.length"
              :steps="row.steps"
              :is-tool-group-open="rt.isToolGroupOpen"
              :is-tool-item-open="rt.isToolItemOpen"
              @toggle-group="rt.toggleGroup"
              @toggle-item="rt.toggleItem"
              @show-result="(content, title) => onShowResult(row.id, content, title)"
            />
            <div v-if="resultView && resultView.rowId === row.id" class="inspect-msg__result">
              <div class="inspect-msg__result-head">
                <span class="inspect-msg__result-title">{{ resultView.title }}</span>
                <button
                  type="button"
                  class="btn btn--icon btn--ghost"
                  aria-label="Close result"
                  title="Close result"
                  @click="resultView = null"
                >
                  <Icon name="x" :size="14" />
                </button>
              </div>
              <pre class="inspect-msg__result-pre">{{ resultView.content }}</pre>
            </div>
          </article>
        </template>
      </div>

      <footer class="inspect-actions">
        <button type="button" class="btn btn--primary" @click="emit('open-chat', item)">
          Open in chat
        </button>
        <button
          v-if="canAbort"
          type="button"
          class="btn btn--ghost inspect-abort"
          :disabled="aborting"
          @click="onAbort"
        >
          {{ aborting ? 'Aborting…' : 'Abort run' }}
        </button>
      </footer>
    </aside>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onUnmounted, ref, watch } from 'vue'
import Icon from '@/components/Icon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import RunTrace from '@/components/run/RunTrace.vue'
import { useSessionInspect } from '@/composables/sessions/useSessionInspect'
import { useChatTextRendering } from '@/composables/chat/useChatTextRendering'
import { useRunTrace } from '@/composables/run/useRunTrace'
import { useToasts } from '@/composables/useToasts'
import { useConfirm } from '@/composables/useConfirm'
import { copyTextWithFallback } from '@/utils/browser'
import { nodeStepsFromHistoryMessage } from '@/components/run/runTrace'
import type { NodeStep, RunTraceStatus, RunTraceSummary } from '@/types/runTrace'
import type { SessionItem } from '@/composables/useSessions'
import { sessionRelTime, sessionStatusBadge, sessionSurfaceIcon } from './sessionDisplay'

interface TranscriptRow {
  id: string
  tone: string
  roleLabel: string
  html: string
  steps: NodeStep[]
}

const props = defineProps<{
  open: boolean
  item: SessionItem | null
  agentName: string
  parentItem?: SessionItem | null
  needsInput?: boolean
}>()

const emit = defineEmits<{
  close: []
  'open-chat': [item: SessionItem]
  aborted: [item: SessionItem]
}>()

const {
  preview,
  messages,
  hasEarlier,
  loading,
  loadingEarlier,
  transcriptError,
  load,
  loadEarlier,
  abortSession,
  reset,
} = useSessionInspect()

const { renderMarkdown, stripDirectiveTags, stripTimePrefix } = useChatTextRendering()
const { pushToast } = useToasts()
const { confirm } = useConfirm()
const rt = useRunTrace()

const drawerRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)
const keyCopied = ref(false)
const aborting = ref(false)
const resultView = ref<{ rowId: string; title: string; content: string } | null>(null)

let keyCopiedTimer: ReturnType<typeof setTimeout> | null = null
let invokerEl: HTMLElement | null = null

const badge = computed(() => (props.item ? sessionStatusBadge(props.item, props.needsInput === true) : null))
const canAbort = computed(() =>
  !!props.item && (props.item.runStatus === 'running' || props.item.runStatus === 'queued'))

const snippetText = computed(() => {
  const text = stripDirectiveTags(stripTimePrefix(preview.value?.lastMessage || '')).trim()
  // Structured payloads (raw JSON tool output) are noise, not a summary.
  if (/^[[{]/.test(text)) return ''
  return text
})

const costText = computed(() => {
  const raw = props.item?.raw as Record<string, unknown> | undefined
  if (!raw) return ''
  const value = Number(raw['costUsd'] ?? raw['cost_usd'] ?? raw['totalCostUsd'] ?? raw['total_cost_usd'] ?? NaN)
  if (!Number.isFinite(value)) return ''
  return `$${value >= 1 ? value.toFixed(2) : value.toFixed(4)}`
})

function roleTone(role: string): string {
  if (role === 'user') return 'user'
  if (role === 'assistant') return 'agent'
  return 'system'
}

function roleLabel(role: string): string {
  if (role === 'user') return 'You'
  if (role === 'assistant') return 'Agent'
  return role.charAt(0).toUpperCase() + role.slice(1)
}

const transcriptRows = computed((): TranscriptRow[] => {
  const rows: TranscriptRow[] = []
  messages.value.forEach((msg, index) => {
    const role = String(msg.role || 'assistant')
    const text = role === 'user' ? stripTimePrefix(msg.text || '') : msg.text || ''
    const html = text.trim() ? renderMarkdown(text) : ''
    const steps = nodeStepsFromHistoryMessage(msg)
    if (!html && steps.length === 0) return
    rows.push({
      id: String(msg.message_id || msg.id || `${index}:${msg.timestamp ?? msg.ts ?? ''}`),
      tone: roleTone(role),
      roleLabel: roleLabel(role),
      html,
      steps,
    })
  })
  return rows
})

// The drawer has no global result modal; "view full" expands a local read-only
// panel beneath the originating row instead.
function onShowResult(rowId: string, content: string, title: string) {
  resultView.value = { rowId, content, title }
}

// Whole-run rollup for the summary header. Token/elapsed totals are not carried
// on the raw history pages, so those cells render the em-dash placeholder.
function summaryStatus(item: SessionItem | null, needsInput: boolean): RunTraceStatus | undefined {
  if (needsInput) return 'queued'
  switch (item?.runStatus) {
    case 'running': return 'running'
    case 'queued': return 'queued'
    case 'failed':
    case 'timeout': return 'error'
    case 'cancelled':
    case 'interrupted': return 'cancelled'
    case 'idle': return 'success'
    default: return undefined
  }
}

const summary = computed<RunTraceSummary>(() => ({
  status: summaryStatus(props.item, props.needsInput === true),
  executor: props.agentName,
  elapsedMs: null,
  tokens: null,
  steps: transcriptRows.value.reduce((count, row) => count + row.steps.length, 0),
  loading: loading.value,
}))

function scrollToBottom() {
  nextTick(() => {
    if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
  })
}

function reload() {
  if (!props.item) return
  void load(props.item.key).then(scrollToBottom)
}

async function onLoadEarlier() {
  const el = bodyRef.value
  const previousHeight = el?.scrollHeight || 0
  await loadEarlier()
  nextTick(() => {
    if (el) el.scrollTop += Math.max(0, el.scrollHeight - previousHeight)
  })
}

async function copyKey() {
  if (!props.item) return
  try {
    await copyTextWithFallback(props.item.key)
    keyCopied.value = true
    if (keyCopiedTimer) clearTimeout(keyCopiedTimer)
    keyCopiedTimer = setTimeout(() => { keyCopied.value = false }, 1500)
  } catch {
    pushToast('Could not copy the session key.', { tone: 'danger' })
  }
}

async function onAbort() {
  const item = props.item
  if (!item || aborting.value) return
  const ok = await confirm({
    title: 'Abort run',
    body: `Abort the active run in "${item.title}"?`,
    primaryLabel: 'Abort',
  })
  if (!ok) return
  aborting.value = true
  try {
    const aborted = await abortSession(item.key)
    pushToast(aborted ? 'Run aborted.' : 'No active run to abort.')
    emit('aborted', item)
  } catch {
    pushToast('Abort failed.', { tone: 'danger' })
  } finally {
    aborting.value = false
  }
}

function onDocumentKeydown(event: KeyboardEvent) {
  if (!props.open) return
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'Tab') return
  const rootEl = drawerRef.value
  if (!rootEl) return
  const focusables = Array.from(rootEl.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], [tabindex]:not([tabindex="-1"])'))
  if (focusables.length === 0) return
  const first = focusables[0]
  const last = focusables[focusables.length - 1]
  const active = document.activeElement as HTMLElement | null
  const inside = !!active && rootEl.contains(active)
  if (event.shiftKey && (!inside || active === first)) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && (!inside || active === last)) {
    event.preventDefault()
    first.focus()
  }
}

watch(
  () => [props.open, props.item?.key] as const,
  ([open, key], previous) => {
    const wasOpen = previous?.[0] === true
    if (open && key) {
      if (!wasOpen) {
        invokerEl = document.activeElement instanceof HTMLElement ? document.activeElement : null
        document.addEventListener('keydown', onDocumentKeydown)
      }
      keyCopied.value = false
      void load(key).then(scrollToBottom)
      nextTick(() => closeBtn.value?.focus())
    } else if (wasOpen && !open) {
      document.removeEventListener('keydown', onDocumentKeydown)
      resultView.value = null
      reset()
      if (invokerEl && document.contains(invokerEl)) invokerEl.focus()
      invokerEl = null
    }
  },
)

onUnmounted(() => {
  document.removeEventListener('keydown', onDocumentKeydown)
  if (keyCopiedTimer) clearTimeout(keyCopiedTimer)
})
</script>

<style scoped>
.inspect-overlay {
  background: var(--scrim);
  display: flex;
  inset: 0;
  justify-content: flex-end;
  position: fixed;
  z-index: 300;
}

.inspect-drawer {
  animation: inspectIn 0.18s ease;
  background: var(--bg-surface);
  border-left: 1px solid var(--border);
  box-shadow: var(--shadow-lg);
  display: flex;
  flex-direction: column;
  height: 100%;
  width: min(560px, 100%);
}

@keyframes inspectIn {
  from { transform: translateX(24px); opacity: 0.4; }
  to { transform: translateX(0); opacity: 1; }
}

@media (prefers-reduced-motion: reduce) {
  .inspect-drawer {
    animation: none;
  }
}

.inspect-head {
  align-items: center;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
}

.inspect-head__icon {
  align-items: center;
  color: var(--text-dim);
  display: inline-flex;
  flex-shrink: 0;
}

.inspect-head__titles {
  flex: 1;
  min-width: 0;
}

.inspect-head__title {
  color: var(--text);
  font-size: var(--fs-md);
  font-weight: 600;
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspect-head__lineage {
  color: var(--text-muted);
  font-size: var(--fs-xs);
  margin: 2px 0 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspect-meta {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4) 0;
}

.inspect-meta__agent {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: var(--fs-xs);
  font-weight: 650;
  max-width: 160px;
  overflow: hidden;
  padding: 2px var(--sp-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspect-meta__status {
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: var(--fs-xs);
  font-weight: 650;
  padding: 2px var(--sp-2);
  white-space: nowrap;
}

.inspect-meta__status.is-running {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.inspect-meta__status.is-needs-input {
  background: color-mix(in srgb, var(--warn) 14%, transparent);
  border-color: color-mix(in srgb, var(--warn) 50%, var(--border));
  color: var(--warn);
}

.inspect-meta__status.is-queued {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 35%, var(--border));
  color: var(--warn);
}

.inspect-meta__status.is-failed {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

.inspect-meta__status.is-off {
  color: var(--text-dim);
}

.inspect-meta__stats {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}

.inspect-snippet {
  border-bottom: 1px solid var(--hairline);
  color: var(--text-muted);
  display: -webkit-box;
  font-size: var(--fs-xs);
  line-height: 1.5;
  margin: 0;
  overflow: hidden;
  padding: var(--sp-2) var(--sp-4) var(--sp-3);
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}

.inspect-body {
  background: var(--bg);
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--sp-3);
  overflow-y: auto;
  padding: var(--sp-4);
}

.inspect-state {
  align-items: center;
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-8) var(--sp-4);
}

.inspect-state__text {
  font-size: var(--fs-sm);
  margin: 0;
}

.inspect-earlier {
  display: flex;
  justify-content: center;
}

.inspect-empty {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: 0;
  padding: var(--sp-6) 0;
  text-align: center;
}

.inspect-msg {
  border-left: 2px solid var(--hairline);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding-left: var(--sp-3);
}

.inspect-msg--user {
  border-left-color: color-mix(in srgb, var(--accent) 55%, var(--border));
}

.inspect-msg--agent {
  border-left-color: var(--border-strong);
}

.inspect-msg__role {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  font-weight: 650;
  letter-spacing: var(--track-tabular);
  text-transform: uppercase;
}

.inspect-msg--user .inspect-msg__role {
  color: var(--accent);
}

.inspect-msg__text {
  color: var(--text);
  font-size: var(--fs-sm);
  line-height: 1.6;
  min-width: 0;
  overflow-wrap: break-word;
}

.inspect-msg__text :deep(p) {
  margin: 0 0 var(--sp-2);
}

.inspect-msg__text :deep(p:last-child) {
  margin-bottom: 0;
}

.inspect-msg__text :deep(ul),
.inspect-msg__text :deep(ol) {
  margin: 0 0 var(--sp-2);
  padding-left: var(--sp-5);
}

.inspect-msg__text :deep(pre) {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  margin: 0 0 var(--sp-2);
  overflow-x: auto;
  padding: var(--sp-2) var(--sp-3);
}

.inspect-msg__text :deep(code) {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.inspect-msg__text :deep(.code-lang) {
  color: var(--text-dim);
  display: block;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
}

.inspect-msg__text :deep(blockquote) {
  border-left: 2px solid var(--border-strong);
  color: var(--text-muted);
  margin: 0 0 var(--sp-2);
  padding-left: var(--sp-3);
}

.inspect-msg__text :deep(a) {
  color: var(--accent);
}

.inspect-msg__result {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  padding: var(--sp-2);
}

.inspect-msg__result-head {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.inspect-msg__result-title {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  font-weight: 650;
  letter-spacing: var(--track-tabular);
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  text-transform: uppercase;
  white-space: nowrap;
}

.inspect-msg__result-pre {
  color: var(--text);
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  margin: 0;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.inspect-actions {
  align-items: center;
  border-top: 1px solid var(--border);
  display: flex;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-4);
}

.inspect-abort {
  border-color: color-mix(in srgb, var(--danger) 35%, var(--border));
  color: var(--danger);
}

.inspect-abort:hover:not(:disabled) {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 50%, var(--border));
  color: var(--danger);
}
</style>

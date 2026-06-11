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
            <div v-if="row.tools.length" class="inspect-msg__tools">
              <span
                v-for="(tool, index) in row.tools"
                :key="row.id + ':' + index"
                class="inspect-tool-pill"
                :class="{ 'inspect-tool-pill--error': tool.isError }"
              >
                <Icon name="gear" :size="11" />
                <span>{{ tool.name }}</span>
              </span>
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
import { useSessionInspect } from '@/composables/sessions/useSessionInspect'
import { useChatTextRendering } from '@/composables/chat/useChatTextRendering'
import { useToasts } from '@/composables/useToasts'
import { copyTextWithFallback } from '@/utils/browser'
import type { SessionItem } from '@/composables/useSessions'
import type { ChatHistoryMessage } from '@/types/rpc'
import { sessionRelTime, sessionStatusBadge, sessionSurfaceIcon } from './sessionDisplay'

interface TranscriptToolPill {
  name: string
  isError: boolean
}

interface TranscriptRow {
  id: string
  tone: string
  roleLabel: string
  html: string
  tools: TranscriptToolPill[]
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

const drawerRef = ref<HTMLElement | null>(null)
const bodyRef = ref<HTMLElement | null>(null)
const closeBtn = ref<HTMLButtonElement | null>(null)
const keyCopied = ref(false)
const aborting = ref(false)

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

// History rows carry paired tool_use/tool_result entries (plus text/thinking
// segments) in tool_calls; merge each call into a single pill by its id.
function toolPills(msg: ChatHistoryMessage): TranscriptToolPill[] {
  if (!Array.isArray(msg.tool_calls)) return []
  const pills = new Map<string, TranscriptToolPill>()
  let anonymous = 0
  for (const entry of msg.tool_calls) {
    if (!entry || typeof entry !== 'object' || Array.isArray(entry)) continue
    const record = entry as Record<string, unknown>
    const type = String(record.type || '')
    if (type && type !== 'tool_use' && type !== 'tool_result') continue
    const id = String(record.tool_use_id || record.toolId || record.id || '') || `anon-${anonymous++}`
    const existing = pills.get(id)
    const name = String(record.name || record.tool_name || existing?.name || 'tool')
    const isError = record.is_error === true || record.isError === true || existing?.isError === true
    pills.set(id, { name, isError })
  }
  return Array.from(pills.values())
}

const transcriptRows = computed((): TranscriptRow[] => {
  const rows: TranscriptRow[] = []
  messages.value.forEach((msg, index) => {
    const role = String(msg.role || 'assistant')
    const text = role === 'user' ? stripTimePrefix(msg.text || '') : msg.text || ''
    const html = text.trim() ? renderMarkdown(text) : ''
    const tools = toolPills(msg)
    if (!html && tools.length === 0) return
    rows.push({
      id: String(msg.message_id || msg.id || `${index}:${msg.timestamp ?? msg.ts ?? ''}`),
      tone: roleTone(role),
      roleLabel: roleLabel(role),
      html,
      tools,
    })
  })
  return rows
})

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
  if (!confirm(`Abort the active run in "${item.title}"?`)) return
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

.inspect-msg__tools {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-1);
}

.inspect-tool-pill {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  display: inline-flex;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  gap: var(--sp-1);
  max-width: 100%;
  overflow: hidden;
  padding: 1px var(--sp-2);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.inspect-tool-pill--error {
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
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

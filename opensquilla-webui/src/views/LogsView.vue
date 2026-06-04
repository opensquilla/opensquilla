<template>
  <div class="lg-stage">
    <header class="lg-stage__header">
      <div class="lg-stage__title-block">
        <span class="lg-stage__eyebrow">Control &middot; Logs</span>
        <h2 class="lg-stage__title">Logs</h2>
        <p class="lg-stage__subtitle">Live gateway log stream — filter, follow, and export.</p>
      </div>
      <div class="lg-stage__actions">
        <div class="lg-status-pills">
          <span
            v-if="!status"
            class="lg-pill lg-pill--warn"
            title="logs.status is unavailable; log tailing can still work."
          >Log status unavailable</span>
          <template v-else>
            <span
              :class="['lg-pill', fileLogEnabled ? '' : 'lg-pill--warn']"
              :title="`Gateway file logging is configurable via log_file_enabled, log_level, rotation settings, and OPENSQUILLA_LOG_DIR. Path: ${filePath}.`"
            >File log {{ fileLogEnabled ? 'on' : 'off' }}</span>
            <span
              :class="['lg-pill', rawLogEnabled ? '' : 'lg-pill--warn']"
              :title="`Raw turn-call capture is enabled by OPENSQUILLA_TURN_CALL_LOG=1 or opensquilla diagnostics on --raw. Source: ${rawSource}. Directory: ${rawPath}.`"
            >Raw turn-call {{ rawLogEnabled ? 'on' : 'off' }}</span>
            <span
              class="lg-pill lg-pill--warn"
              :title="diagnosticsCopy"
            >{{ diagnosticsLabel }}</span>
          </template>
        </div>
        <button class="btn btn--ghost" title="Download filtered log lines" @click="exportLogs">
          <Icon name="download" :size="16" />
          <span>Export</span>
        </button>
      </div>
    </header>

    <section class="stat-row">
      <div class="stat stat--hero">
        <div class="stat-label">In view</div>
        <div class="stat-value">{{ visibleCount.toLocaleString() }}</div>
        <div class="stat-hint">of {{ totalCount.toLocaleString() }} loaded</div>
      </div>
      <div class="stat">
        <div class="stat-label">Errors</div>
        <div class="stat-value">{{ errorCount }}</div>
        <div class="stat-hint">{{ errorCount > 0 ? 'review needed' : 'all clear' }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Warnings</div>
        <div class="stat-value">{{ warnCount }}</div>
        <div class="stat-hint">{{ warnCount > 0 ? 'recent advisories' : 'none' }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Info / Debug</div>
        <div class="stat-value mono">{{ infoCount }}<span>/</span>{{ debugCount }}</div>
        <div class="stat-hint">routine output</div>
      </div>
    </section>

    <section class="lg-toolbar">
      <div class="lg-levels">
        <span class="lg-toolbar__label">Levels</span>
        <div class="lg-levels__row">
          <button
            v-for="level in LEVELS"
            :key="level"
            :class="['lg-level-btn', `lg-level-btn--${level.toLowerCase()}`, activeLevels.has(level) ? 'is-active' : '']"
            @click="toggleLevel(level)"
          >
            <span class="lg-level-btn__dot"></span>
            <span class="lg-level-btn__label">{{ level }}</span>
          </button>
        </div>
      </div>
      <div class="lg-search-wrap">
        <span class="lg-search-icon"><Icon name="search" :size="16" /></span>
        <input
          v-model="searchText"
          class="lg-search-input"
          type="search"
          placeholder="Filter messages…"
          autocomplete="off"
        />
      </div>
      <label class="lg-toggle">
        <input v-model="autoFollow" type="checkbox" />
        <span class="lg-toggle__track"><span class="lg-toggle__thumb"></span></span>
        <span class="lg-toggle__label">Auto-follow</span>
      </label>
    </section>

    <section class="lg-stream">
      <div ref="displayRef" class="lg-display">
        <div v-if="allLines.length === 0" class="lg-display__placeholder">
          <span class="lg-spinner"></span>
          Loading logs…
        </div>
        <div v-else-if="filteredLines.length === 0" class="lg-display__placeholder">
          <span class="lg-display__placeholder-icon"><Icon name="logs" :size="24" /></span>
          No lines match the current filter.
        </div>
        <div
          v-for="(line, idx) in filteredLines"
          :key="idx"
          :class="['lg-line', `lg-line--${(line.level || 'info').toLowerCase()}`]"
        >
          <span v-if="line.ts" class="lg-line__ts">{{ String(line.ts).slice(0, 23) }}</span>
          <span v-else class="lg-line__ts lg-line__ts--empty"></span>
          <span :class="['lg-line__lvl', `lg-line__lvl--${(line.level || 'info').toLowerCase()}`]">{{ line.level }}</span>
          <span class="lg-line__msg">
            <template
              v-for="(part, partIndex) in highlightParts(line.message)"
              :key="`${idx}-${partIndex}`"
            >
              <mark v-if="part.match" class="lg-line__match">{{ part.text }}</mark>
              <template v-else>{{ part.text }}</template>
            </template>
          </span>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import { downloadText } from '@/utils/browser'
import Icon from '@/components/Icon.vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface LogLine {
  level: string
  message: string
  ts?: string | number | null
  raw?: string
}

interface LogTailResponse {
  lines?: LogEntry[]
  entries?: LogEntry[]
  cursor?: number
}

interface LogEntry {
  level?: string
  lvl?: string
  message?: string
  msg?: string
  timestamp?: string | number
  ts?: string | number
  raw?: string
  [key: string]: unknown
}

interface LogStatus {
  gateway_file_log?: {
    enabled?: boolean
    path?: string
  }
  raw_turn_call_log?: {
    enabled?: boolean
    source?: string
    directory?: {
      path?: string
    }
  }
  diagnostics_enabled?: {
    effective?: boolean
    detail?: string
  }
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LEVELS = ['TRACE', 'DEBUG', 'INFO', 'WARN', 'ERROR'] as const
const DEFAULT_LEVELS = new Set<string>(['DEBUG', 'INFO', 'WARN', 'ERROR'])

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const rpc = useRpcStore()
const allLines = ref<LogLine[]>([])
const cursor = ref(0)
const searchText = ref('')
const autoFollow = ref(true)
const status = ref<LogStatus | null>(null)
const activeLevels = ref<Set<string>>(new Set(DEFAULT_LEVELS))
const displayRef = ref<HTMLElement | null>(null)

let pollInterval: ReturnType<typeof setInterval> | null = null
let pollInFlight = false
let pollErrorShown = false

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const totalCount = computed(() => allLines.value.length)
const errorCount = computed(() => allLines.value.filter(l => l.level === 'ERROR').length)
const warnCount = computed(() => allLines.value.filter(l => l.level === 'WARN').length)
const infoCount = computed(() => allLines.value.filter(l => l.level === 'INFO').length)
const debugCount = computed(() => allLines.value.filter(l => l.level === 'DEBUG' || l.level === 'TRACE').length)

const filteredLines = computed(() => {
  const term = searchText.value.toLowerCase()
  return allLines.value.filter(line => {
    if (!activeLevels.value.has(line.level)) return false
    if (term && !line.message.toLowerCase().includes(term)) return false
    return true
  })
})

const visibleCount = computed(() => filteredLines.value.length)

const fileLogEnabled = computed(() => status.value?.gateway_file_log?.enabled ?? false)
const filePath = computed(() => status.value?.gateway_file_log?.path || 'debug.log')

const rawLogEnabled = computed(() => status.value?.raw_turn_call_log?.enabled ?? false)
const rawSource = computed(() => status.value?.raw_turn_call_log?.source || 'off')
const rawPath = computed(() => status.value?.raw_turn_call_log?.directory?.path || '~/.opensquilla/logs')

const diagnosticsCopy = computed(() => {
  const detail = status.value?.diagnostics_enabled?.detail
  if (detail === 'raw') {
    return `Diagnostics raw mode is active for future turns. Raw source: ${rawSource.value}.`
  }
  return 'Standard diagnostics and raw capture are separate levels. Use opensquilla diagnostics on --raw for raw turn-call capture.'
})

const diagnosticsLabel = computed(() => {
  const detail = status.value?.diagnostics_enabled?.detail
  if (detail === 'raw') return 'Diagnostics raw'
  if (status.value?.diagnostics_enabled?.effective) return 'Diagnostics standard'
  return 'Diagnostics off'
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
  pollInterval = setInterval(poll, 3000)
})

onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
})

// Auto-scroll when filtered lines change and autoFollow is on
watch(filteredLines, () => {
  if (autoFollow.value) {
    nextTick(() => scrollToBottom())
  }
})

watch(autoFollow, (val) => {
  if (val) scrollToBottom()
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
    cursor.value = 0
    allLines.value = []
    await loadStatus()
    await poll()
  } catch {
    // Silently ignore initial load errors; poll will retry
  }
}

async function loadStatus() {
  try {
    status.value = await rpc.call<LogStatus>('logs.status', {})
  } catch {
    status.value = null
  }
}

async function poll() {
  if (pollInFlight) return
  const rpcClient = rpc.client
  if (!rpcClient) return
  pollInFlight = true
  try {
    const data = await rpc.call<LogTailResponse>('logs.tail', { limit: 500, cursor: cursor.value, level: null })
    const lines: LogEntry[] = data.lines || data.entries || []
    if (lines.length > 0) {
      if (data.cursor != null) {
        cursor.value = data.cursor
      } else {
        cursor.value += lines.length
      }
      lines.forEach(entry => {
        if (typeof entry === 'string') {
          allLines.value.push({ level: guessLevel(entry), message: entry, raw: entry })
        } else {
          allLines.value.push({
            level: (entry.level || entry.lvl || 'INFO').toUpperCase(),
            message: entry.message || entry.msg || JSON.stringify(entry),
            ts: entry.timestamp || entry.ts || null,
            raw: typeof entry.raw === 'string' ? entry.raw : JSON.stringify(entry),
          })
        }
      })
      if (allLines.value.length > 2000) {
        allLines.value = allLines.value.slice(allLines.value.length - 2000)
      }
    }
    pollErrorShown = false
  } catch (err) {
    if (!pollErrorShown) {
      console.warn('Log refresh failed: ' + (err instanceof Error ? err.message : 'unknown error'))
      pollErrorShown = true
    }
  } finally {
    pollInFlight = false
  }
}

function toggleLevel(level: string) {
  const next = new Set(activeLevels.value)
  if (next.has(level)) {
    next.delete(level)
  } else {
    next.add(level)
  }
  activeLevels.value = next
}

function exportLogs() {
  const text = filteredLines.value.map(line => {
    const ts = line.ts ? String(line.ts).slice(0, 23) + ' ' : ''
    return `${ts}[${line.level}] ${line.message}`
  }).join('\n')
  downloadText('opensquilla-logs.txt', 'text/plain', text)
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function guessLevel(line: string): string {
  const u = line.toUpperCase()
  if (u.includes('ERROR')) return 'ERROR'
  if (u.includes('WARN')) return 'WARN'
  if (u.includes('INFO')) return 'INFO'
  if (u.includes('DEBUG')) return 'DEBUG'
  if (u.includes('TRACE')) return 'TRACE'
  return 'INFO'
}

function highlightParts(message: string): Array<{ text: string; match: boolean }> {
  const term = searchText.value
  if (!term) return [{ text: message, match: false }]
  const re = new RegExp(`(${escRegex(term)})`, 'gi')
  const parts: Array<{ text: string; match: boolean }> = []
  let lastIndex = 0
  for (const match of message.matchAll(re)) {
    const index = match.index ?? 0
    if (index > lastIndex) parts.push({ text: message.slice(lastIndex, index), match: false })
    parts.push({ text: match[0], match: true })
    lastIndex = index + match[0].length
  }
  if (lastIndex < message.length) parts.push({ text: message.slice(lastIndex), match: false })
  return parts.length ? parts : [{ text: message, match: false }]
}

function scrollToBottom() {
  const el = displayRef.value
  if (el) el.scrollTop = el.scrollHeight
}

function escRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
</script>

<style scoped>
.lg-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  max-width: none;
  position: relative;
}

.lg-stage__header {
  align-items: flex-end;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  justify-content: space-between;
  padding-top: var(--sp-3);
}

.lg-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.lg-stage__title {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  margin: 0;
  position: relative;
}

.lg-stage__title::after {
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
  bottom: -8px;
  content: "";
  height: 2px;
  left: 0;
  position: absolute;
  width: 36px;
}

.lg-stage__subtitle {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: var(--sp-3) 0 0;
}

.lg-stage__eyebrow {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.lg-stage__actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}

.lg-status-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.lg-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  white-space: nowrap;
}

.lg-pill--warn {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}

.stat-row {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.stat {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  overflow: hidden;
  padding: var(--sp-4);
  position: relative;
}

.stat--hero {
  min-height: 116px;
}

.stat-label {
  color: var(--text-dim);
  display: block;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.08em;
  line-height: 1.25;
  text-transform: uppercase;
}

.stat-value {
  align-items: center;
  display: flex;
  font-size: 2rem;
  font-variant-numeric: tabular-nums;
  gap: 8px;
  letter-spacing: 0;
  line-height: 1.12;
  margin-top: var(--sp-4);
}

.stat-value.mono {
  font-family: var(--font-mono);
}

.stat-value span {
  color: var(--text-dim);
  font-size: 1.4rem;
}

.stat-hint {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin-top: var(--sp-2);
}

.lg-toolbar {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  padding: var(--sp-3) var(--sp-4);
}

.lg-toolbar__label {
  color: var(--text-dim);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.lg-levels {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
}

.lg-levels__row {
  display: flex;
  gap: 6px;
}

.lg-level-btn {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  gap: 5px;
  letter-spacing: 0.04em;
  padding: 4px 10px;
  text-transform: uppercase;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
}

.lg-level-btn:hover {
  border-color: var(--accent);
  color: var(--text);
}

.lg-level-btn.is-active {
  background: var(--bg-panel);
  color: var(--text);
}

.lg-level-btn__dot {
  border-radius: 999px;
  display: inline-block;
  height: 6px;
  width: 6px;
}

.lg-level-btn--trace .lg-level-btn__dot { background: var(--text-dim); }
.lg-level-btn--debug .lg-level-btn__dot { background: var(--accent); }
.lg-level-btn--info  .lg-level-btn__dot { background: var(--ok); }
.lg-level-btn--warn  .lg-level-btn__dot { background: var(--warn); }
.lg-level-btn--error .lg-level-btn__dot { background: var(--danger); }

.lg-search-wrap {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex: 1;
  gap: 8px;
  min-width: 200px;
  padding: 0 var(--sp-3);
}

.lg-search-icon {
  color: var(--text-dim);
  display: inline-flex;
  flex-shrink: 0;
}

.lg-search-input {
  background: transparent;
  border: none;
  color: var(--text);
  font-size: var(--fs-sm);
  outline: none;
  padding: 8px 0;
  width: 100%;
}

.lg-search-input::placeholder {
  color: var(--text-dim);
}

.lg-toggle {
  align-items: center;
  cursor: pointer;
  display: inline-flex;
  gap: 8px;
  user-select: none;
}

.lg-toggle input {
  clip: rect(0 0 0 0);
  height: 1px;
  margin: -1px;
  overflow: hidden;
  position: absolute;
  width: 1px;
}

.lg-toggle__track {
  background: var(--border);
  border-radius: 999px;
  display: inline-block;
  height: 18px;
  position: relative;
  transition: background 0.2s ease;
  width: 32px;
}

.lg-toggle input:checked + .lg-toggle__track {
  background: var(--accent);
}

.lg-toggle__thumb {
  background: var(--text);
  border-radius: 999px;
  display: block;
  height: 14px;
  left: 2px;
  position: absolute;
  top: 2px;
  transition: transform 0.2s ease;
  width: 14px;
}

.lg-toggle input:checked + .lg-toggle__track .lg-toggle__thumb {
  transform: translateX(14px);
}

.lg-toggle__label {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.lg-stream {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  display: flex;
  flex-direction: column;
  min-height: 320px;
  overflow: hidden;
}

.lg-display {
  flex: 1;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.6;
  max-height: 60vh;
  overflow: auto;
  padding: var(--sp-3);
}

.lg-display__placeholder {
  align-items: center;
  color: var(--text-muted);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  justify-content: center;
  min-height: 200px;
  text-align: center;
}

.lg-display__placeholder-icon {
  color: var(--text-dim);
  display: inline-flex;
}

.lg-spinner {
  animation: lg-spin 1s linear infinite;
  border: 2px solid var(--border);
  border-radius: 999px;
  border-top-color: var(--accent);
  display: inline-block;
  height: 20px;
  width: 20px;
}

@keyframes lg-spin {
  to { transform: rotate(360deg); }
}

.lg-line {
  align-items: baseline;
  border-radius: var(--radius-sm);
  display: flex;
  gap: 10px;
  padding: 2px 6px;
  white-space: pre-wrap;
  word-break: break-word;
}

.lg-line:nth-child(even) {
  background: color-mix(in srgb, var(--bg-elevated) 40%, transparent);
}

.lg-line__ts {
  color: var(--text-dim);
  flex-shrink: 0;
  font-size: 11px;
  width: 160px;
}

.lg-line__ts--empty {
  width: 160px;
}

.lg-line__lvl {
  border-radius: var(--radius-sm);
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.06em;
  padding: 1px 6px;
  text-align: center;
  text-transform: uppercase;
  width: 44px;
}

.lg-line__lvl--trace { background: color-mix(in srgb, var(--text-dim) 15%, transparent); color: var(--text-dim); }
.lg-line__lvl--debug { background: color-mix(in srgb, var(--accent) 12%, transparent); color: var(--accent); }
.lg-line__lvl--info  { background: color-mix(in srgb, var(--ok) 12%, transparent); color: var(--ok); }
.lg-line__lvl--warn  { background: color-mix(in srgb, var(--warn) 12%, transparent); color: var(--warn); }
.lg-line__lvl--error { background: color-mix(in srgb, var(--danger) 12%, transparent); color: var(--danger); }

.lg-line__msg {
  color: var(--text-muted);
  flex: 1;
  min-width: 0;
}

.lg-line__msg :deep(.lg-line__match) {
  background: color-mix(in srgb, var(--accent) 25%, transparent);
  border-radius: 2px;
  color: var(--text);
  padding: 0 2px;
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .lg-stage__header {
    align-items: stretch;
    flex-direction: column;
  }

  .lg-stage__header .btn {
    align-self: flex-start;
    width: auto;
  }

  .lg-toolbar {
    flex-direction: column;
    align-items: stretch;
  }

  .lg-search-wrap {
    min-width: 0;
  }
}

@media (max-width: 480px) {
  .stat-row {
    grid-template-columns: 1fr;
  }

  .lg-line {
    flex-direction: column;
    gap: 2px;
    padding: 6px;
  }

  .lg-line__ts,
  .lg-line__ts--empty {
    width: auto;
  }
}
</style>

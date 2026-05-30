<template>
  <div class="ov-stage">
    <!-- Header -->
    <header class="ov-stage__header">
      <div class="ov-stage__title-block">
        <span class="ov-stage__eyebrow">Control &middot; Overview</span>
        <h2 class="ov-stage__title">OpenSquilla</h2>
        <p class="ov-stage__subtitle">Live status, recent sessions, and the live event stream.</p>
      </div>
      <div class="ov-stage__actions">
        <button class="btn btn--ghost" title="Refresh" @click="refresh">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
        <button class="btn btn--primary" title="Open chat" @click="router.push('/chat')">
          <Icon name="chat" :size="16" />
          <span>Open chat</span>
        </button>
      </div>
    </header>

    <!-- Stat cards -->
    <section class="ov-stats">
      <button class="ov-stat ov-stat--accent" type="button" @click="router.push('/usage')">
        <div class="ov-stat__icon">
          <Icon name="usage" :size="18" />
        </div>
        <div class="ov-stat__label">Total tokens</div>
        <div class="ov-stat__value">{{ tokensDisplay }}</div>
        <div class="ov-stat__hint">{{ costLine }}</div>
      </button>

      <button class="ov-stat" type="button" title="Total sessions across all statuses" @click="router.push('/sessions')">
        <div class="ov-stat__icon">
          <Icon name="sessions" :size="18" />
        </div>
        <div class="ov-stat__label">Total sessions</div>
        <div class="ov-stat__value">{{ sessionsCount }}</div>
        <div class="ov-stat__hint">view all &rarr;</div>
      </button>

      <button class="ov-stat" type="button" @click="router.push('/agents')">
        <div class="ov-stat__icon">
          <Icon name="agents" :size="18" />
        </div>
        <div class="ov-stat__label">Provider</div>
        <div class="ov-stat__value ov-stat__value--mono">{{ provider }}</div>
        <div class="ov-stat__hint">manage agents &rarr;</div>
      </button>

      <button class="ov-stat" type="button" @click="router.push('/health')">
        <div class="ov-stat__icon">
          <Icon name="logs" :size="18" />
        </div>
        <div class="ov-stat__label">Health</div>
        <div class="ov-stat__value ov-stat__value--status">{{ healthStatus }}</div>
        <div class="ov-stat__hint">{{ healthSummary }}</div>
      </button>

      <div class="ov-stat ov-stat--static">
        <div class="ov-stat__icon">
          <Icon name="cron" :size="18" />
        </div>
        <div class="ov-stat__label">Uptime</div>
        <div class="ov-stat__value ov-stat__value--mono">{{ uptime }}</div>
        <div class="ov-stat__hint">{{ versionLine }}</div>
      </div>
    </section>

    <!-- Grid panels -->
    <div class="ov-grid">
      <!-- Recent sessions -->
      <section class="ov-panel ov-panel--span2">
        <div class="ov-panel__head">
          <div>
            <span class="ov-panel__eyebrow">Recent activity</span>
            <h3 class="ov-panel__title">Sessions</h3>
          </div>
          <button class="ov-link" type="button" @click="router.push('/sessions')">
            View all &rarr;
          </button>
        </div>
        <div class="ov-recent">
          <template v-if="loadingSessions">
            <div class="skeleton-row" />
          </template>
          <template v-else-if="recentSessions.length === 0">
            <div class="ov-recent__empty">
              <div class="ov-recent__empty-icon">
                <Icon name="sessions" :size="36" />
              </div>
              <div>No sessions yet &mdash; open chat to start your first one.</div>
            </div>
          </template>
          <template v-else>
            <button
              v-for="s in recentSessions"
              :key="s.key"
              class="ov-recent__row"
              type="button"
              @click="openSession(s.key)"
            >
              <span
                class="dot"
                :class="sessionStatusClass(s.status)"
                :aria-label="sessionStatusLabel(s.status)"
                :title="sessionStatusLabel(s.status)"
              />
              <span class="ov-recent__key">{{ s.key }}</span>
              <span v-if="s.model" class="ov-recent__model">{{ s.model }}</span>
              <span v-if="s.message_count != null" class="ov-recent__msgs">{{ formatMessageCount(s.message_count) }}</span>
              <span class="ov-recent__time">{{ relTime(s.updated_at) }}</span>
              <span class="ov-recent__arrow">&rarr;</span>
            </button>
          </template>
        </div>
      </section>

      <!-- Connection panel -->
      <section class="ov-panel">
        <div class="ov-panel__head">
          <div>
            <span class="ov-panel__eyebrow">Connection</span>
            <h3 class="ov-panel__title">Gateway</h3>
          </div>
          <span class="conn-pill" :class="connPillClass">{{ connPillState }}</span>
        </div>
        <div class="ov-form">
          <label class="ov-field">
            <span class="ov-field__label">WebSocket URL</span>
            <input
              v-model="wsUrl"
              class="ov-field__input ov-field__input--mono"
              type="text"
              placeholder="ws://..."
              autocomplete="off"
            />
          </label>
          <label class="ov-field">
            <span class="ov-field__label">
              Token <span class="ov-field__optional">optional</span>
            </span>
            <input
              v-model="wsToken"
              class="ov-field__input"
              type="password"
              placeholder="&mdash;"
              autocomplete="off"
            />
          </label>
          <div class="ov-form__actions">
            <button class="btn btn--primary btn--sm" @click="connect">Connect</button>
            <button class="btn btn--ghost btn--sm" @click="disconnect">Disconnect</button>
          </div>
        </div>
      </section>

      <!-- Event stream -->
      <section class="ov-panel ov-panel--span3">
        <div class="ov-panel__head">
          <div>
            <span class="ov-panel__eyebrow">Live</span>
            <h3 class="ov-panel__title">Event stream</h3>
          </div>
          <span class="ov-panel__meta">{{ eventCountText }}</span>
        </div>
        <div class="ov-event-log">
          <div v-if="eventLog.length === 0" class="ov-event-log__empty">
            <span class="ov-event-log__pulse" />
            Listening for events&hellip;
          </div>
          <div
            v-for="(e, i) in eventLog"
            :key="i"
            class="ov-event-log__row"
            :class="{ 'is-fresh': i === 0 }"
          >
            <span class="ov-event-log__ts">{{ e.ts }}</span>
            <span class="ov-event-log__name">{{ e.eventName }}</span>
            <span class="ov-event-log__payload">{{ e.payloadStr }}</span>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Session {
  key: string
  status?: string
  model?: string
  message_count?: number
  updated_at?: string
}

interface StatusData {
  uptime_ms?: number
  version?: string
  provider?: string
}

interface DoctorReport {
  status?: string
  summary?: string
}

interface UsageData {
  totalSessions?: number
  totalTokens?: number
  totalCostUsd?: number
}

interface SessionsListData {
  sessions?: Session[]
}

interface LogEvent {
  ts: string
  eventName: string
  payloadStr: string
}

// ---------------------------------------------------------------------------
// Stores & Router
// ---------------------------------------------------------------------------

const router = useRouter()
const rpc = useRpcStore()

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const tokensDisplay = ref<string>('—')
const sessionsCount = ref<string>('—')
const provider = ref<string>('—')
const healthStatus = ref<string>('—')
const healthSummary = ref<string>('doctor.status')
const uptime = ref<string>('—')
const versionLine = ref<string>('—')
const costLine = ref<string>('—')
const recentSessions = ref<Session[]>([])
const loadingSessions = ref(true)
const eventLog = ref<LogEvent[]>([])

const wsUrl = ref('')
const wsToken = ref('')

let autoRefreshId: ReturnType<typeof setInterval> | null = null
let pillTickId: ReturnType<typeof setInterval> | null = null
let unsubEvents: (() => void) | null = null

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const connPillState = computed(() => {
  if (rpc.isConnecting) return 'connecting'
  if (rpc.isConnected) return 'connected'
  return 'disconnected'
})

const connPillClass = computed(() => {
  const state = connPillState.value
  if (state === 'connected') return 'ok'
  if (state === 'connecting') return 'warn'
  return 'err'
})

const eventCountText = computed(() => {
  const n = eventLog.value.length
  return `${n} event${n === 1 ? '' : 's'}`
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  // Load connection settings into form
  const settings = loadConnectionSettings()
  wsUrl.value = settings.url
  wsToken.value = settings.token

  // Subscribe to wildcard events
  unsubEvents = rpc.on('*', (eventName: string, payload: unknown) => {
    pushEvent(eventName, payload)
  })

  // Initial data load
  loadData()

  // Auto-refresh every 30s
  autoRefreshId = setInterval(loadData, 30000)

  // Connection pill tick every 2s
  pillTickId = setInterval(() => {
    // Reactive via computed, no-op needed
  }, 2000)
})

onUnmounted(() => {
  if (autoRefreshId) clearInterval(autoRefreshId)
  if (pillTickId) clearInterval(pillTickId)
  if (unsubEvents) unsubEvents()
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function refresh() {
  loadData()
}

function connect() {
  const url = wsUrl.value.trim()
  const token = wsToken.value.trim()
  saveConnectionSettings(url, token)
  rpc.disconnect()
  rpc.connect(url, token || undefined)
}

function disconnect() {
  rpc.disconnect()
}

function openSession(key: string) {
  router.push({ path: '/chat', query: { session: key } })
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
  } catch {
    return
  }

  // Status
  rpc.call<StatusData>('status').then(data => {
    const ms = data.uptime_ms
    if (ms != null) {
      const s = Math.floor(ms / 1000)
      const h = Math.floor(s / 3600)
      const m = Math.floor((s % 3600) / 60)
      uptime.value = `${h}h ${m}m ${s % 60}s`
    } else {
      uptime.value = '—'
    }
    versionLine.value = data.version ? `v${data.version}` : '—'
    provider.value = data.provider ?? '—'
  }).catch(err => {
    console.warn('Failed to load status:', err.message)
  })

  // Doctor status
  rpc.call<DoctorReport>('doctor.status', { agentId: 'main', deep: false }).then(report => {
    healthStatus.value = readinessStatusLabel(report.status ?? 'unknown')
    healthSummary.value = report.summary ?? 'view details'
  }).catch(() => {
    healthStatus.value = 'unavailable'
    healthSummary.value = 'open health'
  })

  // Usage status
  rpc.call<UsageData>('usage.status').then(data => {
    sessionsCount.value = data.totalSessions != null ? String(data.totalSessions) : '—'
    tokensDisplay.value = data.totalTokens != null ? data.totalTokens.toLocaleString() : '—'

    if (data.totalCostUsd != null) {
      const cnyRate = 7.25
      const usd = '$' + Number(data.totalCostUsd).toFixed(4)
      const cny = '¥' + (Number(data.totalCostUsd) * cnyRate).toFixed(4)
      const cur = localStorage.getItem('opensquilla-currency') || 'USD'
      costLine.value = cur === 'CNY' ? `${cny} · ${usd}` : `${usd} · ${cny}`
    } else {
      costLine.value = '—'
    }
  }).catch(() => {
    // Silently ignore
  })

  // Sessions list
  loadingSessions.value = true
  rpc.call<SessionsListData>('sessions.list', { limit: 5 }).then(data => {
    const sessions = (data.sessions || [])
      .slice()
      .sort((a, b) => {
        const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0
        const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0
        return tb - ta
      })
      .slice(0, 6)
    recentSessions.value = sessions
  }).catch(() => {
    recentSessions.value = []
  }).finally(() => {
    loadingSessions.value = false
  })
}

// ---------------------------------------------------------------------------
// Event log
// ---------------------------------------------------------------------------

function pushEvent(eventName: string, payload: unknown) {
  const now = new Date()
  const ts = now.toTimeString().slice(0, 8)
  let payloadStr = ''
  try {
    payloadStr = JSON.stringify(payload)
    if (payloadStr.length > 80) payloadStr = payloadStr.slice(0, 80) + '…'
  } catch {
    payloadStr = String(payload)
  }
  eventLog.value.unshift({ ts, eventName, payloadStr })
  if (eventLog.value.length > 30) {
    eventLog.value = eventLog.value.slice(0, 30)
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function readinessStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ready: 'Ready',
    degraded: 'Degraded',
    action_required: 'Action required',
    unavailable: 'Unavailable',
    unknown: 'Unknown',
  }
  const key = String(status || 'unknown').toLowerCase()
  if (labels[key]) return labels[key]
  return key
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase())
}

function sessionStatusClass(status: string | undefined): string {
  const s = (status || 'unknown').toLowerCase()
  if (s === 'active' || s === 'ready' || s === 'ok') return 'ok'
  if (s === 'paused' || s === 'degraded' || s === 'warn') return 'warn'
  if (s === 'error' || s === 'failed' || s === 'err') return 'err'
  if (s === 'closed' || s === 'ended' || s === 'offline') return 'off'
  return 'off'
}

function sessionStatusLabel(status: string | undefined): string {
  const s = (status || 'unknown').toLowerCase()
  const labels: Record<string, string> = {
    active: 'Active',
    ready: 'Ready',
    ok: 'OK',
    paused: 'Paused',
    degraded: 'Degraded',
    warn: 'Warning',
    error: 'Error',
    failed: 'Failed',
    closed: 'Closed',
    ended: 'Ended',
    offline: 'Offline',
    unknown: 'Unknown',
  }
  return labels[s] || s.charAt(0).toUpperCase() + s.slice(1)
}

function relTime(dateStr: string | undefined): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  if (isNaN(d.getTime())) return dateStr

  const now = new Date()
  const diffMs = now.getTime() - d.getTime()
  const diffSec = Math.floor(diffMs / 1000)
  const diffMin = Math.floor(diffSec / 60)
  const diffHour = Math.floor(diffMin / 60)
  const diffDay = Math.floor(diffHour / 24)

  if (diffSec < 10) return 'just now'
  if (diffSec < 60) return `${diffSec}s ago`
  if (diffMin < 60) return `${diffMin}m ago`
  if (diffHour < 24) return `${diffHour}h ago`
  if (diffDay < 7) return `${diffDay}d ago`
  return d.toLocaleDateString()
}

function formatMessageCount(n: number): string {
  return `${n.toLocaleString()} msg`
}

// ---------------------------------------------------------------------------
// Connection settings helpers (mirroring rpc store internals)
// ---------------------------------------------------------------------------

const WS_URL_KEY = 'opensquilla.wsUrl'
const WS_TOKEN_KEY = 'opensquilla.wsToken'

function getDefaultRpcUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

function loadConnectionSettings(): { url: string; token: string } {
  let url = getDefaultRpcUrl()
  let token = ''
  try { url = localStorage.getItem(WS_URL_KEY) || url } catch {}
  try { token = sessionStorage.getItem(WS_TOKEN_KEY) || '' } catch {}
  return { url, token }
}

function saveConnectionSettings(url: string, token: string): void {
  try { localStorage.setItem(WS_URL_KEY, url || getDefaultRpcUrl()) } catch {}
  try {
    if (token) sessionStorage.setItem(WS_TOKEN_KEY, token)
    else sessionStorage.removeItem(WS_TOKEN_KEY)
  } catch {}
}
</script>

<style scoped>
.ov-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
  max-width: none;
  position: relative;
}

/* Header */
.ov-stage__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--sp-4);
  padding-top: var(--sp-3);
}
.ov-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}
.ov-stage__eyebrow {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-dim);
}
.ov-stage__title {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  position: relative;
  margin: 0;
}
.ov-stage__title::after {
  content: "";
  position: absolute;
  left: 0;
  bottom: -8px;
  width: 36px;
  height: 2px;
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
}
.ov-stage__subtitle {
  font-size: var(--fs-sm);
  color: var(--text-muted);
  margin: var(--sp-3) 0 0;
  max-width: 60ch;
}
.ov-stage__actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

/* Stat tiles */
.ov-stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--sp-3);
}
.ov-stat {
  position: relative;
  text-align: left;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4) var(--sp-4) var(--sp-4) var(--sp-5);
  overflow: hidden;
  transition: border-color var(--transition), box-shadow var(--transition), transform 200ms ease;
  animation: ov-fade-up 360ms ease both;
  cursor: pointer;
  font: inherit;
  color: inherit;
}
.ov-stat--static {
  cursor: default;
}
.ov-stats > .ov-stat:nth-child(1) { animation-delay: 40ms; }
.ov-stats > .ov-stat:nth-child(2) { animation-delay: 80ms; }
.ov-stats > .ov-stat:nth-child(3) { animation-delay: 120ms; }
.ov-stats > .ov-stat:nth-child(4) { animation-delay: 160ms; }
.ov-stat::before {
  content: "";
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 3px;
  background: var(--border);
}
.ov-stat:hover {
  border-color: var(--border-focus);
  box-shadow: 0 8px 24px -16px rgba(0, 0, 0, 0.4);
  transform: translateY(-1px);
}
.ov-stat--static:hover {
  transform: none;
  box-shadow: none;
}
.ov-stat--accent::before {
  background: var(--accent);
}
.ov-stat--accent::after {
  content: "";
  position: absolute;
  inset: 0;
  background: radial-gradient(circle at 0% 0%, color-mix(in srgb, var(--accent) 14%, transparent), transparent 60%);
  pointer-events: none;
}
.ov-stat__icon {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 24px;
  height: 24px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--accent);
  opacity: 0.85;
}
.ov-stat__label {
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 6px;
}
.ov-stat__value {
  font-size: 1.75rem;
  font-weight: 700;
  letter-spacing: 0;
  color: var(--text);
  line-height: 1.18;
  font-variant-numeric: tabular-nums;
}
.ov-stat__value--mono {
  font-family: var(--font-mono);
  font-size: 1.375rem;
  line-height: 1.3;
}
.ov-stat__value--status {
  font-size: clamp(1.35rem, 1.35vw, 1.55rem);
  line-height: 1.2;
  white-space: nowrap;
}
.ov-stat__hint {
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--text-muted);
}
.ov-stat:hover .ov-stat__hint {
  color: var(--text);
}

/* Grid panels */
.ov-grid {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: var(--sp-4);
}
.ov-panel--span2 {
  grid-column: span 1;
}
.ov-panel--span3 {
  grid-column: 1 / -1;
}
.ov-panel {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4) var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  animation: ov-fade-up 380ms ease both;
}
.ov-panel__head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: var(--sp-3);
}
.ov-panel__eyebrow {
  display: block;
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: var(--text-dim);
  margin-bottom: 2px;
}
.ov-panel__title {
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: 0;
  margin: 0;
}
.ov-panel__meta {
  font-size: var(--fs-xs);
  color: var(--text-dim);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-weight: 600;
}
.ov-link {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: transparent;
  border: 0;
  min-height: 40px;
  padding: 0 var(--sp-1);
  cursor: pointer;
  color: var(--accent);
  font-size: var(--fs-xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  white-space: nowrap;
}
.ov-link:hover {
  color: var(--accent-hover);
}

/* Connection pill */
.conn-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-muted);
}
.conn-pill.ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}
.conn-pill.warn {
  background: color-mix(in srgb, var(--warn) 12%, transparent);
  border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}
.conn-pill.err {
  background: color-mix(in srgb, var(--danger) 12%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

/* Recent sessions */
.ov-recent {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ov-recent__row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto auto auto auto;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--radius-md);
  cursor: pointer;
  text-align: left;
  font: inherit;
  color: inherit;
  transition: background var(--transition), border-color var(--transition), transform 80ms ease;
}
.ov-recent__row:hover {
  background: var(--bg-elevated);
  border-color: var(--border);
  transform: translateX(2px);
}
.ov-recent__row:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 1px;
}
.ov-recent__key {
  font-family: var(--font-mono);
  font-size: 12.5px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}
.ov-recent__row:hover .ov-recent__key {
  color: var(--accent);
}
.ov-recent__model {
  font-family: var(--font-mono);
  font-size: 11px;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  color: var(--text-muted);
  padding: 1px 8px;
  border-radius: var(--radius-sm);
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.ov-recent__msgs {
  font-size: var(--fs-xs);
  color: var(--text-muted);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ov-recent__time {
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ov-recent__arrow {
  color: var(--text-dim);
  font-size: 12px;
  opacity: 0;
  transition: opacity var(--transition), transform 120ms ease;
}
.ov-recent__row:hover .ov-recent__arrow {
  opacity: 1;
  color: var(--accent);
  transform: translateX(2px);
}
.ov-recent__empty {
  padding: var(--sp-5) var(--sp-3);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: var(--fs-sm);
}
.ov-recent__empty-icon {
  width: 36px;
  height: 36px;
  color: var(--text-dim);
  line-height: 1;
}

/* Skeleton loading */
.skeleton-row {
  height: 4rem;
  background: linear-gradient(90deg, var(--bg-elevated) 25%, var(--bg-surface) 50%, var(--bg-elevated) 75%);
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: var(--radius-md);
}
@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Form fields */
.ov-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.ov-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ov-field__label {
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
}
.ov-field__optional {
  color: var(--text-dim);
  text-transform: none;
  letter-spacing: 0;
  font-weight: 500;
  margin-left: 4px;
}
.ov-field__input {
  width: 100%;
  min-height: 40px;
  padding: 8px 12px;
  font-size: var(--fs-sm);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  color: var(--text);
  outline: none;
  transition: border-color var(--transition), box-shadow var(--transition);
}
.ov-field__input--mono {
  font-family: var(--font-mono);
  font-size: 12.5px;
}
.ov-field__input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
}
.ov-form__actions {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}

/* Event log */
.ov-event-log {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  max-height: 320px;
  overflow-y: auto;
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.ov-event-log__empty {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: var(--sp-4);
  color: var(--text-muted);
  font-family: var(--font-sans);
  font-size: var(--fs-sm);
}
.ov-event-log__pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
  position: relative;
  display: inline-block;
  flex-shrink: 0;
}
.ov-event-log__pulse::after {
  content: "";
  position: absolute;
  inset: -2px;
  border-radius: 50%;
  border: 1px solid var(--accent);
  opacity: 0.5;
  animation: ov-listening 1.6s ease-in-out infinite;
}
@keyframes ov-listening {
  0%, 100% { transform: scale(1); opacity: 0.5; }
  50% { transform: scale(1.8); opacity: 0; }
}
.ov-event-log__row {
  display: grid;
  grid-template-columns: 80px 200px 1fr;
  gap: 12px;
  padding: 5px var(--sp-3);
  border-bottom: 1px solid color-mix(in srgb, var(--border) 50%, transparent);
}
.ov-event-log__row.is-fresh {
  background: color-mix(in srgb, var(--accent) 6%, transparent);
  animation: ov-row-flash 1.4s ease-out forwards;
}
@keyframes ov-row-flash {
  from { background: color-mix(in srgb, var(--accent) 18%, transparent); }
  to { background: transparent; }
}
.ov-event-log__row:last-child {
  border-bottom: 0;
}
.ov-event-log__ts {
  color: var(--text-dim);
  font-variant-numeric: tabular-nums;
}
.ov-event-log__name {
  color: var(--accent);
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ov-event-log__payload {
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* Status dot */
.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
  flex-shrink: 0;
}
.dot.ok {
  background: var(--ok);
}
.dot.warn {
  background: var(--warn);
}
.dot.err {
  background: var(--danger);
}
.dot.off {
  background: var(--text-dim);
}

/* Animations */
@keyframes ov-fade-up {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (prefers-reduced-motion: reduce) {
  .ov-stat,
  .ov-panel,
  .skeleton-row {
    animation: none !important;
  }
  .ov-event-log__pulse::after {
    animation: none !important;
  }
}

/* Responsive */
@media (max-width: 920px) {
  .ov-grid {
    grid-template-columns: 1fr;
  }
  .ov-panel--span2 {
    grid-column: span 1;
  }
}
@media (max-width: 720px) {
  .ov-stage__header {
    flex-direction: column;
    align-items: stretch;
  }
  .ov-stage__actions {
    width: 100%;
  }
  .ov-stat__icon {
    top: 8px;
    right: 8px;
  }
  .ov-recent__row {
    grid-template-columns: auto 1fr auto;
    gap: 8px;
  }
  .ov-recent__key {
    max-width: 100%;
    white-space: normal;
    overflow-wrap: anywhere;
    text-overflow: clip;
  }
  .ov-recent__arrow {
    display: none;
  }
  .ov-recent__model,
  .ov-recent__msgs {
    display: none;
  }
  .ov-event-log__row {
    grid-template-columns: 70px 1fr;
  }
  .ov-event-log__payload {
    grid-column: 1 / -1;
    padding-left: 82px;
    color: var(--text-dim);
  }
}
</style>

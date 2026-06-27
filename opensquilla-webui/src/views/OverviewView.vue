<template>
  <div class="ov-stage control-stage control-stage--spacious">
    <!-- Header -->
    <header class="ov-stage__header control-stage__header">
      <div class="ov-stage__title-block control-stage__title-block">
        <h2 class="ov-stage__title control-stage__title">OpenSquilla</h2>
        <p class="ov-stage__subtitle control-stage__subtitle">Live status, recent sessions, and the event stream.</p>
      </div>
      <div class="ov-stage__actions control-stage__actions">
        <button class="btn btn--ghost" title="Refresh" :disabled="refreshing" @click="refresh">
          <Icon name="refresh" :size="16" />
          <span>{{ refreshing ? 'Refreshing…' : 'Refresh' }}</span>
        </button>
        <button class="btn btn--primary" title="Open chat" @click="router.push('/chat')">
          <Icon name="chat" :size="16" />
          <span>Open chat</span>
        </button>
      </div>
    </header>

    <!-- Stat cards -->
    <section class="ov-stats control-stat-grid" style="--control-stat-min: 220px">
      <button class="ov-stat ov-stat--accent control-stat control-stat--clickable control-stat--hero" type="button" @click="router.push('/usage')">
        <div class="ov-stat__icon control-stat__icon">
          <Icon name="usage" :size="18" />
        </div>
        <div class="ov-stat__label control-stat__label">Total tokens</div>
        <div class="ov-stat__value control-stat__value">{{ tokensDisplay }}</div>
        <div class="ov-stat__hint control-stat__hint">{{ costLine }}</div>
      </button>

      <button class="ov-stat control-stat control-stat--clickable" type="button" title="Total sessions across all statuses" @click="router.push('/sessions')">
        <div class="ov-stat__icon control-stat__icon">
          <Icon name="sessions" :size="18" />
        </div>
        <div class="ov-stat__label control-stat__label">Total sessions</div>
        <div class="ov-stat__value control-stat__value">{{ sessionsCount }}</div>
        <div class="ov-stat__hint control-stat__hint">view all &rarr;</div>
      </button>

      <button class="ov-stat control-stat control-stat--clickable" type="button" @click="router.push('/agents')">
        <div class="ov-stat__icon control-stat__icon">
          <Icon name="agents" :size="18" />
        </div>
        <div class="ov-stat__label control-stat__label">Provider</div>
        <div class="ov-stat__value ov-stat__value--mono control-stat__value control-stat__value--mono">{{ provider }}</div>
        <div class="ov-stat__hint control-stat__hint">manage agents &rarr;</div>
      </button>

      <button class="ov-stat control-stat control-stat--clickable" type="button" title="Jump to the readiness report" @click="scrollToHealth">
        <div class="ov-stat__icon control-stat__icon">
          <Icon name="logs" :size="18" />
        </div>
        <div class="ov-stat__label control-stat__label">Health</div>
        <div class="ov-stat__value ov-stat__value--status control-stat__value">{{ statusLabelText }}</div>
        <div class="ov-stat__hint control-stat__hint">{{ statusSummary }}</div>
      </button>

      <div class="ov-stat ov-stat--static control-stat control-stat--static">
        <div class="ov-stat__icon control-stat__icon">
          <Icon name="cron" :size="18" />
        </div>
        <div class="ov-stat__label control-stat__label">Uptime</div>
        <div class="ov-stat__value ov-stat__value--mono control-stat__value control-stat__value--mono">{{ uptime }}</div>
        <div class="ov-stat__hint control-stat__hint">{{ versionLine }}</div>
      </div>
    </section>

    <!-- Readiness report (doctor.status) -->
    <section
      id="overview-health"
      class="health-status__rail"
      :class="stripClass"
      aria-label="Health summary"
    >
      <div class="health-score control-stat control-stat--hero">
        <span class="health-score__label control-stat__label">Readiness</span>
        <strong class="control-stat__value">{{ statusLabelText }}</strong>
        <span class="health-score__summary control-stat__hint">{{ statusSummary }}</span>
        <div v-if="contextItems.length" class="health-report-context" aria-label="Health report context">
          <span v-for="([label, value], idx) in contextItems" :key="idx" class="health-report-context__item">
            <b>{{ label }}</b>
            <span class="health-report-context__value">{{ value }}</span>
          </span>
        </div>
      </div>
      <div class="health-count-grid">
        <div class="health-count control-stat" :class="`is-${classToken('blocks_ready')}`">
          <span class="control-stat__label">Needs action</span>
          <strong class="control-stat__value">{{ impactCounts.blocks_ready || 0 }}</strong>
        </div>
        <div class="health-count control-stat" :class="`is-${classToken('degrades')}`">
          <span class="control-stat__label">Degraded</span>
          <strong class="control-stat__value">{{ impactCounts.degrades || 0 }}</strong>
        </div>
        <div class="health-count control-stat" :class="`is-${classToken('optional')}`">
          <span class="control-stat__label">Optional</span>
          <strong class="control-stat__value">{{ impactCounts.optional || 0 }}</strong>
        </div>
        <div class="health-count control-stat" :class="`is-${classToken('none')}`">
          <span class="control-stat__label">Ready</span>
          <strong class="control-stat__value">{{ impactCounts.none || 0 }}</strong>
        </div>
      </div>
    </section>

    <section class="health-findings" aria-label="Health findings">
      <template v-if="healthLoading">
        <article class="health-empty control-card">Loading health report</article>
      </template>
      <template v-else-if="groupedFindings.length === 0">
        <article class="health-empty control-card">No findings returned.</article>
      </template>
      <template v-else>
        <section
          v-for="group in groupedFindings"
          :key="group.title"
          class="health-finding-group"
        >
          <header class="health-finding-group__header">
            <div>
              <h3>{{ group.title }}</h3>
              <p>{{ group.note }}</p>
            </div>
            <span>{{ group.findings.length }}</span>
          </header>
          <article
            v-for="(finding, fIdx) in group.findings"
            :key="finding.id || fIdx"
            class="health-finding control-card"
            :class="`is-${findingTone(findingGroupKind(finding))}`"
          >
            <div class="health-finding__marker" aria-hidden="true">
              <span class="health-finding__dot"></span>
              <span class="health-finding__line"></span>
            </div>
            <div class="health-finding__body">
              <div class="health-finding__meta">
                <span>{{ finding.severity || 'info' }}</span>
                <span class="health-impact">{{ impactLabel(impactValue(finding)) }}</span>
                <span class="health-surface">{{ finding.surface || 'system' }}</span>
                <span
                  v-if="findingBadges(finding)"
                  class="health-chip"
                  :class="findingBadgeClass(finding)"
                >
                  {{ findingBadgeText(finding) }}
                </span>
                <span v-if="finding.restartRequired" class="health-chip">Recovery requires restart</span>
              </div>
              <div class="health-finding__title">
                {{ finding.title || finding.id || `Finding ${fIdx + 1}` }}
              </div>
              <div v-if="finding.detail" class="health-finding__detail">{{ finding.detail }}</div>
              <div v-if="visibleEvidenceEntries(finding.evidence).length" class="health-evidence" aria-label="Finding evidence">
                <span v-for="([key, value], eIdx) in visibleEvidenceEntries(finding.evidence).slice(0, 6)" :key="eIdx">
                  <b>{{ evidenceLabel(key) }}</b>{{ evidenceValue(value) }}
                </span>
              </div>
              <div v-if="(finding.fixSteps || []).length" class="health-steps">
                <div class="health-steps__heading">{{ stepsHeading(findingGroupKind(finding)) }}</div>
                <ol>
                  <li
                    v-for="(step, sIdx) in finding.fixSteps"
                    :key="sIdx"
                    class="health-step"
                  >
                    <span class="health-step__number">{{ sIdx + 1 }}</span>
                    <span class="health-step__body">
                      <b>{{ step.label || 'Step' }}</b>
                      <span v-if="step.command" class="health-step__command">
                        <code>{{ step.command }}</code>
                        <button
                          class="health-step__copy"
                          type="button"
                          title="Copy command"
                          aria-label="Copy command"
                          @click="copyCommand(step.command!)"
                        >
                          <Icon name="copy" :size="14" />
                        </button>
                      </span>
                      <span v-if="step.detail" class="health-step__detail">{{ step.detail }}</span>
                    </span>
                  </li>
                </ol>
              </div>
            </div>
          </article>
        </section>
      </template>
    </section>

    <!-- Grid panels -->
    <div class="ov-grid">
      <!-- Recent sessions -->
      <section class="ov-panel ov-panel--span2 control-panel">
        <div class="ov-panel__head control-panel__head">
          <div>
            <span class="ov-panel__eyebrow control-panel__eyebrow">Recent activity</span>
            <h3 class="ov-panel__title control-panel__title">Sessions</h3>
          </div>
          <button class="ov-link" type="button" @click="router.push('/sessions')">
            View all &rarr;
          </button>
        </div>
        <div class="ov-recent">
          <template v-if="loadingSessions">
            <div class="skeleton-row" />
          </template>
          <template v-else-if="sessionsError">
            <ErrorState :message="sessionsError" :on-retry="refreshSessions" />
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
      <section class="ov-panel control-panel">
        <div class="ov-panel__head control-panel__head">
          <div>
            <span class="ov-panel__eyebrow control-panel__eyebrow">Connection</span>
            <h3 class="ov-panel__title control-panel__title">Gateway</h3>
          </div>
          <span class="conn-pill" :class="connPillClass">{{ connPillState }}</span>
        </div>
        <div class="ov-form">
          <p class="ov-conn-hint">The gateway WebSocket URL and token now live in Settings.</p>
          <router-link class="btn btn--ghost btn--sm" to="/settings/connection">Manage connection in Settings &rarr;</router-link>
        </div>
      </section>

      <!-- Event stream -->
      <section class="ov-panel ov-panel--span3 control-panel">
        <div class="ov-panel__head control-panel__head">
          <div>
            <span class="ov-panel__eyebrow control-panel__eyebrow">Live</span>
            <h3 class="ov-panel__title control-panel__title">Event stream</h3>
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
import { ref, computed, onMounted, onUnmounted, onActivated, onDeactivated } from 'vue'
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import { useRequest } from '@/composables/useRequest'
import { copyTextWithFallback } from '@/utils/browser'
import Icon from '@/components/Icon.vue'
import ErrorState from '@/components/ErrorState.vue'

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

interface FixStep {
  label: string
  command?: string
  detail?: string
}

interface Finding {
  id?: string
  severity?: 'error' | 'warn' | 'info' | 'ok'
  readinessImpact?: 'blocks_ready' | 'degrades' | 'optional' | 'none'
  surface?: string
  title?: string
  detail?: string
  evidence?: Record<string, unknown>
  fixSteps?: FixStep[]
  restartRequired?: boolean
}

interface HealthReport {
  status?: string
  ready?: boolean
  summary?: string
  gatewayUrl?: string
  configPath?: string
  requestedConfigPath?: string
  agentId?: string
  counts?: Record<string, number>
  impactCounts?: Record<string, number>
  findings?: Finding[]
}

interface FindingGroup {
  title: string
  note: string
  findings: Finding[]
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

const HIDDEN_EVIDENCE_KEYS = new Set(['restart_required', 'restartRequired'])

// Per-panel useRequest instances
const { data: statusData, refresh: refreshStatus } = useRequest<StatusData>(
  'status',
  undefined,
  { errorLabel: 'Failed to load status', immediate: false },
)
const { data: usageData, refresh: refreshUsage } = useRequest<UsageData>(
  'usage.status',
  undefined,
  { errorLabel: 'Failed to load usage', toastOnError: false, immediate: false },
)
const { data: sessionsData, loading: loadingSessions, error: sessionsError, refresh: refreshSessions } = useRequest<SessionsListData>(
  'sessions.list',
  { limit: 5 },
  { errorLabel: 'Failed to load sessions', immediate: false },
)

// Derived display values from status panel
const uptime = computed<string>(() => {
  const ms = statusData.value?.uptime_ms
  if (ms == null) return '—'
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${h}h ${m}m ${s % 60}s`
})
const versionLine = computed<string>(() => statusData.value?.version ? `v${statusData.value.version}` : '—')
const provider = computed<string>(() => statusData.value?.provider ?? '—')

// Derived display values from usage panel
const sessionsCount = computed<string>(() =>
  usageData.value?.totalSessions != null ? String(usageData.value.totalSessions) : '—'
)
const tokensDisplay = computed<string>(() =>
  usageData.value?.totalTokens != null ? usageData.value.totalTokens.toLocaleString() : '—'
)
const costLine = computed<string>(() => {
  const cost = usageData.value?.totalCostUsd
  if (cost == null) return '—'
  const cnyRate = 7.25
  const usd = '$' + Number(cost).toFixed(4)
  const cny = '¥' + (Number(cost) * cnyRate).toFixed(4)
  const cur = localStorage.getItem('opensquilla-currency') || 'USD'
  return cur === 'CNY' ? `${cny} · ${usd}` : `${usd} · ${cny}`
})

// Derived recent sessions
const recentSessions = computed<Session[]>(() => {
  const list = sessionsData.value?.sessions || []
  return list
    .slice()
    .sort((a, b) => {
      const ta = a.updated_at ? new Date(a.updated_at).getTime() : 0
      const tb = b.updated_at ? new Date(b.updated_at).getTime() : 0
      return tb - ta
    })
    .slice(0, 6)
})

// Health panel keeps its own imperative state (special error rendering)
const healthLoading = ref(true)
const healthReport = ref<HealthReport | null>(null)
const healthError = ref<Error | null>(null)

const eventLog = ref<LogEvent[]>([])

let autoRefreshId: ReturnType<typeof setInterval> | null = null
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

const stripClass = computed(() => {
  if (healthLoading.value) return 'is-loading'
  if (healthError.value) return 'is-unavailable'
  return `is-${classToken(healthReport.value?.status || 'unknown')}`
})

const statusLabelText = computed(() => {
  if (healthLoading.value) return 'Checking'
  if (healthError.value) return statusLabel('unavailable', false)
  return statusLabel(healthReport.value?.status || 'unknown', healthReport.value?.ready)
})

const statusSummary = computed(() => {
  if (healthLoading.value) return 'Waiting for doctor.status'
  if (healthError.value) return 'Gateway health report unavailable'
  return healthReport.value?.summary || healthReport.value?.status || ''
})

const impactCounts = computed(() => {
  if (healthLoading.value || healthError.value) {
    return { blocks_ready: 0, degrades: 0, optional: 0, none: 0 }
  }
  return healthReport.value?.impactCounts || impactCountsFromSeverity(healthReport.value?.counts || {})
})

const contextItems = computed<[string, string][]>(() => {
  if (healthLoading.value) return []
  const items: [string, string][] = []
  const gatewayUrl = healthReport.value?.gatewayUrl || gatewayContextUrl()
  if (gatewayUrl) items.push(['Gateway', gatewayUrl])
  if (healthReport.value?.configPath) items.push(['Config', healthReport.value.configPath])
  if (healthReport.value?.requestedConfigPath && healthReport.value.requestedConfigPath !== healthReport.value.configPath) {
    items.push(['Requested config', healthReport.value.requestedConfigPath])
  }
  if (healthReport.value?.agentId) items.push(['Agent', healthReport.value.agentId])
  return items
})

const groupedFindings = computed<FindingGroup[]>(() => {
  if (healthLoading.value) return []

  const findings = healthError.value ? [gatewayUnavailableFinding()] : (healthReport.value?.findings || [])

  if (!findings.length) return []

  const groups: FindingGroup[] = [
    {
      title: 'Needs action',
      note: 'Fix these first to make OpenSquilla ready.',
      findings: findings.filter(f => findingGroupKind(f) === 'action'),
    },
    {
      title: 'Degraded capabilities',
      note: 'OpenSquilla can run, but these capabilities need attention.',
      findings: findings.filter(f => findingGroupKind(f) === 'degraded'),
    },
    {
      title: 'Optional setup',
      note: 'These improve capability or posture but do not block readiness.',
      findings: findings.filter(f => findingGroupKind(f) === 'optional'),
    },
    {
      title: 'Ready checks',
      note: 'These surfaces are already working.',
      findings: findings.filter(f => findingGroupKind(f) === 'ready'),
    },
  ]

  return groups.filter(g => g.findings.length)
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  // Initial data load (readiness loads once; deep doctor checks are heavier
  // than the 30s status polls, so they only rerun on manual Refresh).
  // useRequest handles initial load for status/usage/sessions on mount.
  loadHealth()
})

// Timers and the event subscription live on activate/deactivate so a kept-alive
// but hidden Overview stops its 30s/2s polling and event accrual. onActivated
// fires on first mount too, so the timers are owned entirely here.
onActivated(() => {
  startTimers()
  // A returning view refreshes immediately so cached numbers don't linger.
  loadData()
})

onDeactivated(() => {
  stopTimers()
})

onUnmounted(() => {
  stopTimers()
})

function startTimers() {
  if (!unsubEvents) {
    unsubEvents = rpc.on('*', (eventName: string, payload: unknown) => {
      pushEvent(eventName, payload)
    })
  }
  // Auto-refresh every 30s (silent background refresh)
  if (!autoRefreshId) autoRefreshId = setInterval(loadData, 30000)
}

function stopTimers() {
  if (autoRefreshId) {
    clearInterval(autoRefreshId)
    autoRefreshId = null
  }
  if (unsubEvents) {
    unsubEvents()
    unsubEvents = null
  }
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

const refreshing = ref(false)

// Manual refresh shows a busy state on the button; the 30s background poll
// (loadData) intentionally stays silent, so the control reacts only to clicks.
async function refresh() {
  if (refreshing.value) return
  refreshing.value = true
  try {
    await Promise.all([refreshStatus(), refreshUsage(), refreshSessions(), loadHealth()])
  } finally {
    refreshing.value = false
  }
}

function scrollToHealth() {
  document.getElementById('overview-health')?.scrollIntoView({ block: 'start' })
}

async function loadHealth() {
  healthLoading.value = true
  healthError.value = null

  try {
    await rpc.waitForConnection()
    const data = await rpc.call<HealthReport>('doctor.status', { agentId: 'main', deep: true })
    if (!data.gatewayUrl) data.gatewayUrl = gatewayContextUrl()
    healthReport.value = data
  } catch (err) {
    healthError.value = err instanceof Error ? err : new Error(String(err))
    healthReport.value = null
  } finally {
    healthLoading.value = false
  }
}

async function copyCommand(command: string) {
  if (!command) return
  try {
    await copyTextWithFallback(command)
  } catch {
    // Silently ignore copy failures
  }
}

function openSession(key: string) {
  router.push({ path: '/chat', query: { session: key } })
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

function loadData() {
  void refreshStatus()
  void refreshUsage()
  void refreshSessions()
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

function classToken(value: string | undefined | null): string {
  return String(value || 'unknown').toLowerCase().replace(/[^a-z0-9_-]+/g, '-')
}

function impactValue(finding: Finding): string {
  const impact = String(finding?.readinessImpact || '')
  if (['blocks_ready', 'degrades', 'optional', 'none'].includes(impact)) return impact
  const severity = String(finding?.severity || 'info')
  if (severity === 'error') return 'blocks_ready'
  if (severity === 'warn') return 'degrades'
  if (severity === 'info') return 'optional'
  return 'none'
}

function findingGroupKind(finding: Finding): 'action' | 'degraded' | 'optional' | 'ready' {
  const impact = impactValue(finding)
  if (impact === 'blocks_ready') return 'action'
  if (impact === 'degrades') return 'degraded'
  if (impact === 'optional') return 'optional'
  return 'ready'
}

function findingTone(kind: 'action' | 'degraded' | 'optional' | 'ready'): 'error' | 'warn' | 'info' | 'ok' {
  if (kind === 'action') return 'error'
  if (kind === 'degraded') return 'warn'
  if (kind === 'optional') return 'info'
  return 'ok'
}

function impactLabel(impact: string): string {
  const labels: Record<string, string> = {
    blocks_ready: 'Blocks readiness',
    degrades: 'Degrades',
    optional: 'Optional',
    none: 'Reference',
  }
  return labels[impact] || 'Reference'
}

function statusLabel(status: string, ready: boolean | undefined): string {
  if (ready && status === 'degraded') return 'Ready with warnings'
  if (ready) return 'Ready'
  const labels: Record<string, string> = {
    action_required: 'Action required',
    degraded: 'Degraded',
    unavailable: 'Unavailable',
    ready: 'Ready',
  }
  return labels[status] || status
}

function evidenceLabel(key: string): string {
  const label = String(key || '')
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  return label ? label.charAt(0).toUpperCase() + label.slice(1) : ''
}

function evidenceValue(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    const text = JSON.stringify(value)
    return text.length > 120 ? `${text.slice(0, 117)}...` : text
  } catch {
    return String(value)
  }
}

function visibleEvidenceEntries(evidence: Record<string, unknown> | undefined): [string, unknown][] {
  return Object.entries(evidence || {})
    .filter(([key, value]) => value !== undefined && value !== null && !HIDDEN_EVIDENCE_KEYS.has(key))
}

function stepsHeading(kind: 'action' | 'degraded' | 'optional' | 'ready'): string {
  if (kind === 'optional') return 'Optional setup steps'
  if (kind === 'ready') return 'Reference steps'
  return 'Recovery steps'
}

function shellArg(value: string | undefined | null): string {
  const text = String(value || '')
  if (/^[A-Za-z0-9_@%+=:,./~-]+$/.test(text)) return text
  return `'${text.replace(/'/g, `'\\''`)}'`
}

function bootstrapConfigPath(): string {
  return document.getElementById('opensquilla-data')?.dataset.configPath || ''
}

function gatewayUnavailableDetail(gatewayUrl: string, err: Error | null): string {
  const reason = err?.message || String(err)
  if (!gatewayUrl) return reason
  return `Cannot load doctor.status from ${gatewayUrl}. ${reason}`
}

function gatewayUnavailableFixSteps(gatewayUrl: string): FixStep[] {
  if (!isLocalGatewayUrl(gatewayUrl)) {
    return [
      {
        label: 'Inspect remote gateway',
        command: `opensquilla gateway status --gateway ${shellArg(gatewayUrl)} --json`,
      },
      {
        label: 'Repair remote deployment',
        detail: 'Start or repair the remote OpenSquilla gateway deployment, then refresh health.',
      },
    ]
  }
  const target = gatewayStatusTarget(gatewayUrl)
  const bindArgs = target ? ` --bind ${target.host} --port ${target.port}` : ''
  const useConfigTarget = usesDefaultGatewayUrl(gatewayUrl) && Boolean(bootstrapConfigPath())
  const doctorTarget = useConfigTarget ? '' : (gatewayUrl ? ` --gateway ${shellArg(gatewayUrl)}` : '')
  const configTarget = useConfigTarget ? configOption(bootstrapConfigPath()) : ''
  const targetArgs = useConfigTarget ? '' : bindArgs
  return [
    {
      label: 'Run local doctor',
      command: `opensquilla doctor${doctorTarget}${configTarget} --json`,
      detail: 'Checks local config and onboarding before restarting the gateway.',
    },
    { label: 'Start local gateway', command: `opensquilla gateway start${targetArgs}${configTarget}` },
    { label: 'Inspect local gateway', command: `opensquilla gateway status${targetArgs} --json${configTarget}` },
  ]
}

function usesDefaultGatewayUrl(gatewayUrl: string): boolean {
  try {
    const requested = new URL(gatewayUrl || gatewayContextUrl(), location.href)
    const defaults = new URL(gatewayContextUrl(), location.href)
    return requested.protocol === defaults.protocol
      && requested.host === defaults.host
      && requested.pathname === defaults.pathname
  } catch {
    return false
  }
}

function configOption(configPath: string): string {
  return configPath ? ` --config ${shellArg(configPath)}` : ''
}

function isLocalGatewayUrl(gatewayUrl: string): boolean {
  const target = gatewayStatusTarget(gatewayUrl)
  if (!target) return true
  return ['127.0.0.1', '::1', 'localhost', '0.0.0.0'].includes(target.host)
}

function gatewayStatusTarget(gatewayUrl: string): { host: string; port: string } | null {
  try {
    const url = new URL(gatewayUrl || gatewayContextUrl())
    let host = url.hostname || '127.0.0.1'
    if (host.startsWith('[') && host.endsWith(']')) host = host.slice(1, -1)
    if (host === '0.0.0.0') host = '127.0.0.1'
    if (host === '::') host = '::1'
    const port = url.port || ((url.protocol === 'wss:' || url.protocol === 'https:') ? '443' : '18791')
    return { host, port }
  } catch {
    return null
  }
}

function gatewayUnavailableFinding(): Finding {
  const gatewayUrl = gatewayContextUrl()
  const configPath = usesDefaultGatewayUrl(gatewayUrl) ? bootstrapConfigPath() : ''
  return {
    id: 'gateway.unavailable',
    severity: 'error',
    readinessImpact: 'blocks_ready',
    surface: 'gateway',
    title: 'Gateway health report unavailable',
    detail: gatewayUnavailableDetail(gatewayUrl, healthError.value),
    evidence: configPath ? { gatewayUrl, configPath } : { gatewayUrl },
    fixSteps: gatewayUnavailableFixSteps(gatewayUrl),
    restartRequired: false,
  }
}

function impactCountsFromSeverity(counts: Record<string, number>): Record<string, number> {
  return {
    blocks_ready: Number(counts.error || 0),
    degrades: Number(counts.warn || 0),
    optional: Number(counts.info || 0),
    none: Number(counts.ok || 0),
  }
}

function findingBadges(finding: Finding): boolean {
  const id = String(finding?.id || '')
  return id.endsWith('.diagnostic.incomplete')
    || id.endsWith('.repair.pending')
    || id === 'gateway.config.mismatch'
}

function findingBadgeText(finding: Finding): string {
  const id = String(finding?.id || '')
  if (id.endsWith('.diagnostic.incomplete')) return 'Diagnostics incomplete'
  if (id.endsWith('.repair.pending')) return 'Repair pending'
  if (id === 'gateway.config.mismatch') return 'Config mismatch'
  return ''
}

function findingBadgeClass(finding: Finding): string {
  const id = String(finding?.id || '')
  if (id.endsWith('.diagnostic.incomplete')) return 'health-chip--diagnostic'
  if (id.endsWith('.repair.pending')) return 'health-chip--repair'
  if (id === 'gateway.config.mismatch') return 'health-chip--config'
  return ''
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
// Gateway URL helper (the connection editor moved to Settings → Connection)
// ---------------------------------------------------------------------------

function gatewayContextUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}
</script>

<style scoped>
.ov-stats > .ov-stat:nth-child(1) { animation-delay: 40ms; }
.ov-stats > .ov-stat:nth-child(2) { animation-delay: 80ms; }
.ov-stats > .ov-stat:nth-child(3) { animation-delay: 120ms; }
.ov-stats > .ov-stat:nth-child(4) { animation-delay: 160ms; }
.ov-stat__value--status {
  font-size: clamp(1.35rem, 1.35vw, 1.55rem);
  line-height: 1.2;
  white-space: nowrap;
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
.ov-conn-hint {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text-muted);
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

/* Readiness report (moved from the retired Health view) */
.health-status__rail {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: minmax(250px, 1.1fr) minmax(0, 2.4fr);
}

.health-score,
.health-count,
.health-finding,
.health-empty {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  overflow: hidden;
  position: relative;
}

.health-score {
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  min-height: 116px;
  padding: var(--sp-5);
}

.health-score::before {
  background: var(--border);
  bottom: 0;
  content: "";
  left: 0;
  position: absolute;
  top: 0;
  width: 4px;
}

.health-status__rail.is-action_required .health-score::before,
.health-count.is-blocks_ready::before,
.health-count.is-error::before,
.health-finding.is-error .health-finding__dot {
  background: var(--danger);
}

.health-status__rail.is-degraded .health-score::before,
.health-count.is-degrades::before,
.health-count.is-warn::before,
.health-finding.is-warn .health-finding__dot {
  background: var(--warn);
}

.health-count.is-optional::before,
.health-count.is-info::before,
.health-finding.is-info .health-finding__dot {
  background: var(--accent);
}

.health-status__rail.is-ready .health-score::before,
.health-count.is-none::before,
.health-count.is-ok::before,
.health-finding.is-ok .health-finding__dot {
  background: var(--ok);
}

.health-status__rail.is-unavailable .health-score::before {
  background: var(--danger);
}

.health-score__label,
.health-count span:first-child {
  color: var(--text-dim);
  display: block;
  font-size: 12px;
  font-weight: 750;
  letter-spacing: 0.08em;
  line-height: 1.25;
  text-transform: uppercase;
}

.health-score strong {
  display: block;
  font-size: clamp(1.6rem, 1.2rem + 1vw, 2.35rem);
  letter-spacing: 0;
  line-height: 1.12;
  margin-top: var(--sp-2);
}

.health-score__summary {
  color: var(--text-muted);
  display: block;
  font-size: var(--fs-sm);
  margin-top: var(--sp-2);
  min-width: 0;
  overflow-wrap: anywhere;
}

.health-report-context {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--sp-3);
  min-width: 0;
}

.health-report-context__item {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  display: inline-grid;
  font-family: var(--font-mono);
  font-size: 11px;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 6px;
  line-height: 1.5;
  max-width: 100%;
  min-width: 0;
  padding: 3px 7px;
}

.health-report-context__item b {
  color: var(--text-dim);
  font-family: inherit;
  font-weight: 700;
}

.health-report-context__value {
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.health-count-grid {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.health-count {
  min-height: 116px;
  padding: var(--sp-4);
}

.health-count::before {
  background: var(--border);
  border-radius: 999px;
  content: "";
  height: 8px;
  position: absolute;
  right: var(--sp-4);
  top: var(--sp-4);
  width: 8px;
}

.health-count strong {
  display: block;
  font-size: 2rem;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  line-height: 1.12;
  margin-top: var(--sp-4);
}

.health-findings {
  display: grid;
  gap: var(--sp-3);
}

.health-finding-group {
  display: grid;
  gap: var(--sp-3);
}

.health-finding-group__header {
  align-items: end;
  border-bottom: 1px solid var(--border);
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
  padding: 0 2px var(--sp-2);
}

.health-finding-group__header h3 {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: 0;
}

.health-finding-group__header p {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: 3px 0 0;
}

.health-finding-group__header span {
  color: var(--text-dim);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
}

.health-finding {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: 20px minmax(0, 1fr);
  padding: var(--sp-4);
}

.health-finding__marker {
  align-items: center;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding-top: 4px;
}

.health-finding__dot {
  background: var(--text-dim);
  border-radius: 999px;
  box-shadow: 0 0 0 4px color-mix(in srgb, currentColor 10%, transparent);
  display: block;
  height: 10px;
  width: 10px;
}

.health-finding__line {
  background: var(--border);
  border-radius: 999px;
  flex: 1;
  min-height: 32px;
  width: 1px;
}

.health-finding__body {
  min-width: 0;
}

.health-finding__meta {
  align-items: center;
  color: var(--text-dim);
  display: flex;
  flex-wrap: wrap;
  font-size: 10.5px;
  font-weight: 700;
  gap: 6px;
  letter-spacing: 0.12em;
  min-width: 0;
  overflow-wrap: anywhere;
  text-transform: uppercase;
}

.health-impact,
.health-surface,
.health-chip {
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  display: inline-flex;
  letter-spacing: 0.08em;
  padding: 2px 8px;
}

.health-chip {
  color: var(--warn);
}

.health-chip--diagnostic {
  background: color-mix(in srgb, var(--warn) 10%, transparent);
  border-color: color-mix(in srgb, var(--warn) 40%, var(--border));
  color: var(--warn);
}

.health-chip--repair {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border-color: color-mix(in srgb, var(--accent) 38%, var(--border));
  color: var(--accent);
}

.health-chip--config {
  background: color-mix(in srgb, var(--danger) 8%, transparent);
  border-color: color-mix(in srgb, var(--danger) 36%, var(--border));
  color: var(--danger);
}

.health-finding__title {
  font-size: var(--fs-lg);
  font-weight: 700;
  letter-spacing: 0;
  margin-top: var(--sp-2);
  min-width: 0;
  overflow-wrap: anywhere;
}

.health-finding__detail {
  color: var(--text-muted);
  line-height: 1.5;
  margin-top: 4px;
  min-width: 0;
  overflow-wrap: anywhere;
}

.health-evidence {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: var(--sp-3);
  min-width: 0;
  overflow-wrap: anywhere;
}

.health-evidence span {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  display: inline-flex;
  font-family: var(--font-mono);
  font-size: 11px;
  gap: 6px;
  line-height: 1.5;
  max-width: 100%;
  min-width: 0;
  overflow-wrap: anywhere;
  padding: 3px 7px;
}

.health-evidence span b {
  color: var(--text-dim);
  font-family: inherit;
  font-weight: 700;
}

.health-steps {
  display: grid;
  gap: 8px;
  margin-top: var(--sp-3);
}

.health-steps__heading {
  color: var(--text-dim);
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.health-steps ol {
  display: grid;
  gap: 8px;
  list-style: none;
  margin: 0;
  padding: 0;
}

.health-step {
  align-items: start;
  display: grid;
  gap: 10px;
  grid-template-columns: 24px minmax(0, 1fr);
}

.health-step__number {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: 999px;
  color: var(--text-muted);
  display: inline-flex;
  font-family: var(--font-mono);
  font-size: 11px;
  height: 24px;
  justify-content: center;
  width: 24px;
}

.health-step__body {
  color: var(--text-muted);
  min-width: 0;
}

.health-step__body b {
  color: var(--text);
  display: inline-block;
  margin-right: 8px;
}

.health-step__body code {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text);
  display: inline-block;
  font-size: 12px;
  max-width: 100%;
  overflow-wrap: anywhere;
  padding: 3px 7px;
}

.health-step__command {
  align-items: center;
  display: inline-flex;
  gap: 6px;
  max-width: 100%;
  min-width: 0;
  overflow-wrap: anywhere;
  vertical-align: middle;
}

.health-step__copy {
  align-items: center;
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  cursor: pointer;
  display: inline-flex;
  flex: 0 0 auto;
  height: 40px;
  justify-content: center;
  padding: 0;
  transition: background 0.15s ease, border-color 0.15s ease, color 0.15s ease;
  width: 40px;
}

.health-step__copy:hover {
  background: var(--bg-hover);
  border-color: var(--accent);
  color: var(--text);
}

.health-empty {
  color: var(--text-muted);
  padding: var(--sp-4);
}

@media (max-width: 980px) {
  .health-status__rail {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .health-count-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .health-finding {
    grid-template-columns: 16px minmax(0, 1fr);
    padding: var(--sp-3);
  }
}

@media (max-width: 480px) {
  .health-report-context {
    display: grid;
  }

  .health-report-context__item {
    gap: 2px;
    grid-template-columns: minmax(0, 1fr);
    width: 100%;
  }

  .health-step__command {
    display: flex;
    width: 100%;
  }

  .health-step__command code {
    flex: 1 1 auto;
    min-width: 0;
  }
}
</style>

<template>
  <div class="health-layout health-stage">
    <header class="health-stage__header">
      <div class="health-stage__title-block">
        <span class="health-eyebrow">Control &middot; Health</span>
        <h2>OpenSquilla Health</h2>
        <p>{{ summaryText }}</p>
      </div>
      <button
        class="btn btn--ghost"
        title="Refresh health report"
        :disabled="loading"
        @click="refresh"
      >
        <Icon name="refresh" :size="16" />
        <span>Refresh</span>
      </button>
    </header>

    <section
      class="health-status__rail"
      :class="stripClass"
      aria-label="Health summary"
    >
      <div class="health-score">
        <span class="health-score__label">Readiness</span>
        <strong>{{ statusLabelText }}</strong>
        <span class="health-score__summary">{{ statusSummary }}</span>
        <div v-if="contextItems.length" class="health-report-context" aria-label="Health report context">
          <span v-for="([label, value], idx) in contextItems" :key="idx" class="health-report-context__item">
            <b>{{ label }}</b>
            <span class="health-report-context__value">{{ value }}</span>
          </span>
        </div>
      </div>
      <div class="health-count-grid">
        <div class="health-count" :class="`is-${classToken('blocks_ready')}`">
          <span>Needs action</span>
          <strong>{{ impactCounts.blocks_ready || 0 }}</strong>
        </div>
        <div class="health-count" :class="`is-${classToken('degrades')}`">
          <span>Degraded</span>
          <strong>{{ impactCounts.degrades || 0 }}</strong>
        </div>
        <div class="health-count" :class="`is-${classToken('optional')}`">
          <span>Optional</span>
          <strong>{{ impactCounts.optional || 0 }}</strong>
        </div>
        <div class="health-count" :class="`is-${classToken('none')}`">
          <span>Ready</span>
          <strong>{{ impactCounts.none || 0 }}</strong>
        </div>
      </div>
    </section>

    <section class="health-findings" aria-label="Health findings">
      <template v-if="loading">
        <article class="health-empty">Loading health report</article>
      </template>
      <template v-else-if="groupedFindings.length === 0">
        <article class="health-empty">No findings returned.</article>
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
            class="health-finding"
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
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

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

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const HIDDEN_EVIDENCE_KEYS = new Set(['restart_required', 'restartRequired'])

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const rpc = useRpcStore()
const loading = ref(true)
const report = ref<HealthReport | null>(null)
const error = ref<Error | null>(null)

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const summaryText = computed(() => {
  if (loading.value) return 'Checking readiness'
  if (error.value) return 'Health report unavailable'
  return report.value?.summary || report.value?.status || 'Health report loaded'
})

const stripClass = computed(() => {
  if (loading.value) return 'is-loading'
  if (error.value) return 'is-unavailable'
  return `is-${classToken(report.value?.status || 'unknown')}`
})

const statusLabelText = computed(() => {
  if (loading.value) return 'Checking'
  if (error.value) return statusLabel('unavailable', false)
  return statusLabel(report.value?.status || 'unknown', report.value?.ready)
})

const statusSummary = computed(() => {
  if (loading.value) return 'Waiting for doctor.status'
  if (error.value) return 'Gateway health report unavailable'
  return report.value?.summary || report.value?.status || ''
})

const impactCounts = computed(() => {
  if (loading.value || error.value) {
    return { blocks_ready: 0, degrades: 0, optional: 0, none: 0 }
  }
  return report.value?.impactCounts || impactCountsFromSeverity(report.value?.counts || {})
})

const contextItems = computed<[string, string][]>(() => {
  if (loading.value) return []
  const items: [string, string][] = []
  const gatewayUrl = report.value?.gatewayUrl || gatewayContextUrl()
  if (gatewayUrl) items.push(['Gateway', gatewayUrl])
  if (report.value?.configPath) items.push(['Config', report.value.configPath])
  if (report.value?.requestedConfigPath && report.value.requestedConfigPath !== report.value.configPath) {
    items.push(['Requested config', report.value.requestedConfigPath])
  }
  if (report.value?.agentId) items.push(['Agent', report.value.agentId])
  return items
})

const groupedFindings = computed<FindingGroup[]>(() => {
  if (loading.value) return []

  const findings = error.value ? [gatewayUnavailableFinding()] : (report.value?.findings || [])

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
  load()
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function load() {
  loading.value = true
  error.value = null

  try {
    await rpc.waitForConnection()
    const data = await rpc.call<HealthReport>('doctor.status', { agentId: 'main', deep: true })
    if (!data.gatewayUrl) data.gatewayUrl = gatewayContextUrl()
    report.value = data
  } catch (err) {
    error.value = err instanceof Error ? err : new Error(String(err))
    report.value = null
  } finally {
    loading.value = false
  }
}

function refresh() {
  load()
}

async function copyCommand(command: string) {
  if (!command) return
  try {
    await copyText(command)
  } catch {
    // Silently ignore copy failures
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

function copyText(text: string): Promise<void> {
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    return navigator.clipboard.writeText(text)
  }
  const ta = document.createElement('textarea')
  ta.value = text
  ta.setAttribute('readonly', '')
  ta.style.position = 'fixed'
  ta.style.left = '-9999px'
  document.body.appendChild(ta)
  ta.select()
  const ok = document.execCommand('copy')
  document.body.removeChild(ta)
  return ok ? Promise.resolve() : Promise.reject(new Error('Copy command failed'))
}

// ---------------------------------------------------------------------------
// Gateway URL helpers
// ---------------------------------------------------------------------------

function gatewayContextUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
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
    detail: gatewayUnavailableDetail(gatewayUrl, error.value),
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

// ---------------------------------------------------------------------------
// Badge helpers
// ---------------------------------------------------------------------------

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
</script>

<style scoped>
.health-layout,
.health-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  max-width: none;
  position: relative;
}

.health-stage__header {
  align-items: flex-end;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  justify-content: space-between;
  padding-top: var(--sp-3);
}

.health-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.health-stage__header h2 {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  margin: 0;
  position: relative;
}

.health-stage__header h2::after {
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
  bottom: -8px;
  content: "";
  height: 2px;
  left: 0;
  position: absolute;
  width: 36px;
}

.health-stage__header p {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: var(--sp-3) 0 0;
}

.health-eyebrow {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

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
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
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
  background: var(--bg-panel);
  border-color: var(--accent);
  color: var(--text);
}

.health-empty {
  color: var(--text-muted);
  padding: var(--sp-4);
}

.health-finding.is-error {
  border-color: color-mix(in srgb, var(--danger) 42%, var(--border));
}

.health-finding.is-warn {
  border-color: color-mix(in srgb, var(--warn) 42%, var(--border));
}

.health-finding.is-info {
  border-color: color-mix(in srgb, var(--accent) 34%, var(--border));
}

.health-finding.is-ok {
  border-color: color-mix(in srgb, var(--ok) 42%, var(--border));
}

@media (max-width: 980px) {
  .health-status__rail {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 760px) {
  .health-stage__header {
    align-items: stretch;
    flex-direction: column;
  }

  .health-stage__header .btn {
    align-self: flex-start;
    width: auto;
  }

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

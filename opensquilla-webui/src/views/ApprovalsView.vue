<template>
  <div class="ap-stage control-stage">
    <header class="control-stage__header">
      <div class="control-stage__title-block">
        <span class="control-panel__eyebrow">Control &middot; Approvals</span>
        <h2 class="control-stage__title">Approvals</h2>
        <p class="control-stage__subtitle">Tool execution gate — keep risky actions paused until you say go.</p>
      </div>
      <div class="control-stage__actions">
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
      </div>
    </header>

    <section class="stat-row">
      <div class="stat stat--hero">
        <div class="stat-label">Pending</div>
        <div class="stat-value">{{ pending.length }}</div>
        <div class="stat-hint">{{ pending.length ? 'awaiting decision' : 'all clear' }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Strategy</div>
        <div class="stat-value">{{ activeModeLabel }}</div>
        <div class="stat-hint">{{ activeModeDesc }}</div>
      </div>
    </section>

    <div v-if="loading && !loaded" class="state">
      <LoadingSpinner />
    </div>

    <ErrorState v-else-if="error && !loaded" :message="error" :on-retry="loadData" />

    <template v-else>
    <section class="ap-strategy">
      <div class="ap-strategy__head">
        <span class="ap-panel__eyebrow">Strategy</span>
        <h3 class="ap-panel__title">How approvals are handled</h3>
      </div>
      <div class="ap-strategy__options" role="radiogroup" aria-label="Approval strategy">
        <label
          v-for="opt in modeOptions"
          :key="opt.value"
          :class="['ap-radio', mode === opt.value ? 'is-active' : '']"
        >
          <input
            v-model="mode"
            type="radio"
            name="ap-mode"
            :value="opt.value"
            @change="onModeChange"
          />
          <span class="ap-radio__indicator"></span>
          <span class="ap-radio__body">
            <span class="ap-radio__label">{{ opt.label }}</span>
            <span class="ap-radio__desc">{{ opt.desc }}</span>
          </span>
        </label>
      </div>
    </section>

    <section v-if="pending.length === 0" class="state">
      <div class="state-icon">
        <Icon name="check" :size="48" />
      </div>
      <div class="state-title">No pending approvals.</div>
      <p class="state-text">When an agent reaches a risky tool call, it will appear here for your sign-off.</p>
    </section>

    <section v-else class="ap-pending">
      <div class="ap-list-head">
        <h3 class="ap-list__title">
          Pending requests <span class="ap-list__count">{{ pending.length }}</span>
        </h3>
      </div>
      <div class="ap-pending__list">
        <article v-for="item in pending" :key="item.id || ''" class="ap-card">
          <header class="ap-card__head">
            <div class="ap-card__title-row">
              <span class="ap-card__name">{{ toolName(item) }}</span>
              <span v-if="item.namespace" class="ap-pill ap-pill--ns">{{ item.namespace }}</span>
            </div>
            <span class="ap-card__time">awaiting decision</span>
          </header>
          <div class="ap-card__meta">
            <span v-if="item.agent"><em>Agent</em> {{ item.agent }}</span>
            <span v-if="item.sessionKey"><em>Session</em> <code>{{ item.sessionKey }}</code></span>
          </div>
          <div v-if="approvalCommand(item)" class="ap-card__block">
            <div class="ap-card__block-label">Command</div>
            <pre class="ap-card__pre ap-card__pre--cmd">{{ approvalCommand(item) }}</pre>
          </div>
          <div v-if="approvalDetail(item)" class="ap-card__block">
            <div class="ap-card__block-label">Details</div>
            <pre class="ap-card__pre">{{ approvalDetail(item) }}</pre>
          </div>
          <div class="ap-card__actions">
            <button
              class="btn btn--primary"
              :disabled="resolvingId === item.id"
              @click="resolveApproval(item, 'approve')"
            >
              <Icon name="check" :size="16" />
              <span>Approve once</span>
            </button>
            <button
              v-if="canAlways(item)"
              class="btn btn--ghost"
              :disabled="resolvingId === item.id"
              @click="resolveApproval(item, 'always')"
            >
              Always allow this type
            </button>
            <button
              class="btn btn--warn"
              title="Bypass approval prompts while keeping sensitive-path checks"
              :disabled="resolvingId === item.id"
              @click="resolveApproval(item, 'bypass')"
            >
              Bypass approvals
            </button>
            <button
              class="btn btn--danger"
              :disabled="resolvingId === item.id"
              @click="resolveApproval(item, 'deny')"
            >
              <Icon name="x" :size="16" />
              <span>Deny</span>
            </button>
          </div>
        </article>
      </div>
    </section>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useAppStore } from '@/stores/app'
import Icon from '@/components/Icon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import { useToasts } from '@/composables/useToasts'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ApprovalItem {
  id?: string
  toolName?: string
  pluginId?: string
  actionKind?: string
  namespace?: string
  agent?: string
  sessionKey?: string
  command?: string
  argv?: string[]
  args?: Record<string, unknown>
  warning?: string
  params?: Record<string, unknown>
}

interface ApprovalsResponse {
  pending?: ApprovalItem[]
  mode?: string
}

interface ModeOption {
  value: string
  label: string
  desc: string
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const ELEVATED_MODE_KEY = 'opensquilla.elevatedMode'
const ELEVATED_MODE_VERSION_KEY = 'opensquilla.elevatedMode.version'
const ELEVATED_MODE_STORAGE_VERSION = '2'

const modeOptions: ModeOption[] = [
  { value: 'prompt', label: 'Ask every time', desc: 'Every risky tool execution opens an approval prompt.' },
  { value: 'auto-approve', label: 'Auto approve', desc: 'All tool executions are automatically approved.' },
  { value: 'auto-deny', label: 'Auto deny', desc: 'All tool executions are automatically denied.' },
]

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const appStore = useAppStore()
const { pushToast } = useToasts()

const pending = ref<ApprovalItem[]>([])
const mode = ref('prompt')
const loading = ref(false)
const error = ref<string | null>(null)
const loaded = ref(false)
// Id of the approval currently being resolved; gates its decision buttons so a
// double-click (or a second decision) cannot fire a duplicate resolve mid-flight.
const resolvingId = ref<string | null>(null)

let pollInterval: ReturnType<typeof setInterval> | null = null

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const activeMode = computed(() => modeOptions.find(m => m.value === mode.value) || modeOptions[0])
const activeModeLabel = computed(() => loaded.value ? activeMode.value.label : '—')
const activeModeDesc = computed(() => loaded.value ? activeMode.value.desc : '')

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
  // Skip background polling while the tab is hidden to avoid wasted RPC churn.
  pollInterval = setInterval(() => {
    if (document.hidden) return
    loadData()
  }, 5000)
})

onUnmounted(() => {
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = { ...extra }
  // Try to get token from sessionStorage (same key used by RPC store)
  let token = ''
  try { token = sessionStorage.getItem('opensquilla.wsToken') || '' } catch {}
  if (token) headers['Authorization'] = `Bearer ${token}`
  return headers
}

// Tracks whether the current outage already raised a toast, so the 5s poll
// surfaces one danger toast per outage instead of one every tick.
let approvalErrorToasted = false

async function loadData() {
  if (!loaded.value) loading.value = true
  error.value = null
  try {
    const res = await fetch('/api/approvals', { headers: authHeaders() })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    const data = await res.json() as ApprovalsResponse
    pending.value = data.pending || []
    mode.value = data.mode || 'prompt'
    appStore.setApprovalCount(pending.value.length)
    loaded.value = true
    approvalErrorToasted = false
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err)
    error.value = 'Failed to load approvals: ' + msg
    // The 5s poll must not spam a danger toast every tick during an outage
    // (that evicts every other toast). Surface it once per outage; the inline
    // error strip carries the persistent state.
    if (!approvalErrorToasted) {
      pushToast(error.value, { tone: 'danger' })
      approvalErrorToasted = true
    }
  } finally {
    loading.value = false
  }
}

function toolName(item: ApprovalItem): string {
  return item.toolName || item.pluginId || item.actionKind || 'Unknown'
}

function approvalCommand(item: ApprovalItem): string {
  if (item.command) return String(item.command)
  if (Array.isArray(item.argv) && item.argv.length > 0) return item.argv.map(String).join(' ')
  if (item.args && item.args.command) return String(item.args.command)
  return ''
}

function approvalDetail(item: ApprovalItem): string {
  if (item.warning) return String(item.warning)
  const args = item.args || item.params || null
  if (!args) return ''
  try {
    return JSON.stringify(args, null, 2)
  } catch {
    return String(args)
  }
}

function canAlways(item: ApprovalItem): boolean {
  return item.namespace === 'exec' && !!approvalCommand(item)
}

async function resolveApproval(item: ApprovalItem, decision: string) {
  const id = item.id || ''
  if (resolvingId.value === id) return
  resolvingId.value = id
  const namespace = item.namespace || 'exec'
  const approved = decision === 'approve' || decision === 'always' || decision === 'bypass'
  const allowAlways = decision === 'always'
  const rememberIntent = decision === 'always'
  const elevatedMode = decision === 'bypass' ? 'bypass' : ''
  const body: Record<string, unknown> = { id, namespace, approved, allowAlways, rememberIntent }
  if (elevatedMode) body.elevatedMode = elevatedMode

  try {
    const res = await fetch('/api/approvals/resolve', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(body),
    })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    if (elevatedMode) setBrowserElevated(elevatedMode)
    const msg = elevatedMode
      ? 'Approval bypass enabled'
      : (approved ? 'Approved' : 'Denied')
    pushToast(msg + ': ' + id, { tone: 'ok' })
    await loadData()
  } catch (err) {
    pushToast('Failed: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  } finally {
    if (resolvingId.value === id) resolvingId.value = null
  }
}

async function onModeChange() {
  const newMode = mode.value
  try {
    const res = await fetch('/api/approvals/settings', {
      method: 'POST',
      headers: authHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ mode: newMode }),
    })
    if (!res.ok) throw new Error('HTTP ' + res.status)
    pushToast('Approval strategy: ' + newMode, { tone: 'ok' })
    await loadData()
  } catch (err) {
    pushToast('Failed to save strategy: ' + (err instanceof Error ? err.message : String(err)), { tone: 'danger' })
  }
}

function setBrowserElevated(m: string) {
  const normalized = m === 'full' || m === 'bypass' || m === 'on' ? m : ''
  try {
    if (normalized) {
      localStorage.setItem(ELEVATED_MODE_KEY, normalized)
      localStorage.setItem(ELEVATED_MODE_VERSION_KEY, ELEVATED_MODE_STORAGE_VERSION)
    } else {
      localStorage.removeItem(ELEVATED_MODE_KEY)
      localStorage.removeItem(ELEVATED_MODE_VERSION_KEY)
    }
  } catch {
    // ignore
  }
  window.dispatchEvent(new CustomEvent('opensquilla:elevated-mode', { detail: { mode: normalized } }))
}
</script>

<style scoped>
/* Header uses the shared .control-stage primitive (see control-visual-system.css). */

.stat-row {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(2, minmax(0, 1fr));
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

.stat-hint {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin-top: var(--sp-2);
}

.ap-strategy {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: var(--sp-4);
}

.ap-strategy__head {
  margin-bottom: var(--sp-4);
}

.ap-panel__eyebrow {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
}

.ap-panel__title {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: var(--sp-2) 0 0;
}

.ap-strategy__options {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.ap-radio {
  align-items: flex-start;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  cursor: pointer;
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-4);
  transition: border-color 0.15s, background 0.15s;
}

.ap-radio:hover {
  background: var(--bg-elevated);
}

.ap-radio.is-active {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 5%, var(--bg-surface));
}

.ap-radio input {
  position: absolute;
  opacity: 0;
  width: 0;
  height: 0;
}

.ap-radio__indicator {
  border: 2px solid var(--border);
  border-radius: 999px;
  flex-shrink: 0;
  height: 18px;
  margin-top: 2px;
  position: relative;
  width: 18px;
}

.ap-radio.is-active .ap-radio__indicator {
  border-color: var(--accent);
}

.ap-radio.is-active .ap-radio__indicator::after {
  background: var(--accent);
  border-radius: 999px;
  content: '';
  height: 8px;
  left: 50%;
  position: absolute;
  top: 50%;
  transform: translate(-50%, -50%);
  width: 8px;
}

.ap-radio__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ap-radio__label {
  color: var(--text);
  font-size: var(--fs-sm);
  font-weight: 600;
}

.ap-radio__desc {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.state {
  align-items: center;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-8) var(--sp-4);
  text-align: center;
}

.state-icon {
  color: var(--text-dim);
}

.state-title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.state-text {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
  max-width: 520px;
}

.ap-list-head {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.ap-list__title {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: 0;
}

.ap-list__count {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  font-variant-numeric: tabular-nums;
  margin-left: 6px;
  padding: 2px 8px;
}

.ap-pending__list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.ap-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  overflow: hidden;
  padding: var(--sp-4);
}

.ap-card__head {
  align-items: flex-start;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.ap-card__title-row {
  align-items: center;
  display: flex;
  gap: 8px;
  min-width: 0;
}

.ap-card__name {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ap-pill {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 600;
  padding: 2px 8px;
  text-transform: uppercase;
}

.ap-pill--ns {
  background: color-mix(in srgb, var(--accent) 10%, transparent);
  border-color: color-mix(in srgb, var(--accent) 30%, var(--border));
  color: var(--accent);
}

.ap-card__time {
  color: var(--text-dim);
  font-size: 11px;
  flex-shrink: 0;
}

.ap-card__meta {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
}

.ap-card__meta span {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.ap-card__meta em {
  color: var(--text-dim);
  font-style: normal;
}

.ap-card__meta code {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 1px 6px;
}

.ap-card__block {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  overflow: hidden;
}

.ap-card__block-label {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 600;
  padding: var(--sp-2) var(--sp-3);
  text-transform: uppercase;
}

.ap-card__pre {
  background: var(--bg);
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
  margin: 0;
  max-height: 200px;
  overflow: auto;
  padding: var(--sp-3);
  white-space: pre-wrap;
  word-break: break-word;
}

.ap-card__pre--cmd {
  background: color-mix(in srgb, var(--warn) 5%, var(--bg));
}

.ap-card__actions {
  align-items: center;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-top: var(--sp-1);
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .ap-stage .control-stage__header {
    flex-direction: column;
  }

  .ap-stage .control-stage__header .btn {
    align-self: flex-start;
    width: auto;
  }

  .ap-card__actions {
    flex-direction: column;
    align-items: stretch;
  }

  .ap-card__actions .btn {
    justify-content: center;
  }
}

@media (max-width: 480px) {
  .stat-row {
    grid-template-columns: 1fr;
  }
}
</style>

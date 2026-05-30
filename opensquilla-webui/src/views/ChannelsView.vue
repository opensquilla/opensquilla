<template>
  <div class="ch-stage">
    <header class="ch-stage__header">
      <div class="ch-stage__title-block">
        <span class="ch-stage__eyebrow">Control &middot; Channels</span>
        <h2 class="ch-stage__title">Channels</h2>
        <p class="ch-stage__subtitle">
          Runtime status for configured channels. Use guided setup or CLI to add and change channel configuration.
        </p>
      </div>
      <div class="ch-stage__actions">
        <button class="btn btn--ghost" title="Refresh" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>Refresh</span>
        </button>
      </div>
    </header>

    <section class="stat-row">
      <div class="stat stat--hero">
        <div class="stat-label">Total channels</div>
        <div class="stat-value">{{ total }}</div>
        <div class="stat-hint">{{ typeCount }} type{{ typeCount === 1 ? '' : 's' }}</div>
      </div>
      <div class="stat">
        <div class="stat-label">Connected</div>
        <div class="stat-value">
          {{ connected }}
          <span v-if="connected > 0" class="dot ok"></span>
        </div>
        <div class="stat-hint">
          {{ connected > 0 ? 'live' : (attention > 0 ? `${attention} unhealthy` : 'all idle') }}
        </div>
      </div>
      <div class="stat">
        <div class="stat-label">Inactive</div>
        <div class="stat-value">{{ inactive }}</div>
        <div class="stat-hint">
          <span v-if="attention > 0" class="ch-neg">{{ attention }} need attention</span>
          <span v-else>{{ inactiveHint }}</span>
        </div>
      </div>
      <div class="stat">
        <div class="stat-label">Restart attempts</div>
        <div class="stat-value mono">{{ restarts }}</div>
        <div class="stat-hint">since gateway start</div>
      </div>
    </section>

    <section class="ch-list">
      <div class="ch-list__head">
        <h3 class="ch-list__title">
          Configured channels
          <span v-if="channels.length > 0" class="ch-list__count">{{ channels.length }}</span>
        </h3>
      </div>

      <div v-if="channels.length === 0" class="ch-empty">
        <div class="ch-empty__art" aria-hidden="true">
          <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <radialGradient id="cg2" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="rgba(240,160,48,0.18)" />
                <stop offset="60%" stop-color="rgba(240,160,48,0.04)" />
                <stop offset="100%" stop-color="rgba(240,160,48,0)" />
              </radialGradient>
            </defs>
            <circle cx="60" cy="60" r="58" fill="url(#cg2)" />
            <g fill="none" stroke="currentColor" stroke-width="1.4" opacity="0.55">
              <rect x="20" y="40" width="36" height="40" rx="6" />
              <line x1="28" y1="52" x2="48" y2="52" />
              <line x1="28" y1="60" x2="44" y2="60" />
            </g>
            <g fill="none" stroke="var(--accent)" stroke-width="1.6">
              <rect x="64" y="40" width="36" height="40" rx="6" />
              <line x1="72" y1="52" x2="92" y2="52" />
              <line x1="72" y1="60" x2="88" y2="60" />
            </g>
            <g stroke="var(--accent)" stroke-width="1.4" stroke-dasharray="2 4" opacity="0.7">
              <line x1="56" y1="60" x2="64" y2="60" />
            </g>
          </svg>
        </div>
        <div class="ch-empty__title">No configured channels.</div>
        <p class="ch-empty__msg">
          Channel provisioning stays in guided setup and the CLI so credentials, dependency extras, webhook URLs, and restart requirements stay explicit.
        </p>
        <div class="ch-empty__actions">
          <button class="btn btn--primary" type="button" @click="router.push('/setup')">
            <Icon name="config" :size="16" />
            <span>Guided setup</span>
          </button>
        </div>
        <code class="ch-empty__code">opensquilla onboard configure channels &middot; opensquilla channels list</code>
      </div>

      <div v-else class="ch-cards">
        <article
          v-for="(ch, i) in channels"
          :key="ch.id || ch.name || i"
          class="ch-card"
          :style="{ '--i': i }"
        >
          <header class="ch-card__head">
            <span :class="['dot', dotClass(ch.status)]"></span>
            <span class="ch-card__name" :title="ch.name || ch.id || 'Unknown'">
              {{ ch.name || ch.id || 'Unknown' }}
            </span>
            <span class="chip mono">{{ ch.type || 'unknown' }}</span>
          </header>
          <div class="ch-card__status">
            <span :class="['chip', chipClass(ch.status)]">{{ ch.status || 'stopped' }}</span>
          </div>
          <dl class="ch-card__meta">
            <div>
              <dt>Connected</dt>
              <dd class="ch-mono">{{ formatSince(ch.connected_since) }}</dd>
            </div>
            <div>
              <dt>Restart attempts</dt>
              <dd class="ch-mono">{{ ch.restart_attempts ?? '0' }}</dd>
            </div>
          </dl>
          <details class="ch-card__config">
            <summary>Adapter config</summary>
            <pre class="ch-card__config-pre">{{ formatConfig(ch) }}</pre>
          </details>
          <footer class="ch-card__footnote">
            <span>{{ statusHint(ch) }}</span>
          </footer>
        </article>
      </div>
    </section>
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

interface Channel {
  name?: string
  id?: string
  type?: string
  status?: string
  connected_since?: string | number | null
  restart_attempts?: number
  enabled?: boolean
  configured?: boolean
  [key: string]: unknown
}

interface ChannelsStatusResponse {
  channels?: Channel[]
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_ORDER: Record<string, number> = {
  running: 0,
  connected: 0,
  restarting: 1,
  exhausted: 1,
  dead: 1,
  stopped: 2,
  disabled: 3,
}

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const rpc = useRpcStore()
const router = useRouter()
const channels = ref<Channel[]>([])

let pollInterval: ReturnType<typeof setInterval> | null = null
let unsubStatus: (() => void) | null = null

// ---------------------------------------------------------------------------
// Computed
// ---------------------------------------------------------------------------

const total = computed(() => channels.value.length)

const connected = computed(() =>
  channels.value.filter(c => c.status === 'running' || c.status === 'connected').length
)

const attention = computed(() =>
  channels.value.filter(c => needsAttention(c.status)).length
)

const inactive = computed(() => total.value - connected.value - attention.value)

const disabled = computed(() =>
  channels.value.filter(c => c.status === 'disabled').length
)

const restarts = computed(() =>
  channels.value.reduce((acc, c) => acc + (Number(c.restart_attempts) || 0), 0)
)

const typeCount = computed(() => {
  const types = new Set<string>()
  channels.value.forEach(c => { if (c.type) types.add(c.type) })
  return types.size
})

const inactiveHint = computed(() => {
  if (inactive.value === 0) return 'no inactive channels'
  if (disabled.value > 0) return `${disabled.value} disabled`
  return 'configured but idle'
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

onMounted(() => {
  loadData()
  unsubStatus = rpc.on('channel.status', () => loadData())
  pollInterval = setInterval(loadData, 30000)
})

onUnmounted(() => {
  if (unsubStatus) {
    unsubStatus()
    unsubStatus = null
  }
  if (pollInterval) {
    clearInterval(pollInterval)
    pollInterval = null
  }
})

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

async function loadData() {
  try {
    await rpc.waitForConnection()
    const data = await rpc.call<ChannelsStatusResponse>('channels.status')
    const raw = (data.channels || []).filter(c => c && c.configured !== false)

    channels.value = [...raw].sort((a, b) => {
      const oa = STATUS_ORDER[a.status || ''] ?? 1
      const ob = STATUS_ORDER[b.status || ''] ?? 1
      return oa - ob
    })
  } catch (err) {
    console.warn('Failed to load channels: ' + (err instanceof Error ? err.message : String(err)))
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function needsAttention(status?: string): boolean {
  return status === 'dead' || status === 'restarting' || status === 'exhausted'
}

function isRunning(status?: string): boolean {
  return status === 'running' || status === 'connected'
}

function isDead(status?: string): boolean {
  return status === 'dead'
}

function dotClass(status?: string): string {
  if (isRunning(status)) return 'ok'
  if (isDead(status)) return 'err'
  return 'off'
}

function chipClass(status?: string): string {
  if (isRunning(status)) return 'chip-ok'
  if (isDead(status)) return 'chip-danger'
  return ''
}

function formatSince(since?: string | number | null): string {
  if (!since) return '—'
  const d = new Date(since)
  if (isNaN(d.getTime())) return String(since)
  return d.toLocaleString()
}

function formatConfig(ch: Channel): string {
  try {
    return JSON.stringify(ch, null, 2)
  } catch {
    return String(ch)
  }
}

function statusHint(ch: Channel): string {
  const status = ch.status || (ch.connected ? 'connected' : 'stopped')
  const running = isRunning(status)
  const dead = isDead(status)
  const enabled = ch.enabled !== false
  const name = ch.name || '<name>'

  if (!enabled) {
    return 'Disabled in config — gateway restart required after re-enabling. Run `opensquilla onboard configure channels` to change.'
  }
  if (dead) {
    return `Adapter is dead. Inspect gateway logs, then \`opensquilla channels restart ${name}\`.`
  }
  if (running) {
    return 'Adapter is live in the current gateway process.'
  }
  if (status === 'restarting') {
    return 'Adapter is restarting after dispatch errors.'
  }
  if (status === 'exhausted') {
    return `Adapter exhausted its retry budget. Try \`opensquilla channels restart ${name}\`.`
  }
  return 'Configured on disk but not active in this gateway process — restart the gateway to load it.'
}
</script>

<style scoped>
.ch-stage {
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
  max-width: none;
  position: relative;
}

.ch-stage__header {
  align-items: flex-end;
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-4);
  justify-content: space-between;
  padding-top: var(--sp-3);
}

.ch-stage__title-block {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ch-stage__title {
  font-size: clamp(1.625rem, 1.2rem + 1vw, 2.25rem);
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.05;
  margin: 0;
  position: relative;
}

.ch-stage__title::after {
  background: linear-gradient(90deg, var(--accent), transparent);
  border-radius: 2px;
  bottom: -8px;
  content: "";
  height: 2px;
  left: 0;
  position: absolute;
  width: 36px;
}

.ch-stage__subtitle {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin: var(--sp-3) 0 0;
}

.ch-stage__eyebrow {
  color: var(--text-dim);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.16em;
  text-transform: uppercase;
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
  font-size: 10.5px;
  font-weight: 700;
  letter-spacing: 0.14em;
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

.stat-hint {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  margin-top: var(--sp-2);
}

.dot {
  border-radius: 999px;
  display: inline-block;
  height: 8px;
  width: 8px;
}

.dot.ok {
  background: var(--ok);
}

.dot.err {
  background: var(--danger);
}

.dot.off {
  background: var(--text-dim);
}

.ch-neg {
  color: var(--danger);
}

.ch-list__head {
  align-items: center;
  display: flex;
  gap: var(--sp-3);
  justify-content: space-between;
}

.ch-list__title {
  font-size: var(--fs-md);
  letter-spacing: 0;
  margin: 0;
}

.ch-list__count {
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

.ch-cards {
  display: grid;
  gap: var(--sp-3);
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
}

.ch-card {
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  color: var(--text);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  overflow: hidden;
  padding: var(--sp-4);
  position: relative;
}

.ch-card__head {
  align-items: center;
  display: flex;
  gap: 10px;
}

.ch-card__name {
  flex: 1;
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ch-card__status {
  display: flex;
}

.ch-card__meta {
  display: grid;
  gap: var(--sp-2);
  margin: 0;
}

.ch-card__meta > div {
  align-items: center;
  display: flex;
  gap: var(--sp-2);
  justify-content: space-between;
}

.ch-card__meta dt {
  color: var(--text-dim);
  font-size: var(--fs-sm);
}

.ch-card__meta dd {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: var(--fs-sm);
  margin: 0;
}

.ch-card__config {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  margin-top: var(--sp-1);
}

.ch-card__config summary {
  color: var(--text-muted);
  cursor: pointer;
  font-size: var(--fs-sm);
  font-weight: 500;
  padding: var(--sp-2) var(--sp-3);
  user-select: none;
}

.ch-card__config-pre {
  background: var(--bg-elevated);
  border-top: 1px solid var(--border);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.5;
  margin: 0;
  max-height: 240px;
  overflow: auto;
  padding: var(--sp-3);
  white-space: pre-wrap;
  word-break: break-word;
}

.ch-card__footnote {
  color: var(--text-dim);
  font-size: 11px;
  line-height: 1.5;
  margin-top: auto;
}

.ch-empty {
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

.ch-empty__art {
  color: var(--text-dim);
  height: 120px;
  width: 120px;
}

.ch-empty__art svg {
  display: block;
  height: 100%;
  width: 100%;
}

.ch-empty__title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.ch-empty__msg {
  color: var(--text-muted);
  font-size: var(--fs-sm);
  line-height: 1.5;
  margin: 0;
  max-width: 520px;
}

.ch-empty__actions {
  display: flex;
  gap: var(--sp-3);
}

.ch-empty__code {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 11px;
  padding: 6px 12px;
}

.chip {
  background: var(--bg-elevated);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-muted);
  display: inline-flex;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.04em;
  padding: 3px 8px;
  text-transform: uppercase;
}

.chip.mono {
  font-family: var(--font-mono);
  text-transform: none;
}

.chip-ok {
  background: color-mix(in srgb, var(--ok) 12%, transparent);
  border-color: color-mix(in srgb, var(--ok) 40%, var(--border));
  color: var(--ok);
}

.chip-danger {
  background: color-mix(in srgb, var(--danger) 10%, transparent);
  border-color: color-mix(in srgb, var(--danger) 40%, var(--border));
  color: var(--danger);
}

@media (max-width: 980px) {
  .stat-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .ch-stage__header {
    align-items: stretch;
    flex-direction: column;
  }

  .ch-stage__header .btn {
    align-self: flex-start;
    width: auto;
  }

  .ch-cards {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 480px) {
  .stat-row {
    grid-template-columns: 1fr;
  }
}
</style>

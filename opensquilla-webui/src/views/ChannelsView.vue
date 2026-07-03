<template>
  <div class="ch-stage control-stage">
    <header class="ch-stage__header control-stage__header">
      <div class="ch-stage__title-block control-stage__title-block">
        <h1 class="ch-stage__title control-stage__title">{{ t('console.channels.title') }}</h1>
        <p class="ch-stage__subtitle control-stage__subtitle">
          {{ t('console.channels.subtitle') }}
        </p>
      </div>
      <div class="ch-stage__actions control-stage__actions">
        <button class="btn btn--ghost" :title="t('console.channels.settingsHint')" @click="openSettingsSurface">
          <Icon name="settings" :size="16" aria-hidden="true" />
          <span>{{ t('console.channels.openSettings') }}</span>
        </button>
        <button class="btn btn--ghost" :title="t('console.common.refresh')" @click="loadData">
          <Icon name="refresh" :size="16" />
          <span>{{ t('console.common.refresh') }}</span>
        </button>
      </div>
    </header>

    <section class="stat-row control-stat-grid control-stat-grid--fixed" style="--control-stat-columns: 4">
      <div class="stat stat--hero control-stat control-stat--hero">
        <div class="stat-label control-stat__label">{{ t('console.channels.totalChannels') }}</div>
        <div class="stat-value control-stat__value">{{ total }}</div>
        <div class="stat-hint control-stat__hint">{{ t('console.channels.typeCount', { n: typeCount }) }}</div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">{{ t('console.channels.connected') }}</div>
        <div class="stat-value control-stat__value">
          {{ connected }}
          <span v-if="connected > 0" class="dot ok"></span>
        </div>
        <div class="stat-hint control-stat__hint">
          {{ connected > 0 ? t('console.channels.live') : (attention > 0 ? t('console.channels.unhealthy', { n: attention }) : t('console.channels.allIdle')) }}
        </div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">{{ t('console.channels.inactive') }}</div>
        <div class="stat-value control-stat__value">{{ inactive }}</div>
        <div class="stat-hint control-stat__hint">
          <span v-if="attention > 0" class="ch-neg">{{ t('console.channels.needAttention', { n: attention }) }}</span>
          <span v-else>{{ inactiveHint }}</span>
        </div>
      </div>
      <div class="stat control-stat">
        <div class="stat-label control-stat__label">{{ t('console.channels.restartAttempts') }}</div>
        <div class="stat-value mono control-stat__value control-stat__value--mono">{{ restarts }}</div>
        <div class="stat-hint control-stat__hint">{{ t('console.channels.sinceGatewayStart') }}</div>
      </div>
    </section>

    <section class="ch-list">
      <div class="ch-list__head">
        <h3 class="ch-list__title">
          {{ t('console.channels.configuredChannels') }}
          <span v-if="channels.length > 0" class="ch-list__count">{{ channels.length }}</span>
        </h3>
      </div>

      <div v-if="loading && channels.length === 0" class="control-empty">
        <LoadingSpinner />
      </div>

      <ErrorState v-else-if="error" :message="error" :on-retry="loadData" />

      <div v-else-if="channels.length === 0" class="control-empty ch-empty">
        <div class="ch-empty__art" aria-hidden="true">
          <svg viewBox="0 0 120 120" xmlns="http://www.w3.org/2000/svg">
            <defs>
              <radialGradient id="cg2" cx="50%" cy="50%" r="50%">
                <stop offset="0%" stop-color="color-mix(in srgb, var(--accent) 18%, transparent)" />
                <stop offset="60%" stop-color="color-mix(in srgb, var(--accent) 4%, transparent)" />
                <stop offset="100%" stop-color="transparent" />
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
        <div class="control-empty__title">{{ t('console.channels.emptyTitle') }}</div>
        <p class="control-empty__hint">
          {{ t('console.channels.emptyMsg') }}
        </p>
        <div class="ch-empty__actions">
          <button class="btn btn--primary" type="button" @click="openSettingsSurface">
            <Icon name="settings" :size="16" />
            <span>{{ t('console.channels.openSettingsBtn') }}</span>
          </button>
        </div>
        <code class="ch-empty__code">opensquilla onboard configure channels &middot; opensquilla channels list</code>
      </div>

      <div v-else class="ch-cards control-card-grid" style="--control-card-min: 300px">
        <article
          v-for="(ch, i) in channels"
          :key="ch.id || ch.name || i"
          class="ch-card control-card"
          :style="{ '--i': i }"
        >
          <header class="ch-card__head">
            <span :class="['dot', dotClass(ch.status)]"></span>
            <span class="ch-card__name" :title="ch.name || ch.id || t('console.channels.unknown')">
              {{ ch.name || ch.id || t('console.channels.unknown') }}
            </span>
            <span class="chip mono">{{ ch.type || 'unknown' }}</span>
          </header>
          <div class="ch-card__status">
            <span :class="['chip', chipClass(ch.status)]">{{ ch.status || 'stopped' }}</span>
          </div>
          <dl class="ch-card__meta">
            <div>
              <dt>{{ t('console.channels.connected') }}</dt>
              <dd class="ch-mono">{{ formatSince(ch.connected_since) }}</dd>
            </div>
            <div>
              <dt>{{ t('console.channels.restartAttempts') }}</dt>
              <dd class="ch-mono">{{ ch.restart_attempts ?? '0' }}</dd>
            </div>
          </dl>
          <details class="ch-card__config">
            <summary>{{ t('console.channels.adapterConfig') }}</summary>
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
import { computed, onActivated, onDeactivated, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { useRpcStore } from '@/stores/rpc'
import Icon from '@/components/Icon.vue'
import ErrorState from '@/components/ErrorState.vue'
import LoadingSpinner from '@/components/LoadingSpinner.vue'
import { useRequest } from '@/composables/useRequest'

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

const { t } = useI18n()
const rpc = useRpcStore()
const router = useRouter()

// immediate: false — under <KeepAlive> the composable's onMounted fetch fires
// only on first mount, so loading is driven from onActivated instead (execute()
// on the first display for the spinner, refresh() silently afterwards).
const { data: channelsData, loading, error, execute, refresh } = useRequest<ChannelsStatusResponse>(
  'channels.status',
  undefined,
  { immediate: false, errorLabel: t('console.channels.loadFailed') },
)

const channels = computed<Channel[]>(() => {
  const raw = (channelsData.value?.channels || []).filter(c => c && c.configured !== false)
  return [...raw].sort((a, b) => {
    const oa = STATUS_ORDER[a.status || ''] ?? 1
    const ob = STATUS_ORDER[b.status || ''] ?? 1
    return oa - ob
  })
})

const loadData = refresh

let pollTimer: ReturnType<typeof setInterval> | null = null
let unsubs: Array<() => void> = []

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
  if (inactive.value === 0) return t('console.channels.noInactive')
  if (disabled.value > 0) return t('console.channels.disabledCount', { n: disabled.value })
  return t('console.channels.configuredButIdle')
})

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

// This view is kept-alive (route meta.keepAlive), so the live `channel.status`
// subscription and the fallback poll are bound on activation and released on
// deactivation — they must not keep firing while the view is cached off-screen.
// onActivated also runs on first display: execute() (with the spinner) covers the
// initial empty load, refresh() (silent) covers every keep-alive revisit so the
// background refresh never flashes the spinner over already-rendered data.
// onUnmounted is a final safety net for KeepAlive cache eviction.
let activatedOnce = false

function teardownLive() {
  unsubs.forEach(unsub => unsub())
  unsubs = []
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

onActivated(() => {
  if (!activatedOnce) {
    activatedOnce = true
    void execute()
  } else {
    void refresh()
  }
  unsubs = [rpc.on('channel.status', () => { void refresh() })]
  pollTimer = setInterval(() => { void refresh() }, 30000)
})

onDeactivated(teardownLive)
onUnmounted(teardownLive)

// Both platforms own a `/settings` route (web overlay / desktop settings view).
function openSettingsSurface(): void {
  void router.push('/settings')
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
    return t('console.channels.hintDisabled')
  }
  if (dead) {
    return t('console.channels.hintDead', { cmd: `opensquilla channels restart ${name}` })
  }
  if (running) {
    return t('console.channels.hintRunning')
  }
  if (status === 'restarting') {
    return t('console.channels.hintRestarting')
  }
  if (status === 'exhausted') {
    return t('console.channels.hintExhausted', { cmd: `opensquilla channels restart ${name}` })
  }
  return t('console.channels.hintConfiguredInactive')
}
</script>

<style scoped>
.stat--hero {
  min-height: 116px;
}

.dot {
  border-radius: var(--radius-full);
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
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  gap: var(--sp-4);
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

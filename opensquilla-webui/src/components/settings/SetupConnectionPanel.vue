<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'

// Gateway connection editor. This is the one Settings section that must work
// while the gateway is NOT connected — it is exactly how you point the UI at a
// reachable gateway. It therefore owns its own form state and talks only to the
// rpc store + browser storage; it never depends on catalog/readiness RPCs, so
// it renders outside SettingsDialog's `!loaded` gate.

const WS_URL_KEY = 'opensquilla.wsUrl'
const WS_TOKEN_KEY = 'opensquilla.wsToken'

const rpc = useRpcStore()

const wsUrl = ref('')
const wsToken = ref('')

function defaultRpcUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

function loadConnectionSettings(): { url: string; token: string } {
  let url = defaultRpcUrl()
  let token = ''
  try { url = localStorage.getItem(WS_URL_KEY) || url } catch { /* private mode */ }
  try { token = sessionStorage.getItem(WS_TOKEN_KEY) || '' } catch { /* private mode */ }
  return { url, token }
}

onMounted(() => {
  const settings = loadConnectionSettings()
  wsUrl.value = settings.url
  wsToken.value = settings.token
})

const statusState = computed(() => {
  if (rpc.isConnecting) return 'connecting'
  if (rpc.isConnected) return 'connected'
  return 'disconnected'
})

const statusPillClass = computed(() => {
  if (statusState.value === 'connected') return 'ok'
  if (statusState.value === 'connecting') return 'warn'
  return 'err'
})

const statusLabel = computed(() => {
  if (statusState.value === 'connected') return 'Connected'
  if (statusState.value === 'connecting') return 'Connecting'
  return 'Disconnected'
})

const statusReason = computed(() => {
  if (statusState.value === 'connected') return 'Live link to the gateway socket.'
  if (statusState.value === 'connecting') return 'Reaching the gateway…'
  if (rpc.error) return `Last attempt failed: ${rpc.error}`
  return 'Not connected. Check the WebSocket URL and try Connect.'
})

function connect() {
  const url = wsUrl.value.trim()
  const token = wsToken.value.trim()
  rpc.disconnect()
  void rpc.connect(url, token || undefined)
}

function disconnect() {
  rpc.disconnect()
}
</script>

<template>
  <section class="control-section">
    <div class="control-section__head">
      <h3 class="control-section__title">Connection</h3>
      <p class="control-section__desc">Point this browser at a gateway. Connecting applies immediately &mdash; no save needed.</p>
    </div>

    <div class="conn-status" :class="statusPillClass" role="status" aria-live="polite">
      <span class="conn-status__pill" :class="statusPillClass">{{ statusLabel }}</span>
      <span class="conn-status__reason">{{ statusReason }}</span>
    </div>

    <div class="control-row control-row--stack">
      <div class="control-row__label-block">
        <label class="control-row__label" for="conn-ws-url">WebSocket URL</label>
        <span class="control-row__desc">The gateway socket endpoint, e.g. <code>ws://host:port/ws</code>.</span>
      </div>
      <div class="control-row__control">
        <input
          id="conn-ws-url"
          v-model="wsUrl"
          class="control-input conn-input--mono"
          type="text"
          placeholder="ws://..."
          autocomplete="off"
          spellcheck="false"
        >
      </div>
    </div>

    <div class="control-row control-row--stack">
      <div class="control-row__label-block">
        <label class="control-row__label" for="conn-ws-token">Token <span class="conn-optional">optional</span></label>
        <span class="control-row__desc">Bearer token for gateways that require auth. Stored in this tab only.</span>
      </div>
      <div class="control-row__control">
        <input
          id="conn-ws-token"
          v-model="wsToken"
          class="control-input"
          type="password"
          placeholder="&mdash;"
          autocomplete="off"
        >
      </div>
    </div>

    <div class="conn-actions">
      <button type="button" class="btn btn--primary" @click="connect">
        {{ statusState === 'connected' ? 'Reconnect' : 'Connect' }}
      </button>
      <button type="button" class="btn" @click="disconnect">Disconnect</button>
    </div>
  </section>
</template>

<style scoped>
.conn-status {
  align-items: baseline;
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
  margin-bottom: var(--sp-4);
  padding: var(--sp-3);
}

.conn-status.ok {
  background: color-mix(in srgb, var(--ok) 8%, var(--bg-surface));
  border-color: color-mix(in srgb, var(--ok) 35%, var(--border));
}

.conn-status.warn {
  background: color-mix(in srgb, var(--warn) 8%, var(--bg-surface));
  border-color: color-mix(in srgb, var(--warn) 35%, var(--border));
}

.conn-status.err {
  background: color-mix(in srgb, var(--danger) 8%, var(--bg-surface));
  border-color: color-mix(in srgb, var(--danger) 35%, var(--border));
}

.conn-status__pill {
  border-radius: 999px;
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  padding: 3px 10px;
  text-transform: uppercase;
}

.conn-status__pill.ok { background: color-mix(in srgb, var(--ok) 16%, transparent); color: var(--ok); }
.conn-status__pill.warn { background: color-mix(in srgb, var(--warn) 16%, transparent); color: var(--warn); }
.conn-status__pill.err { background: color-mix(in srgb, var(--danger) 16%, transparent); color: var(--danger); }

.conn-status__reason {
  color: var(--text-muted);
  font-size: var(--fs-sm);
}

.conn-input--mono {
  font-family: var(--font-mono);
}

.conn-optional {
  color: var(--text-dim);
  font-size: var(--fs-xs);
  font-weight: 400;
}

.conn-actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-4);
}
</style>

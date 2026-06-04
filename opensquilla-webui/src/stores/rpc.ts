import { ref, computed } from 'vue'
import { defineStore } from 'pinia'
import { RpcClient, type RpcEventHandler } from '@/lib/rpc'

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

export const useRpcStore = defineStore('rpc', () => {
  const client = ref<RpcClient | null>(null)
  const state = ref<'disconnected' | 'connecting' | 'connected'>('disconnected')
  const policy = ref<Record<string, unknown> | null>(null)
  const error = ref<string | null>(null)

  const isConnected = computed(() => state.value === 'connected')
  const isConnecting = computed(() => state.value === 'connecting')

  function init() {
    const rpc = new RpcClient()
    client.value = rpc

    rpc.on('_state', (s: 'disconnected' | 'connecting' | 'connected') => {
      state.value = s
    })

    rpc.on('_hello', (data: { policy?: Record<string, unknown> }) => {
      policy.value = data.policy || null
    })

    rpc.on('_gap', (detail: unknown) => {
      console.warn('[RPC] Sequence gap detected:', detail)
    })

    // Auto-connect on init
    const { url, token } = loadConnectionSettings()
    if (rpc.state === 'disconnected') {
      rpc.connect(url, token || undefined)
    }
  }

  async function connect(url: string, token?: string) {
    if (!client.value) throw new Error('RPC client not initialized')
    error.value = null
    saveConnectionSettings(url, token || '')
    client.value.connect(url, token)
  }

  function disconnect() {
    client.value?.disconnect()
    state.value = 'disconnected'
    policy.value = null
  }

  async function call<T = unknown>(method: string, params?: Record<string, unknown>): Promise<T> {
    if (!client.value) throw new Error('RPC client not initialized')
    if (state.value !== 'connected') {
      throw new Error(`Cannot call ${method}: not connected (state: ${state.value})`)
    }
    return client.value.call(method, params) as Promise<T>
  }

  function on(event: string, handler: RpcEventHandler): () => void {
    if (!client.value) {
      console.warn(`[RPC] No client for event subscription: ${event}`)
      return () => {}
    }
    return client.value.on(event, handler)
  }

  function waitForConnection(timeoutMs?: number): Promise<void> {
    if (!client.value) return Promise.reject(new Error('RPC client not initialized'))
    if (state.value === 'connected') return Promise.resolve()
    return client.value.waitForConnection(timeoutMs)
  }

  return {
    client,
    state,
    policy,
    error,
    isConnected,
    isConnecting,
    init,
    connect,
    disconnect,
    call,
    on,
    waitForConnection,
  }
})

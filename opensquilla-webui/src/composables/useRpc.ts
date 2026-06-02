import { ref, onMounted, onUnmounted } from 'vue'
import { useRpcStore } from '@/stores/rpc'

/**
 * Composable for subscribing to RPC events within a Vue component lifecycle.
 * Automatically unsubscribes on component unmount.
 */
export function useRpcEvent(event: string, handler: (...args: any[]) => void) {
  const rpc = useRpcStore()
  let unsub: (() => void) | null = null

  onMounted(() => {
    if (rpc.client) {
      unsub = rpc.on(event, handler)
    }
  })

  onUnmounted(() => {
    unsub?.()
  })

  return { unsub }
}

/**
 * Composable that calls an RPC method on mount and exposes reactive state.
 */
export function useRpcCall<T = unknown>(
  method: string,
  params?: Record<string, unknown>
) {
  const rpc = useRpcStore()
  const data = ref<T | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function execute() {
    loading.value = true
    error.value = null
    try {
      data.value = await rpc.call<T>(method, params)
    } catch (e: any) {
      error.value = e.message || String(e)
      throw e
    } finally {
      loading.value = false
    }
  }

  onMounted(() => {
    if (rpc.isConnected) {
      execute()
    } else {
      const unsub = rpc.on('_state', (s: string) => {
        if (s === 'connected') {
          unsub?.()
          execute()
        }
      })
    }
  })

  return { data, loading, error, execute }
}

import { ref, onMounted, type Ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import { useErrorSink } from '@/composables/useErrorSink'

export interface UseRequestOptions {
  /** Run once on mount (after the connection is ready). Default true. */
  immediate?: boolean
  /** Route failures through the de-duped error→toast sink. Default true. */
  toastOnError?: boolean
  /** Human label for the error toast + the dedupe key, e.g. 'Failed to load channels'. */
  errorLabel?: string
}

export interface UseRequestResult<T> {
  data: Ref<T | null>
  error: Ref<string | null>
  loading: Ref<boolean>
  /** Execute with the loading flag (skeleton). Resolves to the result or null on error. */
  execute: () => Promise<T | null>
  /** Re-execute silently (no skeleton flash) — for background refresh. */
  refresh: () => Promise<T | null>
}

/**
 * Flat `{ data, error, loading }` wrapper over `rpc.call` that gates on the
 * connection and never rethrows, so views stop hand-rolling try/catch +
 * `console.warn`. Failures populate `error` (for an inline `ErrorState`) and,
 * unless disabled, raise one de-duped danger toast via `useErrorSink`.
 *
 * Modeled on `useRpcCall` (composables/useRpc.ts) but flat + auto-toast.
 */
export function useRequest<T = unknown>(
  method: string,
  params?: Record<string, unknown> | (() => Record<string, unknown> | undefined),
  options: UseRequestOptions = {},
): UseRequestResult<T> {
  const { immediate = true, toastOnError = true, errorLabel } = options
  const rpc = useRpcStore()
  const { reportError } = useErrorSink()

  const data = ref<T | null>(null) as Ref<T | null>
  const loading = ref(false)
  const error = ref<string | null>(null)

  function resolveParams(): Record<string, unknown> | undefined {
    return typeof params === 'function' ? params() : params
  }

  async function run(silent: boolean): Promise<T | null> {
    if (!silent) loading.value = true
    error.value = null
    try {
      await rpc.waitForConnection()
      const result = await rpc.call<T>(method, resolveParams())
      data.value = result
      return result
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      error.value = msg
      if (toastOnError) {
        reportError(errorLabel ? `${errorLabel}: ${msg}` : msg, errorLabel || method)
      }
      return null
    } finally {
      if (!silent) loading.value = false
    }
  }

  const execute = () => run(false)
  const refresh = () => run(true)

  onMounted(() => {
    if (immediate) void execute()
  })

  return { data, error, loading, execute, refresh }
}

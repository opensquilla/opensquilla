import { ref } from 'vue'

export interface ConfirmOptions {
  title: string
  body: string
  primaryLabel?: string
  primaryClass?: string
}

interface ConfirmRequest extends ConfirmOptions {
  primaryLabel: string
  primaryClass: string
  resolve: (value: boolean) => void
}

// Module-level singleton so any composable or component can raise a confirm
// dialog without prop drilling; the globally-mounted ConfirmModal renders the
// shared request and resolves the promise. Mirrors useToasts.
const confirmState = ref<ConfirmRequest | null>(null)

function confirm(options: ConfirmOptions): Promise<boolean> {
  // A pending request is resolved as cancelled before a new one replaces it so
  // its awaiter never hangs.
  if (confirmState.value) {
    confirmState.value.resolve(false)
  }
  return new Promise<boolean>(resolve => {
    confirmState.value = {
      title: options.title,
      body: options.body,
      primaryLabel: options.primaryLabel ?? 'Confirm',
      primaryClass: options.primaryClass ?? 'btn--danger',
      resolve,
    }
  })
}

function resolveConfirm(ok: boolean) {
  const request = confirmState.value
  if (!request) return
  confirmState.value = null
  request.resolve(ok)
}

export function useConfirm() {
  return { confirm, confirmState, resolveConfirm }
}

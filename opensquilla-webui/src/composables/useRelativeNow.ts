import { getCurrentScope, onScopeDispose, ref } from 'vue'

// One shared clock for every live relative timestamp in the chat. Components
// subscribe via useRelativeNow(); a single interval ticks the shared `now` ref
// so each bubble re-evaluates only its own small relative computed — the heavy
// renderedMessages computed never depends on the clock. Mirrors useCronJobs'
// ticker but coarser (30s is plenty for "Nm ago") and pauses while the tab is
// hidden so a backgrounded console does no work.

const TICK_MS = 30_000

const now = ref(Date.now())
let timer: ReturnType<typeof setInterval> | null = null
let subscribers = 0

function start(): void {
  if (timer != null) return
  if (typeof document !== 'undefined' && document.hidden) return
  timer = setInterval(() => {
    now.value = Date.now()
  }, TICK_MS)
}

function stop(): void {
  if (timer != null) {
    clearInterval(timer)
    timer = null
  }
}

function onVisibilityChange(): void {
  if (document.hidden) {
    stop()
  } else {
    now.value = Date.now() // catch up immediately on return
    if (subscribers > 0) start()
  }
}

export function useRelativeNow() {
  // Must run inside a component/effect scope so the subscriber can be released
  // on unmount. Outside one, onScopeDispose is a no-op, which would leak the
  // subscriber and timer — so we return the shared ref without subscribing.
  if (!getCurrentScope()) {
    if (import.meta.env.DEV) {
      console.warn('[useRelativeNow] must be called from a setup/effect scope; returning a static clock to avoid a leak')
    }
    return now
  }
  subscribers += 1
  if (subscribers === 1) {
    now.value = Date.now() // catch up to wall-clock when the first bubble mounts
    if (typeof document !== 'undefined') {
      document.addEventListener('visibilitychange', onVisibilityChange)
    }
    start()
  }
  onScopeDispose(() => {
    subscribers -= 1
    if (subscribers === 0) {
      stop()
      if (typeof document !== 'undefined') {
        document.removeEventListener('visibilitychange', onVisibilityChange)
      }
    }
  })
  return now
}

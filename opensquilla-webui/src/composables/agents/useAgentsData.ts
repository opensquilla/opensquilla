import { onActivated, onDeactivated, onUnmounted, computed } from 'vue'
import { useRequest } from '@/composables/useRequest'
import i18n from '@/i18n'
import type { Agent } from '@/types/agents'

const POLL_MS = 30000

interface AgentsListResponse {
  agents?: Agent[]
}

export function useAgentsData() {
  // Error state + the loading flag come from useRequest; failures surface as an
  // inline ErrorState and a single de-duped toast. `immediate: false` because the
  // view is kept-alive: onActivated (below) owns the first load too, so letting
  // useRequest also auto-fetch on mount would double-fire agents.list on first
  // paint (onMounted and onActivated both run on the first display).
  const { data, loading, error, refresh, execute } = useRequest<AgentsListResponse>(
    'agents.list',
    undefined,
    { errorLabel: i18n.global.t('console.agents.loadFailed'), immediate: false },
  )
  const agents = computed<Agent[]>(() => data.value?.agents ?? [])

  // The consuming view is kept-alive (route meta.keepAlive), so the poll must
  // bind on activation and release on deactivation — it must not keep firing
  // while the view is cached and off-screen. onActivated also runs on first
  // display; we silently re-fetch on every (re)entry so a keep-alive revisit
  // refreshes without flashing the loading state. onUnmounted is a final safety
  // net for the rare case the KeepAlive cache evicts this instance.
  let pollInterval: ReturnType<typeof setInterval> | null = null
  function teardownLive() {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  }
  onActivated(() => {
    // First visit (empty) shows the spinner via execute(); revisits refresh
    // silently so the cached list never flashes its loading state.
    void (agents.value.length === 0 ? execute() : refresh())
    pollInterval = setInterval(() => { void refresh() }, POLL_MS)
  })
  onDeactivated(teardownLive)
  onUnmounted(teardownLive)

  // `loadData` is the manual refresh (toolbar button + post-mutation reload):
  // a silent re-fetch so the populated list never flashes its loading state.
  return { agents, loading, error, loadData: refresh }
}

import { onMounted, onUnmounted, computed } from 'vue'
import { useRequest } from '@/composables/useRequest'
import type { Agent } from '@/types/agents'

interface AgentsListResponse {
  agents?: Agent[]
}

export function useAgentsData() {
  // Initial load (with the loading flag) + error state come from useRequest;
  // failures surface as an inline ErrorState and a single de-duped toast
  // instead of a swallowed console.warn.
  const { data, loading, error, refresh } = useRequest<AgentsListResponse>(
    'agents.list',
    undefined,
    { errorLabel: 'Failed to load agents' },
  )
  const agents = computed<Agent[]>(() => data.value?.agents ?? [])

  let pollInterval: ReturnType<typeof setInterval> | null = null
  onMounted(() => {
    pollInterval = setInterval(() => { void refresh() }, 30000)
  })
  onUnmounted(() => {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  })

  // `loadData` is the manual refresh (toolbar button + post-mutation reload):
  // a silent re-fetch so the populated list never flashes its loading state.
  return { agents, loading, error, loadData: refresh }
}

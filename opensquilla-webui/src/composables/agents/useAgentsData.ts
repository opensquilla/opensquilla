import { onMounted, onUnmounted, ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import type { Agent } from '@/types/agents'

interface AgentsListResponse {
  agents?: Agent[]
}

export function useAgentsData() {
  const rpc = useRpcStore()
  const agents = ref<Agent[]>([])
  let pollInterval: ReturnType<typeof setInterval> | null = null

  onMounted(() => {
    loadData()
    pollInterval = setInterval(loadData, 30000)
  })

  onUnmounted(() => {
    if (pollInterval) {
      clearInterval(pollInterval)
      pollInterval = null
    }
  })

  async function loadData() {
    try {
      await rpc.waitForConnection()
      const data = await rpc.call<AgentsListResponse>('agents.list')
      agents.value = data.agents || []
    } catch (err) {
      console.warn('Failed to load agents: ' + (err instanceof Error ? err.message : String(err)))
    }
  }

  return {
    agents,
    loadData,
  }
}

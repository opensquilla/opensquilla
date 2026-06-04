import { onMounted, onUnmounted, ref } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import {
  SESSION_LIST_VIEW,
  normalizeSessionItem,
  type SessionItem,
} from '@/composables/useSessions'
import type { RawSessionListEntry } from '@/types/rpc'

interface Agent {
  id: string
  name?: string
  model?: string
  isBuiltin?: boolean
  type?: string
}

interface AgentsListData {
  agents?: Agent[]
}

interface SessionsListData {
  sessions?: RawSessionListEntry[]
}

export function useSessionsData(setSessions: (sessions: SessionItem[]) => void) {
  const rpc = useRpcStore()
  const agentsById = ref<Map<string, Agent>>(new Map())
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
    } catch {
      return
    }

    const [sessRes, agentsRes] = await Promise.allSettled([
      rpc.call<SessionsListData>('sessions.list', { limit: 200, view: SESSION_LIST_VIEW }),
      rpc.call<AgentsListData>('agents.list'),
    ])

    if (agentsRes.status === 'fulfilled') {
      const list = agentsRes.value?.agents || []
      agentsById.value = new Map(list.map(a => [a.id, a]))
    }

    if (sessRes.status === 'fulfilled') {
      const sessions = (sessRes.value?.sessions || [])
        .map(normalizeSessionItem)
        .filter((item): item is SessionItem => !!item)
      setSessions(sessions)
    } else {
      console.warn('Failed to load sessions: ' + (sessRes.reason?.message || 'unknown error'))
    }
  }

  return {
    agentsById,
    loadData,
  }
}

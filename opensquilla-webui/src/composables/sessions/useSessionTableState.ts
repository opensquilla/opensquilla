import { computed, ref } from 'vue'
import { sessionMatches, type SessionItem } from '@/composables/useSessions'

export type SessionSortColumn = 'title' | 'groupLabel' | 'updatedAt' | 'messageCount'

export function useSessionTableState() {
  const allSessions = ref<SessionItem[]>([])
  const filtered = ref<SessionItem[]>([])
  const sortCol = ref<SessionSortColumn>('updatedAt')
  const sortAsc = ref(false)
  const page = ref(0)
  const pageSize = ref(25)
  const selected = ref<Set<string>>(new Set())
  const searchVal = ref('')
  const searchInput = ref('')
  let searchDebounceId: ReturnType<typeof setTimeout> | null = null

  const totalPages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)))

  const slice = computed(() => {
    const tp = totalPages.value
    page.value = Math.min(page.value, tp - 1)
    return filtered.value.slice(page.value * pageSize.value, (page.value + 1) * pageSize.value)
  })

  const allOnPageSelected = computed(() => {
    return slice.value.length > 0 && slice.value.every(s => selected.value.has(s.key))
  })

  const totalSessions = computed(() => allSessions.value.length)
  const lifecycleOpen = computed(() => allSessions.value.filter(s => s.status === 'running').length)
  const activeRuns = computed(() =>
    allSessions.value.filter(s => s.runStatus === 'queued' || s.runStatus === 'running').length
  )
  const doneCount = computed(() => allSessions.value.filter(s => s.visualStatus === 'done').length)
  const failedOrTimedOut = computed(() =>
    allSessions.value.filter(s => s.visualStatus === 'failed' || s.visualStatus === 'timeout').length
  )
  const abortedCount = computed(() => allSessions.value.filter(s => s.visualStatus === 'killed').length)
  const totalMessages = computed(() =>
    allSessions.value.reduce((acc, s) => acc + (Number(s.messageCount) || 0), 0)
  )
  const distinctAgents = computed(() => {
    const agents = new Set<string>()
    allSessions.value.forEach(s => {
      if (s.effectiveAgentId && s.effectiveAgentId !== 'unknown') agents.add(s.effectiveAgentId)
    })
    return agents
  })

  function setSessions(sessions: SessionItem[]) {
    allSessions.value = sessions
    clearSelection()
    applyFilter()
  }

  function onSearchInput() {
    if (searchDebounceId !== null) clearTimeout(searchDebounceId)
    searchDebounceId = setTimeout(() => {
      searchDebounceId = null
      searchVal.value = searchInput.value.trim().toLowerCase()
      page.value = 0
      clearSelection()
      applyFilter()
    }, 180)
  }

  function applyFilter() {
    if (!searchVal.value) {
      filtered.value = [...allSessions.value]
    } else {
      const sv = searchVal.value
      filtered.value = allSessions.value.filter(s => sessionMatches(s, sv))
    }
    sortData()
  }

  function sortData() {
    filtered.value.sort((a, b) => {
      let va: string | number = a[sortCol.value] ?? ''
      let vb: string | number = b[sortCol.value] ?? ''
      if (sortCol.value === 'messageCount' || sortCol.value === 'updatedAt') {
        va = Number(va) || 0
        vb = Number(vb) || 0
      } else {
        va = String(va).toLowerCase()
        vb = String(vb).toLowerCase()
      }
      const cmp = va < vb ? -1 : va > vb ? 1 : 0
      return sortAsc.value ? cmp : -cmp
    })
  }

  function setSort(col: SessionSortColumn) {
    if (sortCol.value === col) {
      sortAsc.value = !sortAsc.value
    } else {
      sortCol.value = col
      sortAsc.value = true
    }
    sortData()
  }

  function toggleRow(key: string) {
    if (selected.value.has(key)) {
      selected.value.delete(key)
    } else {
      selected.value.add(key)
    }
  }

  function toggleSelectAll() {
    if (allOnPageSelected.value) {
      slice.value.forEach(s => selected.value.delete(s.key))
    } else {
      slice.value.forEach(s => selected.value.add(s.key))
    }
  }

  function clearSelection() {
    selected.value.clear()
  }

  return {
    allSessions,
    filtered,
    sortCol,
    sortAsc,
    page,
    pageSize,
    selected,
    searchVal,
    searchInput,
    totalPages,
    slice,
    allOnPageSelected,
    totalSessions,
    lifecycleOpen,
    activeRuns,
    doneCount,
    failedOrTimedOut,
    abortedCount,
    totalMessages,
    distinctAgents,
    setSessions,
    onSearchInput,
    setSort,
    toggleRow,
    toggleSelectAll,
    clearSelection,
  }
}

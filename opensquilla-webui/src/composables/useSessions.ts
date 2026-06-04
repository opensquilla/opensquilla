import { ref, computed } from 'vue'
import { useRpcStore } from '@/stores/rpc'
import type { RawSessionItem, RawSessionListEntry, SessionsListResponse } from '@/types/rpc'

export const SESSION_LIST_VIEW = 'session-list-v1'

export type { RawSessionItem } from '@/types/rpc'

export interface SessionItem {
  key: string
  title: string
  subtitle: string
  groupLabel: string
  effectiveAgentId: string
  sessionKind: string
  surface: string
  conversationKind: string
  threadLabel: string
  channelContext: { name?: string; id?: string; accountId?: string; threadId?: string } | null
  status: string
  visualStatus: string
  runStatus: string
  runLabel: string
  messageCount: number | null
  updatedAt: number
  interactive: boolean
  contractGaps: string[]
  raw: RawSessionItem
}

export interface SessionGroup {
  label: string
  items: SessionItem[]
  updatedAt: number
}

function hasOwn(obj: unknown, field: string): boolean {
  return !!obj && Object.prototype.hasOwnProperty.call(obj, field)
}

export function itemKey(item: unknown): string {
  if (typeof item === 'string') return item
  const row = item && typeof item === 'object' ? item as RawSessionItem : null
  return row?.key || row?.session || row?.sessionKey || ''
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function numberValue(value: unknown): number | null {
  if (value == null || value === '') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function normalizeRunStatus(status: string | undefined): string {
  const value = String(status || '').toLowerCase()
  if (value === 'abandoned') return 'interrupted'
  if (value === 'killed') return 'cancelled'
  if (['succeeded', 'success', 'complete'].includes(value)) return 'idle'
  if (['queued', 'running', 'interrupted', 'failed', 'timeout', 'cancelled', 'idle'].includes(value)) return value
  return 'idle'
}

export function runStatusLabelText(status: string): string {
  const labels: Record<string, string> = {
    queued: 'Queued',
    running: 'Running',
    interrupted: 'Interrupted',
    failed: 'Failed',
    timeout: 'Timed out',
    cancelled: 'Cancelled',
    idle: 'Idle',
  }
  return labels[status] || 'Idle'
}

function terminalRunStatus(row: RawSessionItem): string {
  const lastTask = row.last_task || row.lastTask || null
  const rawStatus = lastTask?.status || row.terminal_status || row.terminalStatus || ''
  const status = normalizeRunStatus(rawStatus)
  return ['failed', 'timeout', 'cancelled', 'interrupted'].includes(status) ? status : ''
}

export function sessionRunStatus(row: RawSessionItem): string {
  const active = row.active_task || row.activeTask || null
  const activeStatus = active ? normalizeRunStatus(active.status) : ''
  const terminal = terminalRunStatus(row)
  const rawStatus = row.runStatus || row.run_status || active?.status || terminal || ''
  const runStatus = normalizeRunStatus(rawStatus)
  if (active && (activeStatus === 'queued' || activeStatus === 'running')) return activeStatus
  if (terminal) return normalizeRunStatus(terminal)
  return runStatus
}

export function sessionVisualStatus(row: Pick<SessionItem, 'status' | 'runStatus'>): string {
  if (row.runStatus === 'failed' || row.runStatus === 'timeout') return row.runStatus
  if (row.runStatus === 'cancelled' || row.runStatus === 'interrupted') return 'killed'
  return String(row.status || 'unknown').toLowerCase()
}

function fallbackTitle(row: RawSessionItem): string {
  return (
    textValue(row.display_name) ||
    textValue(row.displayName) ||
    textValue(row.subject) ||
    textValue(row.derived_title) ||
    textValue(row.derivedTitle) ||
    ''
  )
}

function keyAgentId(key: string): string {
  const parts = key.split(':')
  return parts[0] === 'agent' && parts[1] ? parts[1] : ''
}

function sourceKind(row: RawSessionItem): string {
  return textValue(row.sourceKind) || textValue(row.source_kind)
}

function channelKind(row: RawSessionItem): string {
  return textValue(row.channelKind) || textValue(row.channel_kind) || textValue(row.lastChannel) || textValue(row.last_channel)
}

function deriveConversationKind(row: RawSessionItem, key: string): string {
  const explicit = textValue(row.conversationKind)
  if (explicit) return explicit
  const source = sourceKind(row).toLowerCase()
  const channel = channelKind(row).toLowerCase()
  const chatType = (textValue(row.chatType) || textValue(row.chat_type)).toLowerCase()
  if (key.includes(':webchat:') || chatType === 'webchat' || source === 'webui' || channel === 'webchat') return 'direct'
  if (key.startsWith('cron:') || key.includes(':cron:') || source === 'cron' || channel === 'cron') return 'unknown'
  if (source === 'channel' || (!!channel && !['cli', 'subagent', 'standalone'].includes(channel))) return chatType || 'group'
  if (key.includes(':subagent:') || source === 'subagent' || channel === 'subagent') return 'internal'
  if (key.includes(':cli:') || key.includes(':standalone:') || source === 'cli' || channel === 'cli') return 'internal'
  return 'unknown'
}

function deriveSessionKind(row: RawSessionItem, key: string): string {
  const explicit = textValue(row.sessionKind)
  if (explicit) return explicit
  const source = sourceKind(row).toLowerCase()
  const channel = channelKind(row).toLowerCase()
  if (key.includes(':webchat:') || source === 'webui' || channel === 'webchat') return 'chat'
  if (key.startsWith('cron:') || key.includes(':cron:') || source === 'cron' || channel === 'cron') return 'cron'
  if (source === 'channel' || (!!channel && !['cli', 'subagent', 'standalone'].includes(channel))) return 'channel'
  if (key.includes(':subagent:') || source === 'subagent' || channel === 'subagent') return 'task'
  if (key.includes(':cli:') || key.includes(':standalone:') || source === 'cli' || channel === 'cli') return 'chat'
  return 'unknown'
}

function deriveSurface(row: RawSessionItem, key: string, sessionKind: string): string {
  const explicit = textValue(row.surface)
  if (explicit) return explicit
  const channel = channelKind(row)
  const source = sourceKind(row)
  if (sessionKind === 'chat' && key.includes(':webchat:')) return 'webchat'
  if (sessionKind === 'cron') return channel || source || 'cron'
  if (sessionKind === 'channel') return channel || source || 'channel'
  if (key.includes(':subagent:')) return 'subagent'
  if (key.includes(':cli:') || key.includes(':standalone:')) return 'cli'
  return source || channel || 'unknown'
}

function deliveryContextValue(row: RawSessionItem, field: string): string {
  const ctx = row.deliveryContext || row.delivery_context || null
  return ctx && typeof ctx === 'object' ? textValue(ctx[field]) : ''
}

function deriveGroupLabel(row: RawSessionItem, key: string, sessionKind: string, agentId: string): string {
  const explicit = textValue(row.groupLabel)
  if (explicit) return explicit
  if (sessionKind === 'chat') return agentId || keyAgentId(key) || 'main'
  if (sessionKind === 'cron') {
    return (
      textValue(row.cron?.name) ||
      textValue(row.cron?.jobId) ||
      textValue(row.cron?.id) ||
      textValue(row.subject) ||
      'Cron'
    )
  }
  if (sessionKind === 'channel') {
    const channel = channelKind(row) || 'Channel'
    const target = (
      textValue(row.lastTo) ||
      textValue(row.last_to) ||
      textValue(row.channelId) ||
      textValue(row.channel_id) ||
      deliveryContextValue(row, 'channel_id') ||
      deliveryContextValue(row, 'thread_id') ||
      textValue(row.groupId) ||
      textValue(row.group_id)
    )
    return target ? `${channel} / ${target}` : channel
  }
  return 'Operational sessions'
}

function fallbackSessionTitle(row: RawSessionItem, key: string, sessionKind: string): string {
  const semantic = fallbackTitle(row)
  if (semantic) return semantic
  if (sessionKind === 'chat') return 'New chat'
  if (sessionKind === 'cron') return textValue(row.subject) || 'Automation run'
  if (sessionKind === 'channel') return textValue(row.subject) || 'Channel conversation'
  return key || 'Untitled session'
}

function normalizeUpdatedAt(row: RawSessionItem, gaps: string[]): number {
  const contractValue = numberValue(row.updatedAt)
  if (contractValue != null) return contractValue
  gaps.push('updatedAt')
  return numberValue(row.updated_at) || 0
}

function normalizeMessageCount(row: RawSessionItem, gaps: string[]): number | null {
  const contractValue = numberValue(row.messageCount)
  if (contractValue != null) return contractValue
  gaps.push('messageCount')
  return numberValue(row.message_count) ?? numberValue(row.entry_count)
}

function normalizeEffectiveAgentId(row: RawSessionItem, gaps: string[], fallback = 'unknown'): string {
  const effective = textValue(row.effectiveAgentId)
  if (effective) return effective
  gaps.push('effectiveAgentId')
  return textValue(row.agentId) || textValue(row.agent_id) || fallback
}

function normalizeRequiredString(
  row: RawSessionItem,
  field: keyof RawSessionItem,
  fallback: string,
  gaps: string[],
): string {
  const value = textValue(row[field])
  if (value) return value
  gaps.push(String(field))
  return fallback
}

export function normalizeSessionItem(item: unknown): SessionItem | null {
  const raw: RawSessionItem = typeof item === 'string' ? { key: item } : (item || {}) as RawSessionItem
  const key = itemKey(item)
  if (!key || key === 'unknown') return null

  const gaps: string[] = []
  const derivedAgentId = textValue(raw.effectiveAgentId) || textValue(raw.agentId) || textValue(raw.agent_id) || keyAgentId(key) || 'unknown'
  const sessionKind = deriveSessionKind(raw, key)
  const conversationKind = deriveConversationKind(raw, key)
  const surface = deriveSurface(raw, key, sessionKind)
  const groupLabel = deriveGroupLabel(raw, key, sessionKind, derivedAgentId)
  const title = normalizeRequiredString(raw, 'title', fallbackSessionTitle(raw, key, sessionKind), gaps)
  const subtitle = hasOwn(raw, 'subtitle') ? textValue(raw.subtitle) : ''
  if (!hasOwn(raw, 'subtitle')) gaps.push('subtitle')
  const effectiveAgentId = normalizeEffectiveAgentId(raw, gaps, derivedAgentId)
  if (!hasOwn(raw, 'sessionKind')) gaps.push('sessionKind')
  if (!hasOwn(raw, 'surface')) gaps.push('surface')
  if (!hasOwn(raw, 'conversationKind')) gaps.push('conversationKind')
  const messageCount = normalizeMessageCount(raw, gaps)
  const updatedAt = normalizeUpdatedAt(raw, gaps)
  const status = textValue(raw.status) || 'unknown'
  if (!hasOwn(raw, 'runStatus')) gaps.push('runStatus')
  const runStatus = sessionRunStatus(raw)
  const thread = raw.thread && typeof raw.thread === 'object' ? raw.thread : null
  const threadLabel = thread?.kind && thread?.id ? `${thread.kind} ${thread.id}` : ''
  const channelContext = raw.channelContext && typeof raw.channelContext === 'object' ? raw.channelContext : null

  return {
    key,
    title,
    subtitle,
    groupLabel,
    effectiveAgentId,
    sessionKind,
    surface,
    conversationKind,
    threadLabel,
    channelContext,
    status,
    visualStatus: sessionVisualStatus({ status, runStatus }),
    runStatus,
    runLabel: runStatusLabelText(runStatus),
    messageCount,
    updatedAt,
    interactive: raw.interactive === true,
    contractGaps: Array.from(new Set(gaps)),
    raw,
  }
}

export function sessionMatches(item: SessionItem, query: string): boolean {
  const q = query.trim().toLowerCase()
  if (!q) return true
  return [
    item.title,
    item.subtitle,
    item.groupLabel,
    item.effectiveAgentId,
    item.sessionKind,
    item.surface,
    item.conversationKind,
    item.status,
    item.runStatus,
    item.raw.model,
    item.key,
  ].some(value => String(value || '').toLowerCase().includes(q))
}

export function groupSessions(items: SessionItem[]): SessionGroup[] {
  const groups = new Map<string, SessionGroup>()
  for (const item of items) {
    const label = item.groupLabel || 'Backend contract gaps'
    const existing = groups.get(label)
    if (existing) {
      existing.items.push(item)
      existing.updatedAt = Math.max(existing.updatedAt, item.updatedAt || 0)
    } else {
      groups.set(label, {
        label,
        items: [item],
        updatedAt: item.updatedAt || 0,
      })
    }
  }
  return Array.from(groups.values())
    .map(group => ({
      ...group,
      items: [...group.items].sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0)),
    }))
    .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
}

export function useSessions() {
  const rpc = useRpcStore()
  const sessionsList = ref<RawSessionListEntry[]>([])
  const sessionListError = ref(false)
  const isLoading = ref(false)

  const allSessions = computed((): SessionItem[] =>
    sessionsList.value
      .map(normalizeSessionItem)
      .filter((item): item is SessionItem => !!item)
      .sort((a, b) => (b.updatedAt || 0) - (a.updatedAt || 0))
  )

  const groupedSessions = computed((): SessionGroup[] => groupSessions(allSessions.value))

  async function loadSessions() {
    isLoading.value = true
    sessionListError.value = false
    try {
      await rpc.waitForConnection()
      const data = await rpc.call<SessionsListResponse>('sessions.list', { limit: 200, view: SESSION_LIST_VIEW })
      const raw = data?.sessions || data?.keys || []
      sessionsList.value = raw.filter(s => !!itemKey(s))
    } catch (err: unknown) {
      console.error('[useSessions] sessions.list error:', err instanceof Error ? err.message : err)
      sessionListError.value = true
    } finally {
      isLoading.value = false
    }
  }

  return {
    sessionsList,
    sessionListError,
    isLoading,
    groupedSessions,
    allSessions,
    loadSessions,
  }
}

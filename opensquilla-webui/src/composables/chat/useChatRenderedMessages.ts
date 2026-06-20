import { computed, type Ref } from 'vue'
import type {
  ChatMessage,
  ChatMessageMeta,
  ChatRenderedMessage,
  ChatRouterCell,
  ChatRouterTierConfig,
  ChatStreamTimelineItem,
  ChatTimelineSegment,
  ChatToolCall,
  ChatToolCallRenderItem,
  RawToolCallPayload,
} from '@/types/chat'
import {
  isInternalToolName,
  normalizeToolInputText,
  normalizeToolName,
  summarizeToolGroup,
  toolActionLabel,
  toolCallGroups,
  toolDisplayName,
  toolIconName,
  toolOperationKey,
  toolResultIsError,
  toolSecondaryText,
} from '@/utils/chat/toolDisplay'
import {
  normalizeRouterTextTier,
  normalizeRouterTier,
  sortRouterTiers,
} from '@/utils/chat/routerTiers'

export interface NormalizedRouterDecision extends Record<string, unknown> {
  tier: string
  model: string
  baseline_model?: string
  source?: string
  routed_tier?: string
  routed_model?: string
  routing_applied?: boolean
  fallback?: boolean
  messageId?: string
  confidence?: number
  rollout_phase?: string
}

export interface UseChatRenderedMessagesOptions {
  messages: Ref<ChatMessage[]>
  sessionKey: Ref<string>
  routerSlots: Ref<string[]>
  routerModels: Ref<Record<string, string>>
  routerTierConfigs: Ref<Record<string, ChatRouterTierConfig>>
  routerVisualEffectsEnabled: Ref<boolean>
  renderMarkdown: (text: string) => string
  stripGeneratedArtifactMarkers: (text: string) => string
  stripTimePrefix: (text: string) => string
  isSubagentCompletionMessage: (role: string, text: string, options?: ChatMessage) => boolean
}

type ChatRouterRequestKind = 'text' | 'image'

export function useChatRenderedMessages(options: UseChatRenderedMessagesOptions) {
  const renderedMessages = computed((): ChatRenderedMessage[] => {
    const result: ChatRenderedMessage[] = []
    let prevDay = ''
    let prevRole = ''
    let turnRouterIdx = -1
    let turnIdx = 0
    let turnRequestKind: ChatRouterRequestKind = 'text'

    for (let i = 0; i < options.messages.value.length; i++) {
      const msg = options.messages.value[i]
      const day = dayKey(msg.ts)

      if (day && day !== prevDay) {
        prevDay = day
        prevRole = ''
      }

      if (msg.role === 'user') {
        turnRouterIdx = -1
        turnRequestKind = routerRequestKindFromAttachments(msg.attachments)
        turnIdx++
      }

      const routerDecision = normalizeRouterDecision(msg.routerDecision || (msg.provenanceKind === 'router_decision' ? msg : null))
      if (routerDecision) {
        const stripItem = renderedRouterStrip(msg, routerDecision, turnIdx, i, undefined, turnRequestKind)
        if (stripItem) turnRouterIdx = upsertRouterStrip(result, stripItem, turnRouterIdx)
        prevRole = ''
        continue
      }

      const usageRouterDecision = routerDecisionFromUsage(msg)
      if (usageRouterDecision) {
        const stripItem = renderedRouterStrip(msg, usageRouterDecision, turnIdx, i, `${msg.messageId || i}-router`, turnRequestKind)
        if (stripItem) turnRouterIdx = upsertRouterStrip(result, stripItem, turnRouterIdx)
        prevRole = ''
      }

      const isSubagent = options.isSubagentCompletionMessage(msg.role, msg.text, msg)
      const displayRole = isSubagent ? 'subagent' : msg.role
      const roleLabel = displayRole === 'user' ? 'You' : displayRole === 'assistant' ? 'Assistant' : displayRole === 'subagent' ? 'Sub-agent' : displayRole.charAt(0).toUpperCase() + displayRole.slice(1)
      const collapsible = displayRole === 'user' || displayRole === 'assistant'
      const sameGroup = collapsible && displayRole === prevRole && day === prevDay && day !== ''
      if (collapsible) prevRole = displayRole

      const ownerKey = msg.messageId || `${msg.role}-${i}`
      result.push({
        id: `${msg.role}-${i}`,
        sourceIndex: i,
        role: msg.role,
        displayRole,
        roleLabel,
        text: msg.role === 'assistant' ? options.stripGeneratedArtifactMarkers(msg.text) : msg.text,
        timeStr: msg.ts ? relTime(msg.ts) : '',
        showHeader: !sameGroup,
        messageId: msg.messageId,
        hasAttachments: !!msg.attachments?.length,
        attachments: msg.attachments,
        toolCalls: normalizeToolCalls(msg.tool_calls),
        timelineItems: normalizeMessageTimeline(msg, ownerKey),
        artifacts: msg.artifacts,
        meta: messageMeta(msg),
        reasoning: msg.role === 'assistant' ? msg.reasoning : undefined,
        interrupted: msg.interrupted,
        provenanceKind: msg.provenanceKind,
      })
    }

    return result
  })

  function renderedRouterStrip(
    msg: ChatMessage,
    decision: NormalizedRouterDecision,
    turnIdx: number,
    index: number,
    messageId = msg.messageId,
    requestKind: ChatRouterRequestKind = 'text',
  ): ChatRenderedMessage | null {
    if (!options.routerVisualEffectsEnabled.value) return null
    const cells = routerDecisionCellsForRequest(decision, requestKind)
    if (cells.length <= 1) return null
    return {
      id: `router-turn-${turnIdx}`,
      role: 'router',
      displayRole: 'router',
      roleLabel: 'Router',
      text: '',
      timeStr: msg.ts ? relTime(msg.ts) : '',
      showHeader: false,
      sourceIndex: index,
      isRouterStrip: true,
      routerState: routerDecisionState(decision),
      routerSource: decision.source || 'none',
      routerObserve: decision.routing_applied === false,
      routerStatic: msg.restoredFromHistory === true,
      routerSettled: msg.routerSettled === true,
      gridCells: cells,
      winnerIdx: routerWinnerCellIndex(cells, decision.tier),
      messageId: messageId || `${index}-router`,
    }
  }

  function messageMeta(msg: ChatMessage): ChatMessageMeta | undefined {
    if (!msg.usage && !msg.turn_usage) return undefined
    const u = msg.usage || msg.turn_usage || {}
    const model = String(msg.model || u.model || u.routed_model || '')
    const input = Number(msg.input ?? msg.input_tokens ?? u.input_tokens ?? u.inputTokens ?? 0)
    const output = Number(msg.output ?? msg.output_tokens ?? u.output_tokens ?? u.outputTokens ?? 0)
    const cached = Number(u.cached_tokens || 0)
    const reasoning = Number(u.reasoning_tokens || 0)
    const cost = Number(u.cost_usd || 0)
    const hasTier = !!(u.routed_tier && u.routing_source && u.routing_source !== 'none')
    const turnSavedPct = typeof u.total_savings_pct === 'number' && u.total_savings_pct > 0 ? u.total_savings_pct : 0
    const hasSaved = hasTier && turnSavedPct > 0 && !u.__savings_ui_suppressed
    return {
      model,
      modelShort: model.includes('/') ? (model.split('/').pop() || model) : model,
      input,
      output,
      hasTokens: input > 0 || output > 0,
      cachedTokens: cached,
      reasoningTokens: reasoning,
      costUsd: cost,
      hasSaved,
      turnSavedPct,
      savedLabel: turnSavedPct > 0 ? `Saved ~${Math.round(turnSavedPct)}%` : 'Cost optimized',
    }
  }

  function routerDecisionCells(decision: NormalizedRouterDecision): ChatRouterCell[] {
    return routerDecisionCellsForRequest(decision, 'text')
  }

  function routerDecisionCellsForRequest(decision: NormalizedRouterDecision, requestKind: ChatRouterRequestKind): ChatRouterCell[] {
    const winnerTier = normalizeRouterTier(decision.tier)
    const configuredTiers = options.routerSlots.value.length
      ? options.routerSlots.value.map(normalizeRouterTier).filter(Boolean)
      : Object.keys(options.routerTierConfigs.value).map(normalizeRouterTier).filter(Boolean)
    if (winnerTier && !configuredTiers.includes(winnerTier)) configuredTiers.push(winnerTier)
    const sourceTiers = sortRouterTiers(configuredTiers.length ? configuredTiers : (winnerTier ? [winnerTier] : []))
    const realByModel = new Map<string, ChatRouterCell>()

    for (const tier of sourceTiers) {
      const tierConfig = routerTierConfig(tier)
      if (tier !== winnerTier && !routerTierMatchesRequestKind(tierConfig, requestKind)) continue
      const model = tierConfig.model || options.routerModels.value[tier] || (tier === winnerTier ? String(decision.model || '') : '')
      if (!model && tier !== winnerTier) continue
      const displayName = shortModelName(routerFxStripProvider(model)) || (tier === winnerTier ? 'selected model' : tier)
      const key = displayName || model || `winner:${tier}`
      const existing = realByModel.get(key)
      if (existing) {
        existing.tiers = [...(existing.tiers || []), tier]
        continue
      }
      realByModel.set(key, {
        kind: 'real',
        tier,
        tiers: [tier],
        displayName,
        model,
      })
    }

    return Array.from(realByModel.values())
      .sort((a, b) => (a.displayName || a.tier).localeCompare(b.displayName || b.tier))
  }

  function routerTierConfig(tier: string): ChatRouterTierConfig {
    const normalized = normalizeRouterTier(tier)
    return options.routerTierConfigs.value[normalized] || {
      model: options.routerModels.value[normalized] || '',
      supportsImage: false,
      imageOnly: false,
    }
  }

  function routerTierMatchesRequestKind(tierConfig: ChatRouterTierConfig, requestKind: ChatRouterRequestKind): boolean {
    if (requestKind === 'image') return tierConfig.supportsImage || tierConfig.imageOnly
    return !tierConfig.imageOnly
  }

  function normalizeMessageTimeline(msg: ChatMessage, ownerKey: string): ChatStreamTimelineItem[] {
    if (msg.role !== 'assistant') return []
    const explicitTimeline = Array.isArray(msg.timeline) ? msg.timeline : []
    if (explicitTimeline.length) {
      const calls = normalizeToolCalls(msg.tool_calls)
      return timelineFromSegments(explicitTimeline, calls, ownerKey)
    }
    const rawSegments = Array.isArray(msg.tool_calls) ? msg.tool_calls : []
    const hasPersistedTimeline = rawSegments.some(seg => ['text', 'tool_use', 'tool_result'].includes(String(seg?.type || '')))
    if (!hasPersistedTimeline) return []
    return timelineFromPersistedSegments(rawSegments, ownerKey)
  }

  function timelineFromSegments(segments: ChatTimelineSegment[], calls: ChatToolCall[], ownerKey: string): ChatStreamTimelineItem[] {
    const groupsById = new Map(toolCallGroups(calls, ownerKey).map(group => [group.groupId, group]))
    return segments.flatMap((seg, idx): ChatStreamTimelineItem[] => {
      if (seg?.type === 'text') {
        const raw = String(seg.raw ?? seg.text ?? '')
        return raw ? [{ type: 'text', key: `${ownerKey}:timeline:text:${idx}`, html: options.renderMarkdown(raw), rawText: raw }] : []
      }
      if (seg?.type === 'tool-group') {
        const groupId = String(seg.groupId || seg.group_id || '')
        const group = groupId ? groupsById.get(groupId) : null
        return group ? [{ type: 'tool-group', key: groupId, group }] : []
      }
      return []
    })
  }

  function timelineFromPersistedSegments(segments: RawToolCallPayload[], ownerKey: string): ChatStreamTimelineItem[] {
    const items: ChatStreamTimelineItem[] = []
    const callsById = new Map<string, ChatToolCall>()
    let groupSeq = 0

    const appendToolItem = (segment: RawToolCallPayload, index: number): ChatToolCall | null => {
      const name = normalizeToolName(segment)
      if (!name || isInternalToolName(name)) return null
      const toolId = String(segment.tool_use_id || segment.toolId || segment.id || `${name}:${index}`)
      let call = callsById.get(toolId)
      if (!call) {
        const operationKey = toolOperationKey(name)
        const last = items[items.length - 1]
        let group = last?.type === 'tool-group' && last.group.operationKey === operationKey
          ? last.group
          : null
        if (!group) {
          group = {
            groupId: `${ownerKey}:timeline:tool-group:${operationKey}:${groupSeq++}`,
            operationKey,
            label: toolActionLabel(name),
            iconName: toolIconName(name),
            calls: [],
            secondary: '',
            isRunning: false,
            isError: false,
            status: '',
          }
          items.push({ type: 'tool-group', key: group.groupId, group })
        }
        const input = normalizeToolInputText(segment)
        call = {
          toolId,
          name,
          displayName: toolDisplayName(name, input),
          groupId: group.groupId,
          inputRaw: input,
          inputPreview: truncate(input, 200),
          isRunning: false,
          status: '',
          isError: false,
          result: '',
          resultPreview: '',
          isOpen: false,
          renderKey: `${ownerKey}:tool:${toolId}:${group.calls.length}`,
        } as ChatToolCallRenderItem
        group.calls.push(call as ChatToolCallRenderItem)
        callsById.set(toolId, call)
      }
      return call
    }

    segments.forEach((segment, index) => {
      const type = String(segment?.type || '')
      if (type === 'text') {
        const raw = String(segment.text || segment.raw || '')
        if (raw) items.push({ type: 'text', key: `${ownerKey}:timeline:text:${index}`, html: options.renderMarkdown(raw), rawText: raw })
        return
      }
      if (type === 'tool_use') {
        appendToolItem(segment, index)
        return
      }
      if (type === 'tool_result') {
        const call = appendToolItem(segment, index)
        if (!call) return
        const result = segment.result || segment.content || segment.output || ''
        const resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
        const input = normalizeToolInputText(segment)
        if (input && !call.inputPreview) {
          call.inputRaw = input
          call.inputPreview = truncate(input, 200)
          call.displayName = toolDisplayName(call.name, input)
        }
        call.isRunning = false
        call.isError = toolResultIsError(segment)
        call.status = call.isError ? 'error' : 'success'
        call.result = resultStr
        call.resultPreview = truncate(resultStr, 200)
        if (segment.sources !== undefined) call.sources = segment.sources
      }
    })

    for (const item of items) {
      if (item.type !== 'tool-group') continue
      item.group.isRunning = item.group.calls.some(tc => tc.isRunning)
      item.group.isError = item.group.calls.some(tc => tc.isError || tc.status === 'error')
      item.group.status = item.group.isError ? 'error' : (item.group.calls.every(tc => tc.status === 'success') ? 'success' : '')
      item.group.secondary = item.group.calls.length === 1
        ? toolSecondaryText(item.group.calls[0])
        : summarizeToolGroup(item.group.calls)
    }

    return items
  }

  return {
    renderedMessages,
    normalizeRouterDecision,
    routerDecisionCells,
    routerWinnerCellIndex,
    routerDecisionState,
    shortModelName,
    routerFxSortTiers,
  }
}

function upsertRouterStrip(
  result: ChatRenderedMessage[],
  stripItem: ChatRenderedMessage,
  previousIndex: number,
): number {
  if (previousIndex >= 0) {
    stripItem.routerSettled = true
    result[previousIndex] = stripItem
    return previousIndex
  }
  result.push(stripItem)
  return result.length - 1
}

function routerRequestKindFromAttachments(attachments: ChatMessage['attachments']): ChatRouterRequestKind {
  return attachments?.some(att => String(att.mime || '').toLowerCase().startsWith('image/'))
    ? 'image'
    : 'text'
}

export function relTime(ts: string | number | null): string {
  if (!ts) return ''
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'just now'
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`
  return `${Math.floor(diff / 86400)}d ago`
}

export function fmtTok(n: number): string {
  if (!n) return '0'
  if (n >= 1_000_000) return `${+(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${+(n / 1_000).toFixed(1)}k`
  return String(n)
}

export function dayKey(ts: string | number | null): string {
  if (!ts) return ''
  const d = typeof ts === 'number' ? new Date(ts) : new Date(ts)
  if (isNaN(d.getTime())) return ''
  return d.toISOString().slice(0, 10)
}

export function truncate(s: string, max = 200): string {
  if (!s || s.length <= max) return s || ''
  return s.slice(0, max) + '…'
}

export function normalizeRouterDecision(raw: unknown): NormalizedRouterDecision | null {
  if (!raw || typeof raw !== 'object') return null
  const source = raw as Record<string, unknown>
  const rawTier = String(source.tier || source.routed_tier || '').trim()
  const tier = normalizeRouterTextTier(rawTier) || normalizeRouterTier(rawTier)
  if (!tier) return null
  return {
    ...source,
    tier,
    model: String(source.model || source.routed_model || ''),
    baseline_model: String(source.baseline_model || source.baselineModel || ''),
  }
}

function routerDecisionFromUsage(msg: ChatMessage): NormalizedRouterDecision | null {
  const usage = msg.usage || msg.turn_usage
  if (!usage || usage.routing_source === 'none') return null
  const tier = typeof usage.routed_tier === 'string' ? usage.routed_tier : ''
  if (!tier) return null
  return normalizeRouterDecision({
    tier,
    model: usage.routed_model || usage.model || msg.model || '',
    source: usage.routing_source || 'none',
    confidence: typeof usage.routing_confidence === 'number' ? usage.routing_confidence : 0,
    fallback: usage.routing_source === 'fallback',
    routing_applied: usage.routing_applied !== false,
    rollout_phase: usage.rollout_phase || 'full',
  })
}

export function routerDecisionState(decision: NormalizedRouterDecision): string {
  if (decision.routing_applied === false) return 'observe'
  if (decision.fallback) return 'fallback'
  return 'settled'
}

export function shortModelName(model: string): string {
  const raw = String(model || '').trim()
  if (!raw) return ''
  const last = raw.includes('/') ? raw.split('/').pop() || raw : raw
  return last
}

function routerFxStripProvider(name: string): string {
  const raw = String(name || '').trim()
  if (!raw) return ''
  const idx = raw.lastIndexOf('/')
  return idx >= 0 ? raw.slice(idx + 1) : raw
}

export function routerFxSortTiers(list: string[]): string[] {
  return sortRouterTiers(list)
}

export function routerWinnerCellIndex(cells: ChatRouterCell[], tier: string): number {
  const norm = normalizeRouterTier(tier)
  return cells.findIndex(cell => cell.kind === 'real' && (cell.tiers || []).includes(norm))
}

function normalizeToolCalls(raw: RawToolCallPayload[] | undefined): ChatToolCall[] {
  if (!raw || !Array.isArray(raw)) return []
  const merged: ChatToolCall[] = []
  const byId = new Map<string, ChatToolCall>()

  raw.forEach((tc, index) => {
    const name = normalizeToolName(tc)
    if (!name) return
    if (isInternalToolName(name)) return
    const input = normalizeToolInputText(tc)
    const result = tc.result || tc.content || tc.output || ''
    const resultStr = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
    const executionStatus = String(tc.execution_status?.status || '')
    const isError = !!(tc.is_error || tc.isError || tc.error || ['error', 'timeout', 'cancelled'].includes(executionStatus))
    const toolId = String(tc.tool_use_id || tc.toolId || tc.id || `${name}:${index}`)
    let item = byId.get(toolId)
    if (!item) {
      item = {
        toolId,
        name,
        displayName: toolDisplayName(name, input),
        groupId: tc.groupId || tc.group_id,
        inputRaw: input,
        inputPreview: '',
        isRunning: false,
        status: '' as '' | 'success' | 'error',
        isError: false,
        result: '',
        resultPreview: '',
        sources: undefined,
        isOpen: false,
      }
      byId.set(toolId, item)
      merged.push(item)
    }
    if (!item.inputPreview && input) {
      item.inputRaw = input
      item.inputPreview = truncate(input, 200)
      item.displayName = toolDisplayName(item.name, input)
    }
    if (resultStr) {
      item.result = resultStr
      item.resultPreview = truncate(resultStr, 200)
      item.status = isError ? 'error' : 'success'
    }
    if (tc.sources !== undefined) item.sources = tc.sources
    if (isError) {
      item.isError = true
      item.status = 'error'
    }
  })

  return merged.map(item => ({
    toolId: item.toolId,
    name: item.name,
    displayName: item.displayName,
    groupId: item.groupId,
    inputRaw: item.inputRaw,
    inputPreview: item.inputPreview,
    isRunning: item.isRunning,
    status: item.status,
    isError: item.isError,
    result: item.result,
    resultPreview: item.resultPreview,
    sources: item.sources,
    isOpen: false,
  }))
}

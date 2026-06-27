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
import type { RouterVisualMode } from '@/utils/chat/routerVisualMode'
import { toParts, toolState } from '@/utils/chat/toParts'
import { toSources } from '@/utils/chat/toSources'
import { relativeTime } from '@/utils/messageTime'

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
  routerVisualMode: Ref<RouterVisualMode>
  renderMarkdown: (text: string) => string
  stripGeneratedArtifactMarkers: (text: string) => string
  stripTimePrefix: (text: string) => string
  isSubagentCompletionMessage: (role: string, text: string, options?: ChatMessage) => boolean
}

type ChatRouterRequestKind = 'text' | 'image'

const ROUTER_LEGACY_GRID_CELLS = 15
const ROUTER_LEGACY_REAL_ANCHORS = [1, 6, 8, 13, 11, 3, 5, 9, 12, 14, 0, 4, 7, 10, 2]
const ROUTER_LEGACY_DECOY_MODELS = [
  'gpt-5.5',
  'claude-opus-4.8',
  'gemini-3.5-flash',
  'qwen3-coder-plus',
  'grok-4.3',
  'gpt-5.4-mini',
  'claude-sonnet-4.6',
  'gemini-3.1-pro',
  'deepseek-v3.2',
  'kimi-k2.6',
  'command-a-plus',
  'grok-build-0.1',
  'glm-4.6',
  'mistral-medium-3.5',
  'claude-haiku-4.5',
]

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
      const rendered: ChatRenderedMessage = {
        id: `${msg.role}-${i}`,
        sourceIndex: i,
        role: msg.role,
        displayRole,
        roleLabel,
        text: msg.role === 'assistant' ? options.stripGeneratedArtifactMarkers(msg.text) : msg.text,
        timeStr: relativeTime(msg.ts),
        ts: msg.ts ?? null,
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
      }
      // Additive: derive discriminated parts from the finished rendered
      // object so they cannot drift from the fields the components read. Only
      // assistant turns fold a parts body; other roles render through the
      // ChatMessageList role branch and stay parts:[].
      rendered.parts = rendered.displayRole === 'assistant'
        ? toParts(rendered, options.renderMarkdown, toolCallGroups, ownerKey)
        : []
      rendered.sources = rendered.displayRole === 'assistant' ? toSources(rendered) : []
      // statusHistory is a stored snapshot (not re-derivable from tool_calls), so
      // read it straight off the message for assistant turns. A reloaded thread
      // has no snapshot → []; non-assistant roles stay [] like parts/sources.
      rendered.statusHistory = rendered.displayRole === 'assistant'
        ? (msg.statusHistory ?? [])
        : []
      if (import.meta.env.DEV && rendered.displayRole === 'assistant') {
        assertPartsParity(rendered, ownerKey)
      }
      result.push(rendered)
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
      timeStr: relativeTime(msg.ts),
      ts: msg.ts ?? null,
      showHeader: false,
      sourceIndex: index,
      isRouterStrip: true,
      routerState: routerDecisionState(decision),
      routerSource: decision.source || 'none',
      routerObserve: decision.routing_applied === false,
      routerStatic: msg.restoredFromHistory === true,
      routerSettled: msg.routerSettled === true,
      routerPanel: routerPanelDataset(options.routerVisualMode.value),
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
    const realCells = realRouterDecisionCellsForRequest(decision, requestKind)
    if (realCells.length <= 1 || options.routerVisualMode.value !== 'legacy_grid') return realCells
    return legacyRouterGridCells(realCells)
  }

  function realRouterDecisionCellsForRequest(decision: NormalizedRouterDecision, requestKind: ChatRouterRequestKind): ChatRouterCell[] {
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

  function legacyRouterGridCells(realCells: ChatRouterCell[]): ChatRouterCell[] {
    const cells = Array.from({ length: ROUTER_LEGACY_GRID_CELLS }, (_, index): ChatRouterCell => ({
      kind: 'decoy',
      tier: '',
      tiers: [],
      displayName: ROUTER_LEGACY_DECOY_MODELS[index % ROUTER_LEGACY_DECOY_MODELS.length],
      model: '',
    }))
    realCells.slice(0, ROUTER_LEGACY_GRID_CELLS).forEach((cell, index) => {
      cells[ROUTER_LEGACY_REAL_ANCHORS[index] ?? index] = cell
    })
    return cells
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

/**
 * DEV-only soft parity check: confirms the derived `parts[]` cover exactly what
 * the assistant message components render today (text, tools, artifacts,
 * reasoning) and that tool keys/state match their originating calls. Logs
 * console.error on any mismatch and NEVER throws, so it is invisible in
 * production and only surfaces fold regressions during `npm run dev` / e2e.
 */
function assertPartsParity(rendered: ChatRenderedMessage, ownerKey: string): void {
  try {
    const parts = rendered.parts ?? []
    const problems: string[] = []

    // (1) text/timeline coverage
    const textPartKeys = new Set(parts.filter(p => p.type === 'text').map(p => p.key))
    if (rendered.timelineItems?.length) {
      const timelineTextKeys = new Set(
        rendered.timelineItems.filter(item => item.type === 'text').map(item => item.key),
      )
      if (!sameSet(textPartKeys, timelineTextKeys)) {
        problems.push(`text keys diverge from timeline: parts=${[...textPartKeys].join(',')} timeline=${[...timelineTextKeys].join(',')}`)
      }
    } else {
      const expectsText = !!rendered.text
      const hasTextPart = textPartKeys.has(`${ownerKey}:text`)
      if (expectsText !== hasTextPart) {
        problems.push(`plain text part presence ${hasTextPart} != text non-empty ${expectsText}`)
      }
    }

    // (2) tool coverage — callIds + keys vs the originating calls
    const expectedCalls: ChatToolCallRenderItem[] = rendered.timelineItems?.length
      ? rendered.timelineItems.flatMap(item => (item.type === 'tool-group' ? item.group.calls : []))
      : toolCallGroups(rendered.toolCalls, ownerKey).flatMap(g => g.calls)
    const expectedToolKeys = multiset(expectedCalls.map(call => call.renderKey))
    const toolParts = parts.filter(p => p.type === 'tool')
    const actualToolKeys = multiset(toolParts.map(p => p.key))
    if (!sameMultiset(expectedToolKeys, actualToolKeys)) {
      problems.push('tool part keys diverge from originating call renderKeys')
    }
    const callByKey = new Map(expectedCalls.map(call => [call.renderKey, call]))
    for (const part of toolParts) {
      if (part.type !== 'tool') continue
      const call = callByKey.get(part.key)
      if (!call) continue
      if (part.callId !== call.toolId) problems.push(`tool callId ${part.callId} != ${call.toolId}`)
      if (part.state !== toolState(call)) problems.push(`tool state ${part.state} != ${toolState(call)} for ${part.key}`)
    }

    // (3) artifact coverage
    const artifactParts = parts.filter(p => p.type === 'artifact').length
    if (artifactParts !== (rendered.artifacts?.length ?? 0)) {
      problems.push(`artifact parts ${artifactParts} != artifacts ${rendered.artifacts?.length ?? 0}`)
    }

    // (4) reasoning coverage
    const reasoningParts = parts.filter(p => p.type === 'reasoning').length
    const expectedReasoning = rendered.reasoning ? 1 : 0
    if (reasoningParts !== expectedReasoning) {
      problems.push(`reasoning parts ${reasoningParts} != expected ${expectedReasoning}`)
    }

    // (5) source coverage — folded list stays consistent and within the cap
    const sources = rendered.sources ?? []
    if (sources.length > 12) problems.push(`sources ${sources.length} exceeds MAX_SOURCES`)
    sources.forEach((source, index) => {
      if (source.sourceId !== index + 1) problems.push(`source ${index} has sourceId ${source.sourceId}`)
    })

    if (problems.length) {
      console.error('[live-turn parity]', { id: rendered.id, messageId: rendered.messageId, problems })
    }
  } catch (err) {
    console.error('[live-turn parity]', { id: rendered.id, error: String(err) })
  }
}

function sameSet(a: Set<string>, b: Set<string>): boolean {
  if (a.size !== b.size) return false
  for (const value of a) if (!b.has(value)) return false
  return true
}

function multiset(values: string[]): Map<string, number> {
  const map = new Map<string, number>()
  for (const value of values) map.set(value, (map.get(value) ?? 0) + 1)
  return map
}

function sameMultiset(a: Map<string, number>, b: Map<string, number>): boolean {
  if (a.size !== b.size) return false
  for (const [key, count] of a) if (b.get(key) !== count) return false
  return true
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

export function routerPanelDataset(mode: RouterVisualMode): string {
  return mode === 'legacy_grid' ? 'legacy-grid' : 'real-candidates'
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

import type { ArtifactPayload } from './rpc'
import type { IconName } from '@/utils/icons'

export interface Attachment {
  kind: 'inline' | 'staged' | 'inline_pending' | 'uploading'
  local_id: number
  name: string
  mime: string
  size?: number
  data?: string
  dataUrl?: string
  file_uuid?: string
}

export interface ChatPendingItem {
  text: string
  attachments: Attachment[]
  intent: string | null
}

export interface ChatRouterCell {
  kind: 'real' | 'decoy'
  tier?: string
  tiers?: string[]
  displayName: string
}

export interface ChatToolCall {
  toolId: string
  name: string
  displayName: string
  groupId?: string
  inputRaw?: string
  inputPreview: string
  isRunning: boolean
  status: '' | 'success' | 'error'
  isError: boolean
  result: string
  resultPreview: string
  isOpen: boolean
}

export type ChatToolCallRenderItem = ChatToolCall & {
  renderKey: string
}

export interface ChatToolCallGroup {
  groupId: string
  operationKey: string
  label: string
  iconName: IconName
  calls: ChatToolCallRenderItem[]
  secondary: string
  isRunning: boolean
  isError: boolean
  status: '' | 'success' | 'error'
}

export interface ChatStreamSegment {
  type: 'text' | 'tool-group'
  raw?: string
  html?: string
  dirty?: boolean
  groupId?: string
  operationKey?: string
}

export type ChatStreamTimelineItem =
  | { type: 'text'; key: string; html: string }
  | { type: 'tool-group'; key: string; group: ChatToolCallGroup }

export type ChatRole = 'user' | 'assistant' | 'system' | 'error' | 'router' | string

export type ChatRunStatusState =
  | 'idle'
  | 'queued'
  | 'running'
  | 'interrupted'
  | 'failed'
  | 'timeout'
  | 'cancelled'

export interface ChatRunTask {
  status?: string
  task_id?: string
  taskId?: string
  terminal_reason?: string
  terminalReason?: string
}

export interface ChatRunStatus {
  status: ChatRunStatusState
  label: string
  task: ChatRunTask | null
}

export interface ChatRunStatusSource {
  run_status?: string
  runStatus?: string
  active_task?: ChatRunTask | null
  activeTask?: ChatRunTask | null
  last_task?: ChatRunTask | null
  lastTask?: ChatRunTask | null
}

export interface RawToolCallPayload extends Record<string, unknown> {
  type?: string
  id?: string
  toolId?: string
  tool_use_id?: string
  name?: string
  tool_name?: string
  input?: unknown
  result?: unknown
  content?: unknown
  output?: unknown
  is_error?: boolean
  isError?: boolean
  error?: unknown
  execution_status?: { status?: string }
  groupId?: string
  group_id?: string
}

export interface ChatTimelineSegment extends Record<string, unknown> {
  type?: string
  raw?: string
  text?: string
  groupId?: string
  group_id?: string
}

export interface ChatUsagePayload {
  model?: string
  routed_model?: string
  input_tokens?: number
  inputTokens?: number
  output_tokens?: number
  outputTokens?: number
  cached_tokens?: number
  reasoning_tokens?: number
  cost_usd?: number
  routed_tier?: string
  routing_source?: string
  total_savings_pct?: number
  __savings_ui_suppressed?: boolean
  [key: string]: unknown
}

export interface ChatMessage {
  role: ChatRole
  text: string
  ts: string | number | null
  routerDecision?: import('./rpc').RouterDecisionPayload | null
  artifacts?: ArtifactPayload[]
  tool_calls?: RawToolCallPayload[]
  timeline?: ChatTimelineSegment[]
  attachments?: Attachment[]
  provenanceKind?: string
  provenanceSourceSessionKey?: string
  provenanceSourceTool?: string
  interrupted?: boolean
  routerSettled?: boolean
  messageId?: string
  usage?: ChatUsagePayload
  turn_usage?: ChatUsagePayload
  model?: string
  input?: number
  input_tokens?: number
  output?: number
  output_tokens?: number
  restoredFromHistory?: boolean
}

export interface ChatMessageMeta {
  model: string
  modelShort: string
  input: number
  output: number
  hasTokens: boolean
  cachedTokens: number
  reasoningTokens: number
  costUsd: number
  hasSaved: boolean
  savedLabel: string
  turnSavedPct?: number
}

export interface ChatRenderedMessage {
  id?: string
  sourceIndex?: number
  role: string
  displayRole: string
  roleLabel: string
  text: string
  timeStr: string
  showHeader: boolean
  isStreaming?: boolean
  messageId?: string
  hasAttachments?: boolean
  attachments?: Attachment[]
  toolCalls?: ChatToolCall[]
  timelineItems?: ChatStreamTimelineItem[]
  artifacts?: ArtifactPayload[]
  meta?: ChatMessageMeta
  interrupted?: boolean
  provenanceKind?: string
  daySeparator?: boolean
  dayLabel?: string
  isRouterStrip?: boolean
  routerState?: string
  routerSource?: string
  routerObserve?: boolean
  routerStatic?: boolean
  routerSettled?: boolean
  gridCells?: ChatRouterCell[]
  winnerIdx?: number
}

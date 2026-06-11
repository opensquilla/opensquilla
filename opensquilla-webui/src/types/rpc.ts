import type { Attachment } from './chat'

export interface AgentOption {
  id: string
  name: string
  model?: string
}

export interface AgentsListResponse {
  agents?: Array<{
    id?: string
    agentId?: string
    name?: string
    model?: string
  }>
}

export interface RawSessionThread {
  id?: string
  kind?: string
}

export interface RawSessionChannelContext {
  name?: string
  id?: string
  accountId?: string
  threadId?: string
}

export interface RawSessionTask {
  status?: string
}

export interface RawSessionCron {
  id?: string
  jobId?: string
  job_id?: string
  name?: string
}

export interface RawSessionItem {
  key?: string
  session?: string
  sessionKey?: string
  sessionId?: string
  agentId?: string
  agent_id?: string
  effectiveAgentId?: string
  sessionKind?: string
  surface?: string
  conversationKind?: string
  thread?: RawSessionThread | null
  channelContext?: RawSessionChannelContext | null
  title?: string
  subtitle?: string
  groupLabel?: string
  updatedAt?: number | string
  updated_at?: number | string
  messageCount?: number
  message_count?: number
  entry_count?: number
  status?: string
  runStatus?: string
  run_status?: string
  active_task?: RawSessionTask
  activeTask?: RawSessionTask
  last_task?: RawSessionTask
  lastTask?: RawSessionTask
  terminal_status?: string
  terminalStatus?: string
  display_name?: string
  displayName?: string
  subject?: string
  derived_title?: string
  derivedTitle?: string
  source_kind?: string
  sourceKind?: string
  channel_kind?: string
  channelKind?: string
  channel_id?: string
  channelId?: string
  chat_type?: string
  chatType?: string
  group_id?: string
  groupId?: string
  last_channel?: string
  lastChannel?: string
  last_to?: string
  lastTo?: string
  last_account_id?: string
  lastAccountId?: string
  last_thread_id?: string
  lastThreadId?: string
  delivery_context?: Record<string, unknown>
  deliveryContext?: Record<string, unknown>
  origin?: Record<string, unknown>
  interactive?: boolean
  model?: string
  channel?: Record<string, unknown>
  parent?: Record<string, unknown>
  cron?: RawSessionCron
}

export type RawSessionListEntry = RawSessionItem | string

export interface SessionsListResponse {
  sessions?: RawSessionListEntry[]
  keys?: RawSessionListEntry[]
}

export interface ArtifactPayload {
  id?: string
  key?: string
  session_key?: string
  sessionKey?: string
  epoch?: number
  stream_seq?: number
  name?: string
  mime?: string
  size?: number | string
  download_url?: string
  [key: string]: unknown
}

export interface SessionEventPayload {
  key?: string
  session_key?: string
  sessionKey?: string
  epoch?: number
  stream_seq?: number
  reason?: string
  status?: string
  run_status?: string
  runStatus?: string
  terminal_message?: string
  message?: string
  code?: string
  group_id?: string
  to_state?: string
  toState?: string
  active_task?: RawSessionTask
  last_task?: RawSessionTask
  [key: string]: unknown
}

export interface TextDeltaPayload extends SessionEventPayload {
  text?: string
}

export interface ToolUsePayload extends SessionEventPayload {
  id?: string
  toolId?: string
  tool_use_id?: string
  toolUseId?: string
  tool_id?: string
  name?: string
  tool_name?: string
  input?: unknown
  input_delta?: string
  inputDelta?: string
  json_fragment?: string
  jsonFragment?: string
  fragment?: string
}

export interface ToolDeltaPayload extends ToolUsePayload {
  delta?: string
  input_delta?: string
}

export interface ToolResultPayload extends ToolUsePayload {
  result?: unknown
  content?: unknown
  output?: unknown
  error?: unknown
  is_error?: boolean
  isError?: boolean
  execution_status?: { status?: string }
  executionStatus?: { status?: string }
}

export interface SessionMessagesSubscribeParams {
  key: string
  since_stream_seq?: number
  [key: string]: unknown
}

export interface SessionMessagesSubscribeResponse extends SessionEventPayload {
  subscribed?: boolean
  replay_complete?: boolean
  current_stream_seq?: number
}

export interface ChatSendAttachmentPayload {
  type: string
  mime: string
  name: string
  data?: string
  file_uuid?: string
}

export interface ChatSendParams {
  message: string
  sessionKey: string
  _source?: { elevated?: string }
  intent?: string
  displayText?: string
  attachments?: ChatSendAttachmentPayload[]
  [key: string]: unknown
}

export interface ChatSendResponse {
  sessionKey?: string
}

export interface ChatHistoryMessage {
  role?: string
  text?: string
  timestamp?: string | number | null
  ts?: string | number | null
  id?: string
  message_id?: string
  attachments?: Attachment[]
  artifacts?: ArtifactPayload[]
  router_decision?: RouterDecisionPayload | null
  routerDecision?: RouterDecisionPayload | null
  tool_calls?: unknown[]
  timeline?: unknown[]
  provenance_kind?: string
  provenance_source_session_key?: string
  provenance_source_tool?: string
  reasoning_content?: string
  usage?: unknown
  turn_usage?: unknown
  model?: string
  input?: number
  input_tokens?: number
  output?: number
  output_tokens?: number
}

export interface ChatHistoryResponse {
  messages?: ChatHistoryMessage[]
  has_more?: boolean
  hasMore?: boolean
  oldest_cursor?: string | number | null
  oldestCursor?: string | number | null
  newest_cursor?: string | number | null
  newestCursor?: string | number | null
  history_scope?: string
  historyScope?: string
  limit?: number
  returned?: number
}

export interface RouterDecisionPayload extends SessionEventPayload {
  tier?: string
  model?: string
  routed_model?: string
  source?: string
  routing_applied?: boolean
  decision?: unknown
}

export interface CompactionPayload extends SessionEventPayload {
  compacted?: boolean
  detail?: string
}

export interface RpcEventMap {
  'session.event.text_delta': TextDeltaPayload
  'session.event.tool_use_start': ToolUsePayload
  'session.event.tool_use_delta': ToolDeltaPayload
  'session.event.tool_result': ToolResultPayload
  'session.event.artifact': ArtifactPayload
  'session.event.router_decision': RouterDecisionPayload
  'session.event.router_control_replay': SessionEventPayload
  'session.event.state_change': SessionEventPayload
  'session.event.run_heartbeat': SessionEventPayload
  'session.event.compaction': CompactionPayload
  'session.event.warning': SessionEventPayload
  'session.epoch_changed': SessionEventPayload
  'sessions.changed': SessionEventPayload
  'task.queued': SessionEventPayload
  'task.running': SessionEventPayload
  'session.event.task_group.waiting': SessionEventPayload
  'session.event.task_group.synthesizing': SessionEventPayload
  'session.event.task_group.done': SessionEventPayload
  'session.event.task_group.failed': SessionEventPayload
}

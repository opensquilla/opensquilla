export interface SessionRow {
  session?: string
  sessionKey?: string
  key?: string
  updated_at?: number | string
  updatedAt?: number | string
  endedAt?: number | string
  ended_at?: number | string
  startedAt?: number | string
  started_at?: number | string
  createdAt?: number | string
  created_at?: number | string
  input_tokens?: number | string
  inputTokens?: number | string
  output_tokens?: number | string
  outputTokens?: number | string
  cache_read_tokens?: number | string
  cacheReadTokens?: number | string
  cache_write_tokens?: number | string
  cacheWriteTokens?: number | string
  cost_usd?: number | string
  costUsd?: number | string
  cost_source?: string
  costSource?: string
  cost_ephemeral?: boolean
  costEphemeral?: boolean
  model?: string
  modelBreakdown?: ModelBreakdownItem[]
  [key: string]: unknown
}

export interface ModelBreakdownItem {
  model?: string
  inputTokens?: number | string
  input_tokens?: number | string
  outputTokens?: number | string
  output_tokens?: number | string
  costUsd?: number | string
  cost_usd?: number | string
  costSource?: string
  cost_source?: string
  costEphemeral?: boolean
  cost_ephemeral?: boolean
  [key: string]: unknown
}

export interface UsageStatusData {
  sessions?: SessionRow[]
  totalSessions?: number
  totalTokens?: number
  totalCostUsd?: number
}

export interface TableColumn {
  key: string
  label: string
}

export interface ChartRow {
  sessionKey: string
  label: string
  inputPct: number
  outputPct: number
  totalPct: number
  valueLabel: string
}

export interface ModelCard {
  model: string
  provider: string
  name: string
  inputTokens: number
  outputTokens: number
  cacheReadTokens: number
  cacheWriteTokens: number
  costUsd: number
  sessions: number
  share: number
  totalTokens: number
}

export interface BreakdownRow {
  model: string
  provider: string
  name: string
  tokens: number
  cost: number
  share: number
  costSource?: string
  cost_source?: string
  costEphemeral?: boolean
  cost_ephemeral?: boolean
}

export interface UsageTotals {
  input: number
  output: number
  cost: number
  cacheRead: number
  cacheWrite: number
  sessions: number
}

export interface SortedRow {
  raw: SessionRow
  sessionKey: string
  modified: string
  inputTokens: number | null
  outputTokens: number | null
  cacheReadTokens: number | null
  cacheWriteTokens: number | null
  cost: number | null
  hasModelBreakdown: boolean
}

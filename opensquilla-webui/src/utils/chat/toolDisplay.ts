import type {
  ChatToolCall,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
} from '@/types/chat'
import type { IconName } from '@/utils/icons'

function truncateToolText(text: string, max = 200): string {
  if (!text || text.length <= max) return text || ''
  return text.slice(0, max) + '…'
}

function parseToolInput(input: unknown): Record<string, unknown> | null {
  if (typeof input !== 'string') {
    return input && typeof input === 'object' ? input as Record<string, unknown> : null
  }
  try {
    const parsed = JSON.parse(input)
    return parsed && typeof parsed === 'object' ? parsed as Record<string, unknown> : null
  } catch {
    return null
  }
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' ? value as Record<string, unknown> : null
}

export function isEmptyToolPreview(text: string): boolean {
  const value = String(text || '').trim()
  return !value || value === '""' || value === "''" || value === '{}' || value === '[]'
}

export function truncateToolPreview(text: string, max = 200): string {
  return truncateToolText(text, max)
}

export function normalizeToolName(raw: unknown): string {
  const record = asRecord(raw)
  const fn = asRecord(record?.function)
  const value = record?.name ?? record?.tool_name ?? record?.toolName ?? fn?.name
  const name = typeof value === 'string' ? value.trim() : ''
  return name && name !== 'tool' ? name : ''
}

export function isInternalToolName(name: string): boolean {
  return name === 'router_control'
}

export function normalizeToolInputText(raw: unknown): string {
  const record = asRecord(raw)
  const value = record?.input ?? record?.arguments ?? ''
  if (value == null) return ''
  if (typeof value === 'string') {
    const text = value.trim()
    return isEmptyToolPreview(text) ? '' : text
  }
  if (Array.isArray(value) && value.length === 0) return ''
  if (typeof value === 'object' && Object.keys(value).length === 0) return ''
  const text = JSON.stringify(value, null, 2)
  return isEmptyToolPreview(text) ? '' : text
}

export function toolDisplayName(name: string, input: unknown): string {
  if (name === 'publish_artifact') {
    const inputObj = parseToolInput(input)
    const target = inputObj?.name || inputObj?.path
    if (typeof target === 'string' && target) {
      return `${name} - ${target.split(/[\\/]+/).filter(Boolean).pop() || target}`
    }
  }
  return name
}

export function toolIconName(name: string): IconName {
  const n = String(name || '').toLowerCase()
  if (n.includes('search') || n.includes('google') || n.includes('bing')) return 'search'
  if (n.includes('fetch') || n.includes('http') || n.includes('curl') || n.includes('wget')) return 'monitor'
  if (n.includes('python') || n === 'py' || n.includes('exec') || n.includes('bash') || n.includes('shell')) return 'config'
  if (n.includes('write') || n.includes('edit') || n.includes('patch')) return 'edit'
  if (n.includes('read') || n.includes('file') || n.includes('cat') || n.includes('list') || n === 'ls' || n.includes('glob') || n.includes('find')) return 'logs'
  if (n.includes('artifact') || n.includes('download')) return 'download'
  if (n.includes('memory')) return 'clock'
  return 'gear'
}

export function toolOperationKey(name: string): string {
  const n = String(name || '').toLowerCase()
  if (n.includes('web_search') || n === 'search' || n.includes('google') || n.includes('bing')) return 'web.search'
  if (n.includes('web_fetch') || n.includes('http') || n.includes('fetch') || n.includes('curl') || n.includes('wget')) return 'web.read'
  if (n.includes('python') || n === 'py') return 'code.python'
  if (n.includes('bash') || n.includes('shell') || n.includes('exec')) return 'command.run'
  if (n.includes('write')) return 'file.write'
  if (n.includes('edit') || n.includes('patch')) return 'file.edit'
  if (n.includes('read') || n.includes('cat') || n.includes('list') || n === 'ls' || n.includes('glob') || n.includes('find') || n.includes('file')) return 'file.inspect'
  if (n.includes('publish_artifact') || n.includes('artifact')) return 'artifact.create'
  if (n.includes('memory')) return 'memory.search'
  return `tool.${n.replace(/[^a-z0-9]+/g, '.') || 'unknown'}`
}

export function toolActionLabel(name: string): string {
  const key = toolOperationKey(name)
  if (key === 'web.search') return 'Search web'
  if (key === 'web.read') return 'Read web page'
  if (key === 'code.python') return 'Run Python'
  if (key === 'command.run') return 'Run command'
  if (key === 'file.inspect') return 'Inspect files'
  if (key === 'file.write') return 'Write file'
  if (key === 'file.edit') return 'Edit file'
  if (key === 'artifact.create') return 'Create file'
  if (key === 'memory.search') return 'Search memory'
  return name.replace(/[_-]+/g, ' ')
}

export function toolSecondaryText(toolCall: ChatToolCall): string {
  const source = String(toolCall.inputPreview || toolCall.resultPreview || '').replace(/\s+/g, ' ').trim()
  if (isEmptyToolPreview(source)) return ''
  return truncateToolText(source.replace(/^"|"$/g, ''), 86)
}

export function summarizeToolGroup(calls: ChatToolCall[]): string {
  const running = calls.filter(toolCall => toolCall.isRunning).length
  const done = calls.filter(toolCall => toolCall.status === 'success').length
  const failed = calls.filter(toolCall => toolCall.status === 'error').length
  const sample = calls.map(toolCall => toolSecondaryText(toolCall)).find(Boolean)
  const parts = []
  if (running) parts.push(`${running} running`)
  if (done) parts.push(`${done} done`)
  if (failed) parts.push(`${failed} failed`)
  if (sample) parts.push(sample)
  return parts.join(' · ')
}

export function toolCallGroups(calls: ChatToolCall[] | undefined, ownerKey: string): ChatToolCallGroup[] {
  if (!calls?.length) return []
  const groups: ChatToolCallGroup[] = []

  calls.forEach((call, index) => {
    const operationKey = toolOperationKey(call.name)
    const renderKey = `${ownerKey}:tool:${call.toolId || call.name || index}:${index}`
    const last = groups[groups.length - 1]
    if (!last || last.operationKey !== operationKey || (call.groupId && last.groupId !== call.groupId)) {
      groups.push({
        groupId: call.groupId || `${ownerKey}:tool-group:${operationKey}:${groups.length}`,
        operationKey,
        label: toolActionLabel(call.name),
        iconName: toolIconName(call.name),
        calls: [],
        secondary: '',
        isRunning: false,
        isError: false,
        status: '',
      })
    }

    groups[groups.length - 1].calls.push({ ...call, renderKey } as ChatToolCallRenderItem)
  })

  groups.forEach(group => {
    group.isRunning = group.calls.some(tc => tc.isRunning)
    group.isError = group.calls.some(tc => tc.isError || tc.status === 'error')
    group.status = group.isError ? 'error' : (group.calls.every(tc => tc.status === 'success') ? 'success' : '')
    group.secondary = group.calls.length === 1
      ? toolSecondaryText(group.calls[0])
      : summarizeToolGroup(group.calls)
  })

  return groups
}

export function toolResultCount(raw: string): number | null {
  const text = String(raw || '').trim()
  if (!text) return null
  // 结果 is the CJK word for "results", kept to parse localized tool output.
  const match = /(?:^|\D)(\d{1,4})\s*(?:results?|结果)(?:\D|$)/i.exec(text)
  if (match) return Number(match[1])
  try {
    const parsed = JSON.parse(text)
    if (Array.isArray(parsed)) return parsed.length
    for (const key of ['results', 'items', 'data', 'matches']) {
      if (Array.isArray(parsed?.[key])) return parsed[key].length
    }
  } catch {}
  return null
}

export function toolResultIsError(payload: unknown): boolean {
  const record = asRecord(payload)
  const status = asRecord(record?.execution_status ?? record?.executionStatus)
  if (typeof status?.status === 'string') {
    return ['error', 'timeout', 'cancelled'].includes(status.status)
  }
  return !!(record?.is_error || record?.isError || record?.error)
}

export function toolStatusText(toolCall: ChatToolCall): string {
  if (toolCall.isRunning) return 'Running'
  if (toolCall.status === 'error') return 'Failed'
  const count = toolResultCount(toolCall.result)
  if (count !== null) return `${count} results`
  if (toolCall.status === 'success') return 'Done'
  return 'Pending'
}

export function toolGroupStatusText(group: ChatToolCallGroup): string {
  if (group.isRunning) return 'Running'
  if (group.isError) return 'Failed'
  const counts = group.calls.map(toolCall => toolResultCount(toolCall.result)).filter((count): count is number => count !== null)
  if (counts.length && group.calls.length === 1) return `${counts[0]} results`
  if (counts.length) return `${counts.reduce((sum, count) => sum + count, 0)} results`
  if (group.status === 'success') return 'Done'
  return 'Pending'
}

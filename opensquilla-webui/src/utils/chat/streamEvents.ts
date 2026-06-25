import type { SessionEventPayload } from '@/types/rpc'

export interface StreamSeqDecision {
  accepted: boolean
  nextStreamSeq: number
}

export type NormalizeRunStatus = (status: string) => string

export function payloadSessionKey(payload: SessionEventPayload | null | undefined): string {
  return payload?.key || payload?.session_key || payload?.sessionKey || ''
}

export function isCurrentSessionPayload(payload: SessionEventPayload | null | undefined, sessionKey: string): boolean {
  const key = payloadSessionKey(payload)
  return !key || !sessionKey || key === sessionKey
}

export function isStaleEpoch(payload: SessionEventPayload | null | undefined, currentEpoch: number): boolean {
  const ep = payload?.epoch
  if (typeof ep !== 'number' || !Number.isFinite(ep)) return false
  return ep < currentEpoch
}

export function acceptStreamSeq(
  payload: SessionEventPayload | null | undefined,
  sessionKey: string,
  lastStreamSeq: number,
): StreamSeqDecision {
  if (!isCurrentSessionPayload(payload, sessionKey)) {
    return { accepted: false, nextStreamSeq: lastStreamSeq }
  }
  const seq = payload?.stream_seq
  if (typeof seq !== 'number' || !Number.isFinite(seq)) {
    return { accepted: true, nextStreamSeq: lastStreamSeq }
  }
  if (seq <= lastStreamSeq) {
    return { accepted: false, nextStreamSeq: lastStreamSeq }
  }
  return { accepted: true, nextStreamSeq: seq }
}

export function taskGroupId(payload: SessionEventPayload | null | undefined): string {
  const id = payload?.group_id
  return typeof id === 'string' && id ? id : ''
}

export function activeTaskGroupRunState(payload: SessionEventPayload = {}, activeTaskGroupCount: number) {
  return {
    run_status: 'running',
    active_task: { ...(payload || {}), status: 'running', task_group_count: activeTaskGroupCount },
  }
}

export function sessionChangeIsTerminal(
  payload: SessionEventPayload,
  normalizeRunStatus: NormalizeRunStatus,
): boolean {
  const reason = String(payload?.reason || '').toLowerCase()
  if (reason === 'turn_complete' || reason === 'task_terminal') return true
  const lifecycle = String(payload?.status || '').toLowerCase()
  if (['done', 'failed', 'killed', 'timeout'].includes(lifecycle)) return true
  const runStatus = normalizeRunStatus(String(payload?.run_status || payload?.runStatus || ''))
  return ['failed', 'timeout', 'cancelled', 'interrupted'].includes(runStatus)
}

export function taskTerminalStatus(event: string): string {
  if (!event.startsWith('task.')) return ''
  const status = event.slice('task.'.length)
  return ['succeeded', 'failed', 'timeout', 'abandoned', 'cancelled'].includes(status) ? status : ''
}

export function taskTerminalAsSessionEvent(event: string, payload: SessionEventPayload | null | undefined) {
  if (event === 'task.cancelled') {
    return { event: 'session.event.done', payload: { ...(payload || {}), reason: 'aborted' } }
  }
  if (!['task.failed', 'task.timeout', 'task.abandoned'].includes(event)) return null
  const status = event.replace('task.', '')
  return {
    event: 'session.event.error',
    payload: { ...(payload || {}), message: taskTerminalMessage(status, payload), code: status },
  }
}

export function taskTerminalMessage(status: string, payload: SessionEventPayload | null | undefined): string {
  if (typeof payload?.terminal_message === 'string' && payload.terminal_message.trim()) return payload.terminal_message.trim()
  if (status === 'timeout') return 'The task timed out before it could finish.'
  if (status === 'abandoned') return 'The task stopped before it could finish.'
  if (status === 'cancelled') return 'The task was cancelled before it finished.'
  if (status === 'failed') return 'The task failed before it could finish.'
  return 'The task ended before it could finish.'
}

export function sessionErrorMessage(payload: SessionEventPayload | null | undefined): string {
  if (typeof payload?.terminal_message === 'string' && payload.terminal_message.trim()) return payload.terminal_message.trim()
  const message = typeof payload?.message === 'string' ? payload.message : ''
  const code = typeof payload?.code === 'string' ? payload.code.toLowerCase() : ''
  if (code.includes('timeout') || message.toLowerCase().includes('stream idle')) return 'The task timed out before it could finish.'
  if (message) return message
  return 'Agent error'
}

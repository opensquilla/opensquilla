import type { ChatMessage, ChatRunStatus, ChatRunTask } from '@/types/chat'

export const STOPPED_OUTPUT_NOTICE_PROVENANCE = 'client_stop_notice'

export function messagesWithStoppedOutputNotice(
  messages: ChatMessage[],
  runStatus: ChatRunStatus,
  emptyTurnLabel = '',
): ChatMessage[] {
  const filled = emptyTurnLabel
    ? messagesWithInteriorStoppedOutputNotices(messages, emptyTurnLabel)
    : messages
  const notice = stoppedOutputNoticeMessage(filled, runStatus)
  return notice ? [...filled, notice] : filled
}

export function stoppedOutputNoticeMessage(
  messages: ChatMessage[],
  runStatus: ChatRunStatus,
): ChatMessage | null {
  if (runStatus.status !== 'cancelled' && runStatus.status !== 'interrupted') return null
  const label = String(runStatus.label || '').trim()
  if (!label) return null

  const lastUserIndex = lastUserMessageIndex(messages)
  if (lastUserIndex < 0) return null
  if (turnAlreadyHasVisibleOutput(messages, lastUserIndex)) return null

  const lastUser = messages[lastUserIndex]
  const task = runStatus.task || null
  const taskId = taskKey(task)
  const userKey = lastUser.messageId || String(lastUser.ts ?? lastUserIndex)
  return {
    role: 'assistant',
    text: label,
    ts: taskFinishedAt(task) ?? messages[messages.length - 1]?.ts ?? null,
    messageId: `client-stop-notice:${taskId || userKey}`,
    interrupted: true,
    stopNotice: true,
    provenanceKind: STOPPED_OUTPUT_NOTICE_PROVENANCE,
  }
}

function lastUserMessageIndex(messages: ChatMessage[]): number {
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]?.role === 'user') return i
  }
  return -1
}

function messagesWithInteriorStoppedOutputNotices(
  messages: ChatMessage[],
  label: string,
): ChatMessage[] {
  const noticesByInsertionIndex = new Map<number, ChatMessage[]>()
  let changed = false

  for (let i = 0; i < messages.length; i++) {
    const message = messages[i]
    if (message?.role !== 'user') continue
    if (!turnEndsBeforeAnotherUser(messages, i)) continue
    if (turnHasVisibleOutputBeforeNextUser(messages, i)) continue

    const insertionIndex = interiorStoppedOutputNoticeInsertionIndex(messages, i)
    const notices = noticesByInsertionIndex.get(insertionIndex) || []
    notices.push(interiorStoppedOutputNotice(message, i, label))
    noticesByInsertionIndex.set(insertionIndex, notices)
    changed = true
  }

  if (!changed) return messages

  const result: ChatMessage[] = []
  for (let i = 0; i < messages.length; i++) {
    const notices = noticesByInsertionIndex.get(i)
    if (notices) result.push(...notices)
    result.push(messages[i])
  }
  const trailingNotices = noticesByInsertionIndex.get(messages.length)
  if (trailingNotices) result.push(...trailingNotices)
  return result
}

function interiorStoppedOutputNoticeInsertionIndex(messages: ChatMessage[], userIndex: number): number {
  let index = userIndex + 1
  while (index < messages.length) {
    const message = messages[index]
    if (!message) {
      index++
      continue
    }
    if (message.role === 'router') {
      index++
      continue
    }
    if (message.role === 'assistant' && !assistantMessageHasVisibleOutput(message)) {
      index++
      continue
    }
    break
  }
  return index
}

function turnEndsBeforeAnotherUser(messages: ChatMessage[], userIndex: number): boolean {
  for (let i = userIndex + 1; i < messages.length; i++) {
    const message = messages[i]
    if (!message) continue
    if (message.role === 'router') continue
    if (message.role === 'assistant' && !assistantMessageHasVisibleOutput(message)) continue
    return message.role === 'user'
  }
  return false
}

function turnHasVisibleOutputBeforeNextUser(messages: ChatMessage[], userIndex: number): boolean {
  for (let i = userIndex + 1; i < messages.length; i++) {
    const message = messages[i]
    if (!message) continue
    if (message.role === 'user') return false
    if (message.stopNotice || message.provenanceKind === STOPPED_OUTPUT_NOTICE_PROVENANCE) return true
    if (message.role === 'router') continue
    if (message.role === 'assistant' && !assistantMessageHasVisibleOutput(message)) continue
    return true
  }
  return false
}

function turnAlreadyHasVisibleOutput(messages: ChatMessage[], lastUserIndex: number): boolean {
  for (let i = lastUserIndex + 1; i < messages.length; i++) {
    const message = messages[i]
    if (!message) continue
    if (message.stopNotice || message.provenanceKind === STOPPED_OUTPUT_NOTICE_PROVENANCE) return true
    if (message.role === 'router') continue
    if (message.role === 'assistant' && !assistantMessageHasVisibleOutput(message)) continue
    return true
  }
  return false
}

function interiorStoppedOutputNotice(userMessage: ChatMessage, userIndex: number, label: string): ChatMessage {
  const userKey = userMessage.messageId || String(userMessage.ts ?? userIndex)
  return {
    role: 'assistant',
    text: label,
    ts: userMessage.ts ?? null,
    messageId: `client-stop-notice:empty-turn:${userKey}:${userIndex}`,
    interrupted: true,
    stopNotice: true,
    provenanceKind: STOPPED_OUTPUT_NOTICE_PROVENANCE,
  }
}

function assistantMessageHasVisibleOutput(message: ChatMessage): boolean {
  return Boolean(
    String(message.text || '').trim() ||
    message.reasoning?.text ||
    message.attachments?.length ||
    message.artifacts?.length ||
    message.tool_calls?.length ||
    message.timeline?.length ||
    message.statusHistory?.length,
  )
}

function taskKey(task: ChatRunTask | null): string {
  return String(task?.task_id || task?.taskId || '').trim()
}

function taskFinishedAt(task: ChatRunTask | null): string | number | null {
  return task?.finished_at ?? task?.finishedAt ?? null
}

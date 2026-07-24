import type { ChatRenderedMessage, ChatStreamTimelineItem } from '@/types/chat'
import type { ChatPart } from '@/types/parts'

type TextPart = Extract<ChatPart, { type: 'text' }>

export interface AssistantActivityProjection {
  /**
   * Whether the message can be rendered as a compact activity disclosure plus
   * one canonical answer. False is the compatibility path for older history
   * rows that have timeline text but no authoritative message.text.
   */
  canSeparateActivity: boolean
  activityItems: ChatStreamTimelineItem[]
  answerPart: TextPart | null
  toolCount: number
  failureCount: number
}

/**
 * Project a completed assistant message into compact activity and canonical
 * answer surfaces without rewriting the persisted timeline.
 *
 * The terminal `message.text` is the only authoritative answer. Timeline text
 * may be a prefix, suffix, or stale streamed snapshot, so it is never used to
 * guess the answer. Older rows that lack canonical text keep their original
 * timeline rendering rather than risking hidden content.
 */
export function projectAssistantActivity(
  message: ChatRenderedMessage,
  renderMarkdown: (text: string) => string,
  fallbackToolItems: ChatStreamTimelineItem[] = [],
): AssistantActivityProjection {
  const timeline = message.timelineItems?.length
    ? message.timelineItems
    : fallbackToolItems
  const hasTimelineText = timeline.some(item => item.type === 'text')
  const hasCanonicalAnswer = Boolean(message.text.trim())
  const canSeparateActivity = hasCanonicalAnswer || !hasTimelineText
  const activityItems = canSeparateActivity
    ? timeline.filter((item): item is Extract<ChatStreamTimelineItem, { type: 'tool-group' }> =>
        item.type === 'tool-group',
      )
    : []

  let toolCount = 0
  let failureCount = 0
  for (const item of activityItems) {
    toolCount += item.group.calls.length
    failureCount += item.group.calls.filter(
      call => call.isError || call.status === 'error',
    ).length
  }

  const answerPart: TextPart | null = canSeparateActivity && hasCanonicalAnswer
    ? {
        type: 'text',
        html: renderMarkdown(message.text),
        rawText: message.text,
        key: `${message.messageId || message.id || 'assistant'}:answer`,
      }
    : null

  return {
    canSeparateActivity,
    activityItems,
    answerPart,
    toolCount,
    failureCount,
  }
}

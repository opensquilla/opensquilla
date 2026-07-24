import { describe, expect, it } from 'vitest'

import type {
  ChatRenderedMessage,
  ChatStreamTimelineItem,
  ChatToolCallRenderItem,
} from '@/types/chat'
import { projectAssistantActivity } from './assistantActivity'

function message(overrides: Partial<ChatRenderedMessage> = {}): ChatRenderedMessage {
  return {
    id: 'assistant-1',
    role: 'assistant',
    displayRole: 'assistant',
    roleLabel: 'Assistant',
    text: '',
    timeStr: '',
    showHeader: false,
    ...overrides,
  }
}

function call(
  toolId: string,
  overrides: Partial<ChatToolCallRenderItem> = {},
): ChatToolCallRenderItem {
  return {
    toolId,
    renderKey: toolId,
    name: 'web_search',
    displayName: 'Search',
    inputRaw: '{}',
    inputPreview: '{}',
    isRunning: false,
    status: 'success',
    isError: false,
    result: 'ok',
    resultPreview: 'ok',
    isOpen: false,
    ...overrides,
  }
}

function toolGroup(calls: ChatToolCallRenderItem[]): ChatStreamTimelineItem {
  return {
    type: 'tool-group',
    key: 'group-1',
    group: {
      groupId: 'group-1',
      operationKey: 'web.search',
      label: 'Search',
      iconName: 'search',
      calls,
      secondary: '',
      isRunning: false,
      isError: calls.some(item => item.isError),
      status: calls.some(item => item.isError) ? 'error' : 'success',
    },
  }
}

describe('projectAssistantActivity', () => {
  it('uses canonical message text and never guesses from the last timeline fragment', () => {
    const failed = call('failed', {
      status: 'error',
      isError: true,
      result: 'network error',
      resultPreview: 'network error',
    })
    const projection = projectAssistantActivity(
      message({
        text: 'Canonical prefix and suffix',
        timelineItems: [
          { type: 'text', key: 'prefix', html: 'Canonical prefix', rawText: 'Canonical prefix' },
          toolGroup([call('ok'), failed]),
          { type: 'text', key: 'suffix', html: ' and suffix', rawText: ' and suffix' },
        ],
      }),
      text => `<p>${text}</p>`,
    )

    expect(projection.canSeparateActivity).toBe(true)
    expect(projection.activityItems).toHaveLength(1)
    expect(projection.activityItems[0]?.type).toBe('tool-group')
    expect(projection.answerPart).toMatchObject({
      rawText: 'Canonical prefix and suffix',
      html: '<p>Canonical prefix and suffix</p>',
    })
    expect(projection.toolCount).toBe(2)
    expect(projection.failureCount).toBe(1)
    const tools = projection.activityItems.flatMap(item =>
      item.type === 'tool-group' ? item.group.calls : [],
    )
    expect(tools.map(item => item.toolId)).toEqual(['ok', 'failed'])
  })

  it('preserves the original timeline when old history has text but no canonical answer', () => {
    const timelineItems: ChatStreamTimelineItem[] = [
      { type: 'text', key: 'legacy-text', html: 'Legacy answer', rawText: 'Legacy answer' },
      toolGroup([call('legacy-tool')]),
    ]
    const projection = projectAssistantActivity(
      message({ text: '', timelineItems }),
      text => text,
    )

    expect(projection.canSeparateActivity).toBe(false)
    expect(projection.activityItems).toEqual([])
    expect(projection.answerPart).toBeNull()
    expect(projection.toolCount).toBe(0)
  })

  it('treats whitespace-only canonical text as missing for compatibility', () => {
    const projection = projectAssistantActivity(
      message({
        text: '   ',
        timelineItems: [{
          type: 'text',
          key: 'legacy-text',
          html: 'Legacy answer',
          rawText: 'Legacy answer',
        }],
      }),
      text => text,
    )

    expect(projection.canSeparateActivity).toBe(false)
    expect(projection.answerPart).toBeNull()
  })

  it('folds legacy tool-only calls without inventing an answer', () => {
    const fallback = [toolGroup([call('legacy-tool')])]
    const projection = projectAssistantActivity(
      message({ text: '', timelineItems: [] }),
      text => text,
      fallback,
    )

    expect(projection.canSeparateActivity).toBe(true)
    expect(projection.activityItems).toEqual(fallback)
    expect(projection.answerPart).toBeNull()
    expect(projection.toolCount).toBe(1)
  })
})

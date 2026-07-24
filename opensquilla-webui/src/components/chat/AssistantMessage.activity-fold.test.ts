// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { createApp, h, nextTick, type App } from 'vue'
import { createPinia } from 'pinia'

import i18n from '@/i18n'
import { useToolDetailPreference } from '@/composables/useToolDetailPreference'
import type {
  ChatRenderedMessage,
  ChatStreamTimelineItem,
  ChatToolCallRenderItem,
} from '@/types/chat'
import AssistantMessage from './AssistantMessage.vue'

const mountedApps: App[] = []

function failedCall(): ChatToolCallRenderItem {
  return {
    toolId: 'failed-search',
    renderKey: 'failed-search',
    name: 'web_search',
    displayName: 'Search',
    inputRaw: '{"query":"OpenSquilla"}',
    inputPreview: 'OpenSquilla',
    isRunning: false,
    status: 'error',
    isError: true,
    result: 'Network unavailable',
    resultPreview: 'Network unavailable',
    isOpen: false,
  }
}

function failedTimeline(): ChatStreamTimelineItem[] {
  const call = failedCall()
  return [
    { type: 'text', key: 'draft-prefix', html: 'Draft prefix', rawText: 'Draft prefix' },
    {
      type: 'tool-group',
      key: 'failed-group',
      group: {
        groupId: 'failed-group',
        operationKey: 'web.search',
        label: 'Search',
        iconName: 'search',
        calls: [call],
        secondary: '',
        isRunning: false,
        isError: true,
        status: 'error',
      },
    },
    { type: 'text', key: 'draft-suffix', html: 'Draft suffix', rawText: 'Draft suffix' },
  ]
}

function successfulTimeline(): ChatStreamTimelineItem[] {
  const call = failedCall()
  call.status = 'success'
  call.isError = false
  call.result = 'Found one result'
  call.resultPreview = 'Found one result'
  return failedTimeline().map(item => {
    if (item.type !== 'tool-group') return item
    return {
      ...item,
      group: {
        ...item.group,
        calls: [call],
        isError: false,
        status: 'success' as const,
      },
    }
  })
}

function baseMessage(overrides: Partial<ChatRenderedMessage> = {}): ChatRenderedMessage {
  return {
    id: 'assistant-1',
    messageId: 'assistant-1',
    role: 'assistant',
    displayRole: 'assistant',
    roleLabel: 'Assistant',
    text: 'Canonical answer',
    timeStr: '',
    showHeader: false,
    timelineItems: failedTimeline(),
    parts: [{
      type: 'reasoning',
      key: 'assistant-1:reasoning',
      text: 'Checked the available evidence.',
      seconds: 7,
    }],
    statusHistory: [
      { action: 'search', label: 'Searching', at: 1000 },
      { action: 'write', label: 'Writing', at: 2000 },
    ],
    ...overrides,
  }
}

function mountMessage(message: ChatRenderedMessage): HTMLElement {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp({
    render: () => h(AssistantMessage, {
      message,
      index: 0,
      sessionKey: 'session-a',
      shareMode: false,
      shareSelected: false,
      shareMessageId: 'assistant-1',
      renderMarkdown: (text: string) => `<p>${text}</p>`,
      fmtTok: (value: number) => String(value),
      toolCallGroups: () => [],
      isToolGroupOpen: () => false,
      isToolItemOpen: () => false,
      toolGroupStatusText: () => 'Failed',
      toolStatusText: () => 'Failed',
      toolSecondaryText: () => '',
      copyMessage: async () => true,
    }),
  })
  mountedApps.push(app)
  app.use(i18n)
  app.use(createPinia())
  app.mount(el)
  return el
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  useToolDetailPreference().setMode('auto')
  document.body.innerHTML = ''
})

afterEach(() => {
  while (mountedApps.length) mountedApps.pop()?.unmount()
  document.body.innerHTML = ''
})

describe('AssistantMessage activity disclosure', () => {
  it('keeps the canonical answer outside one activity fold and preserves failures', async () => {
    const el = mountMessage(baseMessage())
    await nextTick()

    const activity = el.querySelector<HTMLDetailsElement>('.assistant-activity')
    const answer = el.querySelector<HTMLElement>('.msg-ai-text')
    const failedRow = activity?.querySelector<HTMLElement>('.tool-row--error')

    expect(activity).not.toBeNull()
    expect(activity?.open).toBe(true)
    expect(activity?.querySelectorAll('details')).toHaveLength(0)
    expect(activity?.textContent).toContain('Checked the available evidence.')
    expect(activity?.textContent).toContain('Searching')
    expect(activity?.textContent).toContain('1 failed')
    expect(failedRow).not.toBeNull()
    expect(failedRow?.getAttribute('aria-expanded')).toBe('true')

    expect(answer?.textContent).toBe('Canonical answer')
    expect(activity?.contains(answer ?? null)).toBe(false)
    expect(el.querySelectorAll('.msg-ai-text')).toHaveLength(1)
    expect(el.textContent).not.toContain('Draft prefix')
    expect(el.textContent).not.toContain('Draft suffix')
  })

  it('defaults successful activity to collapsed', async () => {
    const el = mountMessage(baseMessage({ timelineItems: successfulTimeline() }))
    await nextTick()

    expect(el.querySelector<HTMLDetailsElement>('.assistant-activity')?.open).toBe(false)
    expect(el.querySelector('.tool-row')).not.toBeNull()
  })

  it('honors the global expanded tool-detail preference at the outer fold', async () => {
    useToolDetailPreference().setMode('expanded')
    const el = mountMessage(baseMessage({ timelineItems: successfulTimeline() }))
    await nextTick()

    expect(el.querySelector<HTMLDetailsElement>('.assistant-activity')?.open).toBe(true)
    expect(el.querySelector('.tool-row-body')).not.toBeNull()
  })

  it('does not apply the tool-detail preference to reasoning-only activity', async () => {
    useToolDetailPreference().setMode('expanded')
    const el = mountMessage(baseMessage({
      timelineItems: [],
      statusHistory: [],
    }))
    await nextTick()

    expect(el.querySelector<HTMLDetailsElement>('.assistant-activity')?.open).toBe(false)
    expect(el.querySelector('.thinking-block')).not.toBeNull()
  })

  it('preserves legacy timeline order when no canonical answer exists', async () => {
    const el = mountMessage(baseMessage({
      text: '   ',
      parts: [],
      statusHistory: [],
    }))
    await nextTick()

    const text = el.textContent || ''
    expect(el.querySelector('.assistant-activity')).toBeNull()
    expect(text).toContain('Draft prefix')
    expect(text).toContain('Draft suffix')
    expect(text.indexOf('Draft prefix')).toBeLessThan(text.indexOf('Search'))
    expect(text.indexOf('Search')).toBeLessThan(text.indexOf('Draft suffix'))
  })

  it('keeps artifacts outside the activity disclosure and actionable', async () => {
    const el = mountMessage(baseMessage({
      artifacts: [{
        id: 'artifact-1',
        name: 'study-notes.md',
        mime: 'text/markdown',
        download_url: '/api/v1/artifacts/artifact-1',
      }],
    }))
    await nextTick()

    const activity = el.querySelector('.assistant-activity')
    const artifacts = el.querySelector<HTMLElement>('.msg-artifacts')
    expect(activity).not.toBeNull()
    expect(artifacts).not.toBeNull()
    expect(activity?.contains(artifacts ?? null)).toBe(false)
    expect(artifacts?.textContent).toContain('study-notes.md')
    expect(artifacts?.querySelector('button')).not.toBeNull()
  })

  it('does not render an empty disclosure for a plain canonical answer', async () => {
    const el = mountMessage(baseMessage({
      timelineItems: [],
      parts: [],
      statusHistory: [],
    }))
    await nextTick()

    expect(el.querySelector('.assistant-activity')).toBeNull()
    expect(el.querySelector('.msg-ai-text')?.textContent).toBe('Canonical answer')
  })
})

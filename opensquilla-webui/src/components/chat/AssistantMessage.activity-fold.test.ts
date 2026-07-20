// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import type {
  ChatRenderedMessage,
  ChatStreamTimelineItem,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
} from '@/types/chat'
import AssistantMessage from './AssistantMessage.vue'

function call(
  id: string,
  name: string,
  options: { status?: 'success' | 'error'; result?: string; inputPreview?: string } = {},
): ChatToolCallRenderItem {
  const status = options.status ?? 'success'
  return {
    toolId: id,
    renderKey: `turn:tool:${id}`,
    name,
    displayName: name,
    inputPreview: options.inputPreview ?? '',
    isRunning: false,
    status,
    isError: status === 'error',
    result: options.result ?? 'ok',
    resultPreview: options.result ?? 'ok',
    isOpen: false,
  }
}

function group(
  id: string,
  operationKey: string,
  label: string,
  calls: ChatToolCallRenderItem[],
): ChatToolCallGroup {
  return {
    groupId: id,
    operationKey,
    label,
    iconName: 'gear',
    calls,
    secondary: '',
    isRunning: false,
    isError: false,
    status: 'success',
  }
}

async function mountMessage(timelineItems: ChatStreamTimelineItem[], reasoningSeconds = 12, turnElapsedSeconds = 125) {
  const message: ChatRenderedMessage = {
    id: 'assistant-1',
    role: 'assistant',
    displayRole: 'assistant',
    roleLabel: 'Assistant',
    text: 'Final answer',
    timeStr: '',
    ts: null,
    showHeader: false,
    reasoning: { text: 'Compare both approaches.', seconds: reasoningSeconds },
    parts: [{
      type: 'reasoning',
      text: 'Compare both approaches.',
      seconds: reasoningSeconds,
      key: 'assistant-1:reasoning',
    }],
    timelineItems,
  }
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(AssistantMessage, {
    message,
    index: 0,
    turnElapsedSeconds,
    shareMode: false,
    shareSelected: false,
    shareMessageId: 'assistant-1',
    renderMarkdown: (text: string) => text,
    fmtTok: (value: number) => String(value),
    toolCallGroups: () => [],
    isToolGroupOpen: () => false,
    isToolItemOpen: () => false,
    toolGroupStatusText: () => '',
    toolStatusText: () => '',
    toolSecondaryText: () => '',
    copyMessage: async () => true,
  })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('AssistantMessage activity fold', () => {
  it('shows a reasoning-only disclosure without duplicated labels or nested cards', async () => {
    const { app, el } = await mountMessage([
      { type: 'text', key: 'answer', html: '<p>Ready.</p>', rawText: 'Ready.' },
    ], 0)
    const summary = el.querySelector('[data-testid="activity-fold-toggle"]')

    expect(summary?.textContent).toContain('Completed 2m 5s')
    expect(el.querySelector('.activity-fold__summary-meta')).toBeNull()
    expect(el.querySelector('.activity-fold__reasoning-label')).toBeNull()
    expect(el.querySelector('.activity-fold__step-index')).toBeNull()
    app.unmount()
  })

  it('keeps execution context folded while leaving the final answer visible', async () => {
    const timeline: ChatStreamTimelineItem[] = [
      { type: 'text', key: 'plan', html: '<p>Inspecting the project.</p>', rawText: 'Inspecting the project.' },
      {
        type: 'tool-group',
        key: 'search',
        group: group('search', 'web.search', 'Search the web', [
          call('search-1', 'web_search'),
          call('search-2', 'web_search'),
        ]),
      },
      {
        type: 'tool-group',
        key: 'edit',
        group: group('edit', 'file.edit', 'Edit file', [call('edit-1', 'apply_patch')]),
      },
      { type: 'text', key: 'answer', html: '<p>Final answer stays visible.</p>', rawText: 'Final answer stays visible.' },
    ]
    const { app, el } = await mountMessage(timeline)
    const details = el.querySelector<HTMLDetailsElement>('.activity-fold')

    expect(details).toBeTruthy()
    expect(details?.open).toBe(false)
    expect(el.querySelector('[data-testid="activity-fold-toggle"]')?.textContent)
      .toContain('Completed 2m 5s')

    const renderedText = Array.from(el.querySelectorAll<HTMLElement>('.msg-ai-text'))
    const planning = renderedText.find(node => node.textContent?.includes('Inspecting the project.'))
    const answer = renderedText.find(node => node.textContent?.includes('Final answer stays visible.'))
    expect(planning?.closest('details')).toBe(details)
    expect(answer?.closest('details')).toBeNull()

    el.querySelector<HTMLElement>('[data-testid="activity-fold-toggle"]')?.click()
    await nextTick()
    expect(details?.open).toBe(true)
    expect(el.querySelector('.activity-fold__reasoning-text')).toBeNull()
    expect(Array.from(el.querySelectorAll('[aria-expanded="true"]'))).toHaveLength(0)

    const reasoningToggle = el.querySelector<HTMLButtonElement>('[data-testid="activity-reasoning-toggle"]')
    reasoningToggle?.click()
    await nextTick()
    expect(reasoningToggle?.getAttribute('aria-expanded')).toBe('true')
    expect(el.querySelector('.activity-fold__reasoning-text')?.textContent)
      .toBe('Compare both approaches.')

    const editStep = el.querySelector<HTMLButtonElement>('.tool-row[data-op="file.edit"]')
    editStep?.click()
    await nextTick()
    expect(reasoningToggle?.getAttribute('aria-expanded')).toBe('false')
    expect(el.querySelector('.activity-fold__reasoning-text')).toBeNull()
    expect(editStep?.getAttribute('aria-expanded')).toBe('true')

    const searchGroup = el.querySelector<HTMLButtonElement>('.tool-row--group[data-op="web.search"]')
    searchGroup?.click()
    await nextTick()
    expect(editStep?.getAttribute('aria-expanded')).toBe('false')
    expect(searchGroup?.getAttribute('aria-expanded')).toBe('true')

    const members = Array.from(el.querySelectorAll<HTMLButtonElement>('.tool-row--member'))
    expect(members).toHaveLength(2)
    expect(members.every(member => member.getAttribute('aria-expanded') === 'false')).toBe(true)
    members[0]?.click()
    await nextTick()
    expect(searchGroup?.getAttribute('aria-expanded')).toBe('true')
    expect(members[0]?.getAttribute('aria-expanded')).toBe('true')
    members[1]?.click()
    await nextTick()
    expect(members[0]?.getAttribute('aria-expanded')).toBe('false')
    expect(members[1]?.getAttribute('aria-expanded')).toBe('true')
    expect(el.querySelectorAll('.tool-row-body')).toHaveLength(1)
    app.unmount()
  })

  it('merges web research retries and omits failed or zero-result attempts', async () => {
    const timeline: ChatStreamTimelineItem[] = [
      { type: 'text', key: 'plan', html: '<p>Trying several providers.</p>', rawText: 'Trying several providers.' },
      {
        type: 'tool-group',
        key: 'search',
        group: group('search', 'web.search', 'Search web', [
          call('search-ok', 'web_search', {
            result: '{"results":[{"title":"AI update"}]}',
            inputPreview: '{"query":"AI news"}',
          }),
          call('search-empty', 'web_search', { result: '{"results":[]}' }),
          call('search-failed', 'web_search', { status: 'error', result: 'provider timeout' }),
        ]),
      },
      {
        type: 'tool-group',
        key: 'read',
        group: group('read', 'web.read', 'Read web page', [
          call('read-ok', 'web_fetch', {
            result: '{"content":"Useful article"}',
            inputPreview: '{"url":"https://example.com/article"}',
          }),
          call('read-failed', 'web_fetch', { status: 'error', result: 'fetch failed' }),
        ]),
      },
      { type: 'text', key: 'answer', html: '<p>Here is the useful summary.</p>', rawText: 'Here is the useful summary.' },
    ]
    const { app, el } = await mountMessage(timeline)

    const summary = el.querySelector('[data-testid="activity-fold-toggle"]')
    expect(summary?.textContent).toContain('Completed 2m 5s')
    expect(summary?.textContent).not.toContain('failed')

    summary?.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await nextTick()
    const researchGroup = el.querySelector<HTMLButtonElement>('.tool-row--group[data-op="web.research"]')
    expect(researchGroup).toBeTruthy()
    expect(researchGroup?.textContent).toContain('Searched and read the web')
    expect(researchGroup?.textContent).toContain('2 calls')
    expect(researchGroup?.textContent).not.toContain('failed')

    researchGroup?.click()
    await nextTick()
    const members = Array.from(el.querySelectorAll<HTMLButtonElement>('.tool-row--member'))
    expect(members).toHaveLength(2)
    expect(members.map(member => member.textContent)).toEqual(expect.arrayContaining([
      expect.stringContaining('Search web'),
      expect.stringContaining('Read web page'),
    ]))
    expect(el.querySelector('.tool-row--error')).toBeNull()
    expect(el.textContent).not.toContain('Trying several providers.')
    expect(el.textContent).toContain('Here is the useful summary.')
    app.unmount()
  })

  it('omits failed calls from mixed activity without showing failure rows', async () => {
    const timeline: ChatStreamTimelineItem[] = [
      {
        type: 'tool-group',
        key: 'read',
        group: group('read', 'web.read', 'Read web page', [
          call('read-ok', 'web_fetch', { result: '{"content":"Useful"}' }),
          call('read-failed', 'web_fetch', { status: 'error', result: 'fetch failed' }),
        ]),
      },
      {
        type: 'tool-group',
        key: 'edit-failed',
        group: group('edit-failed', 'file.edit', 'Edit file', [
          call('edit-failed', 'apply_patch', { status: 'error', result: 'edit failed' }),
        ]),
      },
      { type: 'text', key: 'answer', html: '<p>Useful answer.</p>', rawText: 'Useful answer.' },
    ]
    const { app, el } = await mountMessage(timeline)

    el.querySelector<HTMLElement>('[data-testid="activity-fold-toggle"]')?.click()
    await nextTick()

    expect(el.querySelectorAll('.tool-row[data-op="web.read"]')).toHaveLength(1)
    expect(el.querySelector('.tool-row[data-op="file.edit"]')).toBeNull()
    expect(el.querySelector('.tool-row--error')).toBeNull()
    expect(el.textContent).not.toContain('fetch failed')
    expect(el.textContent).not.toContain('edit failed')
    app.unmount()
  })
})

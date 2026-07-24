// @vitest-environment happy-dom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h, nextTick, type App } from 'vue'

import ToolCallTimeline from '@/components/chat/ToolCallTimeline.vue'
import i18n from '@/i18n'
import type {
  ChatStreamTimelineItem,
  ChatToolCallGroup,
  ChatToolCallRenderItem,
} from '@/types/chat'

const mountedApps: App[] = []

function call(
  renderKey: string,
  overrides: Partial<ChatToolCallRenderItem> = {},
): ChatToolCallRenderItem {
  return {
    toolId: renderKey,
    renderKey,
    name: 'shell',
    displayName: renderKey,
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

function group(
  groupId: string,
  calls: ChatToolCallRenderItem[],
): Extract<ChatStreamTimelineItem, { type: 'tool-group' }> {
  const isError = calls.some(entry => entry.isError || entry.status === 'error')
  const isRunning = calls.some(entry => entry.isRunning)
  return {
    type: 'tool-group',
    key: groupId,
    group: {
      groupId,
      operationKey: groupId,
      label: groupId,
      iconName: 'gear',
      calls,
      secondary: '',
      isRunning,
      isError,
      status: isError
        ? 'error'
        : (calls.every(entry => entry.status === 'success') ? 'success' : ''),
    },
  }
}

async function mountTimeline(
  items: ChatStreamTimelineItem[],
  options: {
    presentation?: 'activity'
    itemOpen?: boolean
    onShowResult?: (content: string, title: string, context?: unknown) => void
    toolStatusText?: (call: ChatToolCallRenderItem) => string
  } = {},
) {
  const el = document.createElement('div')
  document.body.appendChild(el)

  const Host = defineComponent({
    setup() {
      return () => h(ToolCallTimeline, {
        items,
        ...(options.presentation ? { presentation: options.presentation } : {}),
        isToolGroupOpen: () => false,
        isToolItemOpen: () => options.itemOpen === true,
        toolGroupStatusText: (toolGroup: ChatToolCallGroup) => {
          if (toolGroup.isRunning) return 'Running'
          if (toolGroup.isError) return 'Failed'
          return 'Done'
        },
        toolStatusText: options.toolStatusText ?? (() => ''),
        toolSecondaryText: () => '',
        onShowResult: options.onShowResult,
      })
    },
  })

  const app = createApp(Host)
  mountedApps.push(app)
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return el
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

afterEach(() => {
  while (mountedApps.length) mountedApps.pop()?.unmount()
  document.body.innerHTML = ''
})

describe('RunTrace activity presentation', () => {
  const completedGroup = group('completed-group', [
    call('completed-one'),
    call('completed-two'),
  ])
  const failedGroup = group('failed-group', [
    call('failed-one', {
      status: 'error',
      isError: true,
      result: 'failed',
      resultPreview: 'failed',
    }),
    call('failed-two', {
      status: 'error',
      isError: true,
      result: 'failed',
      resultPreview: 'failed',
    }),
  ])

  it('keeps the existing card and success affordances by default', async () => {
    const el = await mountTimeline([completedGroup, failedGroup])

    expect(el.querySelector('.tool-timeline--activity')).toBeNull()
    expect(el.querySelector('.tool-row__bullet--ok')).not.toBeNull()
    expect(el.querySelector('.tool-row__state-icon--ok')).not.toBeNull()
    expect(el.querySelector('.step-chevron')).not.toBeNull()
    expect(el.querySelector('.tool-timeline__bulk-icon')).not.toBeNull()
    expect(
      Array.from(el.querySelectorAll('.tool-row--group .tool-row__status'))
        .map(node => node.textContent),
    ).toEqual(['Done', 'Failed'])
  })

  it('neutralizes completed chrome while retaining failure state', async () => {
    const el = await mountTimeline(
      [completedGroup, failedGroup],
      { presentation: 'activity' },
    )

    expect(el.querySelector('.tool-timeline--activity')).not.toBeNull()
    expect(el.querySelector('.tool-row__bullet--ok')).toBeNull()
    expect(el.querySelector('.tool-row__state-icon--ok')).toBeNull()
    expect(el.querySelector('.step-chevron')).toBeNull()
    expect(el.querySelector('.tool-timeline__toolbar')).toBeNull()
    expect(el.querySelector('.tool-timeline__bulk-icon')).toBeNull()
    expect(
      Array.from(el.querySelectorAll('.tool-row--group .tool-row__status'))
        .map(node => node.textContent),
    ).toEqual(['Failed'])
    expect(
      el.querySelector('.tool-row--group')?.getAttribute('aria-expanded'),
    ).toBe('false')
    expect(el.querySelector('.tool-row__bullet--err')).not.toBeNull()
    expect(el.querySelector('.tool-row__state-icon--err')).not.toBeNull()
    expect(el.querySelector('.tool-row-section--error')).not.toBeNull()
  })

  it('uses the running treatment without repeating a running status label', async () => {
    const runningGroup = group('running-group', [
      call('running-one', { isRunning: true, status: '' }),
      call('running-two', { isRunning: true, status: '' }),
    ])
    const el = await mountTimeline([runningGroup], { presentation: 'activity' })

    expect(el.querySelector('.tool-row__bullet--running')).not.toBeNull()
    expect(el.querySelector('.tool-row--group .tool-row__status')).toBeNull()
  })

  it('shows an accessible failure status for a single activity call', async () => {
    const el = await mountTimeline([
      group('single-failure-group', [
        call('single-failure', {
          status: 'error',
          isError: true,
          result: 'failed',
          resultPreview: 'failed',
        }),
      ]),
    ], { presentation: 'activity' })

    const row = el.querySelector('.tool-row--error')
    const status = row?.querySelector('.tool-row__status[role="status"]')
    expect(status?.textContent).toBe('Failed')
    expect(el.querySelector('.tool-row__state-icon--err')).not.toBeNull()
    expect(el.querySelector('.step-chevron')).toBeNull()
  })

  it('keeps injected cancellation copy visible for assistive technology', async () => {
    const el = await mountTimeline([
      group('single-cancelled-group', [
        call('single-cancelled', {
          status: 'error',
          isError: true,
          result: 'cancelled',
          resultPreview: 'cancelled',
        }),
      ]),
    ], {
      presentation: 'activity',
      toolStatusText: () => 'Cancelled',
    })

    expect(
      el.querySelector('.tool-row--error .tool-row__status[role="status"]')?.textContent,
    ).toBe('Cancelled')
  })

  it('keeps expanded raw details and full-result forwarding available', async () => {
    const result = 'command output\n'.repeat(30)
    const onShowResult = vi.fn()
    const el = await mountTimeline([
      group('long-result-group', [
        call('long-result', {
          result,
          resultPreview: result.slice(0, 200),
        }),
      ]),
    ], {
      presentation: 'activity',
      itemOpen: true,
      onShowResult,
    })

    const section = el.querySelector('.tool-row-section:not(.tool-row-section--error)')
    const viewFull = el.querySelector<HTMLButtonElement>('.step-view-btn')
    expect(section).not.toBeNull()
    expect(viewFull).not.toBeNull()

    viewFull?.click()

    expect(onShowResult).toHaveBeenCalledWith(
      result,
      'long-result-group · result',
      {
        toolName: 'shell',
        inputRaw: '{}',
        section: 'result',
      },
    )
  })
})

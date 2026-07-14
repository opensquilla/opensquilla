// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from 'vitest'
import { createApp, h, nextTick } from 'vue'
import i18n from '@/i18n'
import RunTrace from './RunTrace.vue'

describe('RunTrace tool result summary', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('shows model-delivered count separately from persisted preview count', async () => {
    const root = document.createElement('div')
    document.body.appendChild(root)
    const app = createApp({
      render: () => h(RunTrace, {
        items: [{
          type: 'tool-group',
          key: 'knowledge-search',
          group: {
            groupId: 'knowledge-search',
            operationKey: 'knowledge.search',
            label: '检索知识库',
            iconName: 'search',
            secondary: '',
            isRunning: false,
            isError: false,
            status: 'success',
            calls: [{
              toolId: 'call-1',
              renderKey: 'call-1',
              name: 'knowledge_search',
              displayName: 'knowledge_search',
              inputPreview: 'NAND',
              isRunning: false,
              status: 'success',
              isError: false,
              result: '{"returnedCount":20,"results":[{}]}',
              resultPreview: '{"returnedCount":20,"results":[{}]}',
              deliverySummary: {
                returnedCount: 20,
                resultChars: 12345,
                providerBudgetViolation: false,
              },
              previewSummary: {
                displayedCount: 1,
                previewChars: 1900,
                previewTruncated: true,
              },
              isOpen: false,
            }],
          },
        }],
        isToolGroupOpen: () => false,
        isToolItemOpen: () => false,
      }),
    })
    app.use(i18n)
    app.mount(root)
    await nextTick()

    expect(root.textContent).toContain(
      '模型收到 20 条结果 · 当前预览显示 1 条 · 预览已截断',
    )
    app.unmount()
  })
})

// @vitest-environment happy-dom
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createApp, defineComponent, h, nextTick, ref } from 'vue'
import i18n from '@/i18n'
import type { ChatStreamTimelineItem } from '@/types/chat'
import { copyTextWithFallback } from '@/utils/browser'
import RunTrace from './RunTrace.vue'

vi.mock('@/utils/browser', () => ({
  copyTextWithFallback: vi.fn().mockResolvedValue(undefined),
}))

async function mountRunTrace(initialItems: ChatStreamTimelineItem[]) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const items = ref(initialItems)
  const Host = defineComponent({
    setup() {
      return () => h(RunTrace, {
        items: items.value,
        isToolGroupOpen: () => false,
        isToolItemOpen: () => false,
      })
    },
  })
  const app = createApp(Host)
  app.use(i18n)
  app.mount(el)
  await nextTick()
  return { app, el, items }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
  vi.mocked(copyTextWithFallback).mockClear()
})

describe('RunTrace code block copy control', () => {
  it('decorates code blocks that appear during same-key text updates', async () => {
    const { app, el, items } = await mountRunTrace([
      { type: 'text', key: 'streaming-text', html: '<p>partial result</p>' },
    ])

    expect(el.querySelector('.code-copy-btn')).toBeNull()

    items.value = [
      {
        type: 'text',
        key: 'streaming-text',
        html: '<p>done</p><pre><code>console.log("late")</code></pre>',
      },
    ]
    await nextTick()
    await nextTick()

    const button = el.querySelector<HTMLButtonElement>('.code-copy-btn')
    expect(el.querySelector('.msg-ai-text pre code')?.textContent).toBe('console.log("late")')
    expect(button).not.toBeNull()

    button?.click()
    await Promise.resolve()

    expect(copyTextWithFallback).toHaveBeenCalledWith('console.log("late")')
    app.unmount()
  })
})

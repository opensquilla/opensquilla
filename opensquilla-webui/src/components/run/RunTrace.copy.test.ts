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
  it('compacts long tool input sections into a short summary', async () => {
    const prompt = Array.from({ length: 12 }, (_, index) => `line ${index + 1}: detailed image prompt`).join('\n')
    const inputRaw = JSON.stringify({
      filename: 'octopus-3d-clay.png',
      prompt,
      provider: 'openrouter',
    }, null, 2)

    const { app, el } = await mountRunTrace([
      {
        type: 'tool-group',
        key: 'image-generate-group',
        group: {
          groupId: 'image-generate-group',
          operationKey: 'image_generate',
          label: 'image_generate',
          iconName: 'gear',
          secondary: '',
          isRunning: false,
          isError: false,
          status: 'success',
          calls: [
            {
              toolId: 'tool-1',
              renderKey: 'tool-1',
              name: 'image_generate',
              displayName: 'image_generate',
              inputRaw,
              inputPreview: inputRaw.slice(0, 200),
              isRunning: false,
              status: 'success',
              isError: false,
              result: '{"status":"ok"}',
              resultPreview: '{"status":"ok"}',
              isOpen: false,
            },
          ],
        },
      },
    ])

    const inputSection = el.querySelector<HTMLElement>('.tool-row-section')
    expect(inputSection?.querySelector('.tool-row-section__compact')).not.toBeNull()
    expect(inputSection?.querySelector('pre')).toBeNull()
    expect(inputSection?.textContent).toContain('JSON')
    expect(inputSection?.textContent).toContain('octopus-3d-clay.png')
    expect(inputSection?.textContent).toContain('view full')

    app.unmount()
  })
  it('uses shell-specific summaries for compacted command input and stdout output', async () => {
    const command = [
      "python - <<'PY'",
      'import json',
      'payload = {',
      '  "filename": "octopus-3d-clay.png",',
      '  "provider": "openrouter",',
      '  "prompt": "\\n".join([',
      '    f"line {i}: detailed image prompt with many style details and lighting constraints"',
      '    for i in range(1, 28)',
      '  ]),',
      '}',
      'print(json.dumps(payload, indent=2))',
      '# keep this fixture long enough to exercise the compact shell summary',
      '# line 01: extra command context that would otherwise crowd the run trace',
      '# line 02: extra command context that would otherwise crowd the run trace',
      '# line 03: extra command context that would otherwise crowd the run trace',
      '# line 04: extra command context that would otherwise crowd the run trace',
      'PY',
    ].join('\n')
    const inputRaw = JSON.stringify({ command }, null, 2)
    const result = [
      'exit_code=0',
      '{',
      '  "filename": "octopus-3d-clay.png",',
      '  "artifact": {',
      '    "path": "/tmp/octopus-3d-clay.png",',
      '    "mime": "image/png"',
      '  }',
      '}',
    ].join('\n')

    const { app, el } = await mountRunTrace([
      {
        type: 'tool-group',
        key: 'shell-group',
        group: {
          groupId: 'shell-group',
          operationKey: 'shell',
          label: '运行命令',
          iconName: 'gear',
          secondary: '',
          isRunning: false,
          isError: false,
          status: 'success',
          calls: [
            {
              toolId: 'tool-1',
              renderKey: 'tool-1',
              name: 'shell',
              displayName: '运行命令',
              inputRaw,
              inputPreview: inputRaw.slice(0, 200),
              isRunning: false,
              status: 'success',
              isError: false,
              result,
              resultPreview: result.slice(0, 200),
              isOpen: false,
            },
          ],
        },
      },
    ])

    const sections = el.querySelectorAll<HTMLElement>('.tool-row-section')
    expect(sections[0]?.querySelector('.tool-row-section__compact')).not.toBeNull()
    expect(sections[0]?.textContent).toContain('shell command')
    expect(sections[0]?.textContent).toContain("command: python - <<'PY'")

    expect(sections[1]?.querySelector('.tool-row-section__compact')).not.toBeNull()
    expect(sections[1]?.textContent).toContain('shell result')
    expect(sections[1]?.textContent).toContain('exit_code=0')
    expect(sections[1]?.textContent).toContain('output: filename: octopus-3d-clay.png')
    expect(sections[1]?.textContent).toContain('artifact: { path: /tmp/octopus-3d-clay.png, mime: image/png }')
    expect(sections[1]?.textContent).not.toContain('[object Object]')

    app.unmount()
  })
})

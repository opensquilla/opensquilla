// @vitest-environment happy-dom

import { describe, expect, it } from 'vitest'

import { useChatTextRendering } from './useChatTextRendering'
import { buildShareDom } from './useChatShareExport'

describe('buildShareDom protocol-shaped documentation', () => {
  it('clones the complete rendered message into the share image stage', () => {
    const text = [
      'Document `<tool_calls>` inline.',
      '```xml',
      '<tool_calls><invoke name="demo"></invoke></tool_calls>',
      '```',
      'Keep `<｜DSML｜tool_calls>` too.',
      '<details><summary>View areas around line 10</summary>Visible note.</details>',
      'Final suffix.',
    ].join('\n')
    const source = document.createElement('article')
    source.className = 'msg msg-ai'
    source.dataset.shareMessageId = 'assistant-literal'
    const body = document.createElement('div')
    body.className = 'msg-body'
    body.innerHTML = useChatTextRendering().renderMarkdown(text)
    source.appendChild(body)

    const stage = buildShareDom([source])
    const sharedText = stage.querySelector('.msg-body')?.textContent || ''

    expect(sharedText).toContain('<tool_calls>')
    expect(sharedText).toContain('<｜DSML｜tool_calls>')
    expect(sharedText).toContain('Visible note.')
    expect(sharedText).toContain('Final suffix.')
  })
})

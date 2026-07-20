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

  it('drops a collapsed activity fold while keeping the final answer', () => {
    const source = document.createElement('article')
    source.className = 'msg msg-ai'
    source.dataset.shareMessageId = 'assistant-collapsed-activity'
    source.innerHTML = [
      '<details class="activity-fold">',
      '  <summary>Search the web ×2</summary>',
      '  <div class="activity-fold__body">Private execution trace</div>',
      '</details>',
      '<div class="timeline-text">Final answer remains visible.</div>',
    ].join('')

    const stage = buildShareDom([source])

    expect(stage.querySelector('.activity-fold')).toBeNull()
    expect(stage.textContent).not.toContain('Private execution trace')
    expect(stage.textContent).toContain('Final answer remains visible.')
  })

  it('exports an opened activity fold as static trace content', () => {
    const source = document.createElement('article')
    source.className = 'msg msg-ai'
    source.dataset.shareMessageId = 'assistant-open-activity'
    source.innerHTML = [
      '<details class="activity-fold" open>',
      '  <summary>Search the web ×2</summary>',
      '  <div class="activity-fold__body">Execution trace selected for sharing.</div>',
      '</details>',
      '<div class="timeline-text">Final answer.</div>',
    ].join('')

    const stage = buildShareDom([source])
    const trace = stage.querySelector('.chat-share-export-thinking')

    expect(stage.querySelector('.activity-fold')).toBeNull()
    expect(trace?.textContent).toContain('Search the web ×2')
    expect(trace?.textContent).toContain('Execution trace selected for sharing.')
    expect(stage.textContent).toContain('Final answer.')
  })
})

// @vitest-environment happy-dom

import { beforeEach, describe, expect, it } from 'vitest'
import { createApp, nextTick } from 'vue'
import i18n from '@/i18n'
import type { ChatToolCall } from '@/types/chat'
import type { SourcePart } from '@/types/parts'
import SourcesRow from './SourcesRow.vue'

const calls: ChatToolCall[] = []

async function mountSources(sources: SourcePart[]) {
  const el = document.createElement('div')
  document.body.appendChild(el)
  const app = createApp(SourcesRow, { calls, sources })
  app.use(i18n)
  app.mount(el)
  await nextTick()
  el.querySelector<HTMLButtonElement>('.sources-row__toggle')?.click()
  await nextTick()
  return { app, el }
}

beforeEach(() => {
  i18n.global.locale.value = 'en'
  document.body.innerHTML = ''
})

describe('SourcesRow Knowledge cards', () => {
  it('renders metadata-rich Knowledge cards and keeps missing or unsafe URLs non-clickable', async () => {
    const sources: SourcePart[] = [
      {
        kind: 'knowledge',
        sourceId: 1,
        evidenceId: 'ev_no_url',
        rank: 1,
        title: 'report.pdf',
        documentTitle: 'Quarterly report',
        documentId: 'doc_report',
        fileName: 'report.pdf',
        sourcePath: 'datasets/reports/report.pdf',
        source: 'datasets',
        locator: 'page 7',
        snippet: 'x'.repeat(401),
        snippetTruncated: true,
      },
      {
        kind: 'knowledge',
        sourceId: 2,
        evidenceId: 'ev_safe',
        title: 'Safe source',
        url: 'https://knowledge.example/source',
        domain: 'knowledge.example',
        snippet: 'safe evidence',
        snippetTruncated: false,
      },
      {
        kind: 'knowledge',
        sourceId: 3,
        evidenceId: 'ev_unsafe',
        title: 'Unsafe source',
        url: 'javascript:alert(1)',
        snippet: 'unsafe URL must not become a link',
        snippetTruncated: false,
      },
    ]

    const { app, el } = await mountSources(sources)
    const noUrl = el.querySelector<HTMLElement>('[data-source-id="1"]')
    const safe = el.querySelector<HTMLElement>('[data-source-id="2"]')
    const unsafe = el.querySelector<HTMLElement>('[data-source-id="3"]')

    expect(noUrl?.querySelector('a')).toBeNull()
    expect(noUrl?.textContent).toContain('report.pdf')
    expect(noUrl?.textContent).toContain('Quarterly report')
    expect(noUrl?.textContent).toContain('datasets/reports/report.pdf')
    expect(noUrl?.textContent).toContain('datasets')
    expect(noUrl?.textContent).toContain('page 7')
    const snippet = noUrl?.querySelector('.sources-row__snippet')?.textContent || ''
    expect(snippet).toBe(`${'x'.repeat(400)}…`)

    expect(safe?.querySelector('a')?.getAttribute('href')).toBe('https://knowledge.example/source')
    expect(unsafe?.querySelector('a')).toBeNull()
    expect(unsafe?.textContent).toContain('Unsafe source')
    app.unmount()
  })

  it('keeps legacy Web cards behaviorally unchanged when kind is absent', async () => {
    const sources: SourcePart[] = [
      {
        sourceId: 1,
        url: 'https://example.com/result',
        title: 'Example result',
        domain: 'example.com',
        fetched: false,
        fetchStatus: 'not_requested',
      },
    ]

    const { app, el } = await mountSources(sources)
    const item = el.querySelector<HTMLElement>('[data-source-id="1"]')
    const link = item?.querySelector<HTMLAnchorElement>('a.sources-row__link')

    expect(link?.getAttribute('href')).toBe('https://example.com/result')
    expect(item?.querySelector('.sources-row__title')?.textContent).toBe('Example result')
    expect(item?.querySelector('.sources-row__status')?.textContent).toBe('Search result')
    expect(item?.querySelector('.sources-row__domain')?.textContent).toBe('example.com')
    app.unmount()
  })

  it('derives Knowledge cards from structured call sources without result recovery', async () => {
    const call: ChatToolCall = {
      toolId: 'knowledge-1',
      name: 'knowledge_search',
      displayName: 'knowledge_search',
      inputPreview: '',
      isRunning: false,
      status: 'success',
      isError: false,
      result: JSON.stringify({
        results: [{ chunk: { content: 'full model-visible chunk' } }],
      }),
      resultPreview: '',
      sources: [{
        kind: 'knowledge',
        evidenceId: 'ev_call',
        citation: { title: 'Structured source' },
        snippet: 'sidecar only',
        snippetTruncated: false,
      }],
      isOpen: false,
    }
    const el = document.createElement('div')
    document.body.appendChild(el)
    const app = createApp(SourcesRow, { calls: [call] })
    app.use(i18n)
    app.mount(el)
    await nextTick()

    expect(el.textContent).toContain('Sources')
    expect(el.textContent).not.toContain('full model-visible chunk')
    app.unmount()
  })
})

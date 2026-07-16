// @vitest-environment happy-dom

import { describe, expect, it, vi } from 'vitest'
import { decorateCitations } from './citations'
import type { SourcePart } from '@/types/parts'

const sources: SourcePart[] = [
  {
    sourceId: 1,
    url: 'https://example.com/a',
    title: 'Example result',
    domain: 'example.com',
  },
]

describe('decorateCitations', () => {
  it('creates pills for valid citations and reports missing ids', () => {
    const root = document.createElement('div')
    root.textContent = 'Supported [1], missing [9].'
    const onActivate = vi.fn()
    let missing: number[] = []

    const created = decorateCitations(root, sources, {
      onActivate,
      labelFor: () => 'Example result',
      onMissingCitations: ids => {
        missing = ids
      },
    })

    const pill = root.querySelector<HTMLButtonElement>('button.citation-pill')
    expect(created).toBe(1)
    expect(pill?.textContent).toBe('[1]')
    expect(pill?.getAttribute('data-citation')).toBe('1')
    expect(root.textContent).toContain('[9]')
    expect(missing).toEqual([9])
  })

  it('does not report missing citations when there are no sources', () => {
    const root = document.createElement('div')
    root.textContent = 'Nothing should be upgraded [1].'
    const onMissingCitations = vi.fn()

    const created = decorateCitations(root, [], {
      onActivate: vi.fn(),
      labelFor: () => '',
      onMissingCitations,
    })

    expect(created).toBe(0)
    expect(root.querySelector('button.citation-pill')).toBeNull()
    expect(onMissingCitations).not.toHaveBeenCalled()
  })

  it('decorates citations for Knowledge sources without URL or domain fields', () => {
    const knowledgeSources: SourcePart[] = [
      {
        kind: 'knowledge',
        sourceId: 1,
        evidenceId: 'ev_1',
        title: 'Local handbook.pdf',
        documentTitle: 'Local handbook',
        locator: 'page 3',
      },
    ]
    const root = document.createElement('div')
    root.textContent = 'Knowledge-backed answer [1].'
    const onActivate = vi.fn()

    const created = decorateCitations(root, knowledgeSources, {
      onActivate,
      labelFor: sourceId => knowledgeSources[sourceId - 1]?.title || '',
    })

    const pill = root.querySelector<HTMLButtonElement>('button.citation-pill')
    expect(created).toBe(1)
    expect(pill?.getAttribute('aria-label')).toBe(
      'Jump to source 1: Local handbook.pdf',
    )
    pill?.click()
    expect(onActivate).toHaveBeenCalledWith(1)
  })
})

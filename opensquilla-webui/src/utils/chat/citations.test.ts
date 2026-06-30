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
})

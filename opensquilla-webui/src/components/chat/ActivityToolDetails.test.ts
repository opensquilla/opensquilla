import { describe, expect, it } from 'vitest'

import activityToolDetailsSource from './ActivityToolDetails.vue?raw'

function ruleBody(selector: string): string {
  const selectorStart = activityToolDetailsSource.indexOf(selector)
  expect(selectorStart).toBeGreaterThanOrEqual(0)

  const blockStart = activityToolDetailsSource.indexOf('{', selectorStart)
  const blockEnd = activityToolDetailsSource.indexOf('}', blockStart)
  return activityToolDetailsSource.slice(blockStart + 1, blockEnd)
}

describe('ActivityToolDetails text hierarchy', () => {
  it('keeps compact detail text on AA contrast tokens', () => {
    expect(ruleBody('.activity-tool-details__summary')).toContain(
      'color: var(--text-muted);',
    )
    expect(ruleBody('.activity-tool-details__line--target')).toContain(
      'color: var(--text-muted);',
    )
    expect(ruleBody('.activity-tool-details__line--code')).toContain(
      'color: var(--text-muted);',
    )
    expect(ruleBody('.activity-tool-details__fallback')).toContain(
      'color: var(--text-muted);',
    )
  })
})

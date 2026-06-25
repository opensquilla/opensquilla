import { describe, expect, it } from 'vitest'
import { getConsoleNavigationSections, getWorkNavigationSection } from './nav'

// Guards the route nav taxonomy that the sidebar rail, the mobile drawer, and
// the command palette all read. Before this, the rail rows and the palette Work
// band were hardcoded path lists that silently drifted from route meta; these
// assertions pin the band membership so a future meta edit can't reintroduce a
// vanished or double-listed destination unnoticed.

describe('getConsoleNavigationSections', () => {
  it('resolves to Manage then Monitor with the expected members in order', () => {
    const sections = getConsoleNavigationSections()
    expect(sections.map((s) => s.label)).toEqual(['Manage', 'Monitor'])

    const [manage, monitor] = sections
    expect(manage.items.map((i) => i.path)).toEqual(['/approvals', '/agents', '/channels'])
    expect(monitor.items.map((i) => i.path)).toEqual(['/overview', '/usage', '/logs'])
  })
})

describe('getWorkNavigationSection', () => {
  it('pins Sessions, Cron, Skills as the level-1 rail rows, navOrder-sorted', () => {
    expect(getWorkNavigationSection().map((i) => i.path)).toEqual(['/sessions', '/cron', '/skills'])
  })

  it('excludes Chat (it is the New-chat action, not a row) and Approvals (demoted to More)', () => {
    const paths = getWorkNavigationSection().map((i) => i.path)
    expect(paths).not.toContain('/chat')
    expect(paths).not.toContain('/approvals')
  })
})

describe('navigation taxonomy de-dup invariant', () => {
  it('lists each destination exactly once across the Work band and the console fold', () => {
    const paths = [
      ...getWorkNavigationSection().map((i) => i.path),
      ...getConsoleNavigationSections().flatMap((s) => s.items.map((i) => i.path)),
    ]
    const counts = paths.reduce<Record<string, number>>((acc, p) => {
      acc[p] = (acc[p] ?? 0) + 1
      return acc
    }, {})
    for (const path of ['/sessions', '/cron', '/skills', '/approvals', '/agents', '/channels', '/overview', '/usage', '/logs']) {
      expect(counts[path]).toBe(1)
    }
  })
})

import { describe, expect, it } from 'vitest'
import { getConsoleNavigationSections, getMoreNavigationSections, getWorkNavigationSection } from './nav'

// Guards the route nav taxonomy that the sidebar rail, the mobile drawer, and
// the command palette all read. Before this, the rail rows and the palette Work
// band were hardcoded path lists that silently drifted from route meta; these
// assertions pin the band membership so a future meta edit can't reintroduce a
// vanished or double-listed destination unnoticed.
//
// Current IA: the Work band pins Sessions + Overview (the Monitor hub, which
// hosts Channels/Usage/Logs as tabs), the Build band (group Operate) holds
// Agents/Skills/Cron, and Approvals is retired from the nav (/approvals
// redirects to /sessions).

describe('getConsoleNavigationSections', () => {
  it('resolves to the Build band with the expected members in order', () => {
    const sections = getConsoleNavigationSections()
    expect(sections.map((s) => s.group)).toEqual(['Operate'])

    const [build] = sections
    expect(build.items.map((i) => i.path)).toEqual(['/agents', '/skills', '/cron'])
  })

  it('localizes the band label instead of exposing the taxonomy key', () => {
    const [build] = getConsoleNavigationSections()
    expect(build.label).not.toBe('Operate')
    expect(build.label.length).toBeGreaterThan(0)
  })
})

describe('getMoreNavigationSections', () => {
  it('is an alias of the full console sections (the More fold is retired)', () => {
    expect(getMoreNavigationSections()).toEqual(getConsoleNavigationSections())
  })
})

describe('getWorkNavigationSection', () => {
  it('pins Sessions then Overview as the level-1 rail rows, navOrder-sorted', () => {
    expect(getWorkNavigationSection().map((i) => i.path)).toEqual(['/sessions', '/overview'])
  })

  it('excludes Chat (it is the New-chat action, not a row)', () => {
    expect(getWorkNavigationSection().map((i) => i.path)).not.toContain('/chat')
  })
})

describe('navigation taxonomy invariants', () => {
  it('lists each destination exactly once across the Work band and the console bands', () => {
    const paths = [
      ...getWorkNavigationSection().map((i) => i.path),
      ...getConsoleNavigationSections().flatMap((s) => s.items.map((i) => i.path)),
    ]
    const counts = paths.reduce<Record<string, number>>((acc, p) => {
      acc[p] = (acc[p] ?? 0) + 1
      return acc
    }, {})
    for (const path of ['/sessions', '/overview', '/agents', '/skills', '/cron']) {
      expect(counts[path]).toBe(1)
    }
  })

  it('keeps the retired and hub-hosted routes out of the nav bands', () => {
    const paths = [
      ...getWorkNavigationSection().map((i) => i.path),
      ...getConsoleNavigationSections().flatMap((s) => s.items.map((i) => i.path)),
    ]
    // Approvals is retired (redirects to /sessions); Channels/Usage/Logs live
    // as Monitor-hub tabs behind the single Overview row.
    for (const path of ['/approvals', '/channels', '/usage', '/logs']) {
      expect(paths).not.toContain(path)
    }
  })
})

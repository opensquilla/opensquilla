import { describe, expect, it } from 'vitest'

import {
  formatEstimatedActivity,
  isProfileSourceKind,
  profileSourceGroup,
  profileSourceLabelKey,
} from './profileSourceKind'

describe('profile source presentation', () => {
  it('treats CLI and Desktop as supported installations and Portable as historical', () => {
    expect(profileSourceGroup('cli-home')).toBe('supported')
    expect(profileSourceGroup('desktop-home')).toBe('supported')
    expect(profileSourceGroup('windows-portable')).toBe('historical')
  })

  it('maps protocol kinds to UI translation keys without exposing raw values', () => {
    expect(profileSourceLabelKey('cli-home')).toBe('setup.runtime.migrationSourceCli')
    expect(profileSourceLabelKey('desktop-home')).toBe('setup.runtime.migrationSourceDesktop')
    expect(profileSourceLabelKey('windows-portable')).toBe(
      'setup.runtime.migrationSourceWindowsPortable',
    )
    expect(profileSourceLabelKey('future-kind')).toBe('setup.runtime.migrationSourceUnknown')
  })

  it('accepts only the three stable migration protocol kinds', () => {
    expect(isProfileSourceKind('cli-home')).toBe(true)
    expect(isProfileSourceKind('desktop-home')).toBe(true)
    expect(isProfileSourceKind('windows-portable')).toBe(true)
    expect(isProfileSourceKind('legacy')).toBe(false)
    expect(isProfileSourceKind(null)).toBe(false)
  })

  it('formats estimated activity in the local language instead of exposing ISO text', () => {
    const now = Date.parse('2026-07-12T10:00:00Z')
    expect(formatEstimatedActivity('2026-07-10T10:00:00Z', 'en', now)).toBe('2 days ago')
    expect(formatEstimatedActivity('2026-07-10T10:00:00Z', 'zh-Hans', now)).toBe('前天')
    expect(formatEstimatedActivity('not-a-date', 'en', now)).toBeNull()
  })
})
